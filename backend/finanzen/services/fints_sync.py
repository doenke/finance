"""FinTS (HBCI) access via python-fints, run as background jobs so TAN prompts can be answered in the browser.

A job keeps the FinTS dialog open in its own thread. If the bank asks for a TAN, the job publishes the
challenge and waits; the web request delivers the TAN (or, for app approval/decoupled, the job polls
the bank until the user has confirmed). PINs only live in memory for the duration of a job unless the
user chose to store them (encrypted).
"""

from __future__ import annotations

import base64
import hashlib
import logging
import threading
import time
import unicodedata
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from .. import cache, kinds
from ..config import Settings
from ..models import Account, BalanceSnapshot, BankLogin, Instrument, Price, Trade, Transaction
from ..secrets import SecretsError, decrypt
from .holdings import TradeIn, build_positions

log = logging.getLogger("finanzen.fints")

TAN_TIMEOUT = 300  # seconds to wait for a TAN or an app approval
DECOUPLED_POLL = 3
FIRST_SYNC_DAYS = 90  # most banks allow 90 days without an extra TAN

# FinTS account types (UPD "Kontoart") -> our account kind
ACCOUNT_TYPES = [
    (range(1, 10), "giro"),
    (range(10, 20), "tagesgeld"),
    (range(20, 30), "festgeld"),
    (range(30, 40), "depot"),
    (range(40, 50), "kredit"),
    (range(50, 60), "kreditkarte"),
    (range(60, 70), "depot"),
    (range(70, 80), "altersvorsorge"),
    (range(80, 90), "altersvorsorge"),
]


def suggest_kind(account_type: int | None) -> str:
    for r, kind in ACCOUNT_TYPES:
        if account_type is not None and account_type in r:
            return kind
    return "giro"


class TanRequired(Exception):
    """The bank wants a TAN but nobody can answer (automatic sync)."""


class JobCancelled(Exception):
    pass


def is_tan_response(obj: Any) -> bool:
    try:
        from fints.client import NeedTANResponse

        if isinstance(obj, NeedTANResponse):
            return True
    except ImportError:  # pragma: no cover
        pass
    return bool(getattr(obj, "_needs_tan", False))


class BankRejected(Exception):
    """The bank answered with an HTTP error; `messages` holds its FinTS return codes (if readable)."""

    def __init__(self, status: int, messages: list[tuple[str, str]]) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status
        self.messages = messages


def bank_messages(raw: bytes) -> list[tuple[str, str]]:
    """Return codes (HIRMG/HIRMS) from a base64 encoded FinTS answer; empty if it is not one."""
    try:
        from fints.message import FinTSInstituteMessage

        message = FinTSInstituteMessage(segments=base64.b64decode(raw.decode("iso-8859-1")))
        result = []
        for name in ("HIRMG", "HIRMS"):
            for seg in message.find_segments(name):
                for resp in seg.responses:
                    result.append((str(resp.code), str(resp.text or "").strip()))
        return result
    except Exception:  # noqa: BLE001
        return []


def _connection(url: str):
    """python-fints connection that records every return code of the bank.

    python-fints turns many rejections into generic errors (e.g. FinTSClientError for 9010), and some
    banks (DKB) answer the closing message of a failed dialog with an empty HTTP 400 – the real reason
    is in an earlier answer. `codes` keeps all of them so the job can show what the bank said.
    """
    from fints.connection import FinTSHTTPSConnection

    class Connection(FinTSHTTPSConnection):
        codes: list[tuple[str, str]]

        def send(self, msg):
            original = self.session.post

            def post(*args, **kwargs):
                res = original(*args, **kwargs)
                found = bank_messages(res.content)
                self.codes.extend(found)
                if not 200 <= res.status_code < 300:
                    raise BankRejected(res.status_code, found or list(self.codes))
                return res

            self.session.post = post
            try:
                return super().send(msg)
            finally:
                self.session.post = original

    conn = Connection(url)
    conn.codes = []
    return conn


def default_client_factory(login: BankLogin, pin: str, product_id: str):
    from fints.client import FinTS3PinTanClient

    state = base64.b64decode(login.client_state) if login.client_state else None
    client = FinTS3PinTanClient(
        login.blz,
        unicodedata.normalize("NFC", login.username),
        pin,
        login.server_url,
        customer_id=unicodedata.normalize("NFC", login.customer_id) if login.customer_id else None,
        product_id=product_id,
        from_data=state,
        tan_medium=login.tan_medium,
    )
    client.connection = _connection(login.server_url)
    return client


ClientFactory = Callable[[BankLogin, str, str], Any]


@dataclass
class Job:
    id: str
    login_id: int
    kind: str  # discover | sync
    interactive: bool
    status: str = "running"  # running | need_tan | need_choice | done | error | cancelled
    message: str = "Verbinde mit der Bank …"
    challenge: dict | None = None
    choices: list[dict] | None = None
    choice_kind: str = ""
    result: dict | None = None
    error: str = ""
    created: float = field(default_factory=time.time)
    _event: threading.Event = field(default_factory=threading.Event, repr=False)
    _answer: str | None = field(default=None, repr=False)
    _cancel: bool = field(default=False, repr=False)

    def public(self) -> dict:
        return {
            "id": self.id,
            "login_id": self.login_id,
            "kind": self.kind,
            "status": self.status,
            "message": self.message,
            "challenge": self.challenge,
            "choices": self.choices,
            "choice_kind": self.choice_kind,
            "result": self.result,
            "error": self.error,
        }

    def wait_answer(self, timeout: float) -> str | None:
        self._event.clear()
        self._event.wait(timeout)
        if self._cancel:
            raise JobCancelled()
        answer, self._answer = self._answer, None
        return answer

    def answer(self, value: str) -> None:
        self._answer = value
        self._event.set()

    def cancel(self) -> None:
        self._cancel = True
        self._event.set()


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._busy_logins: set[int] = set()

    def start(
        self,
        kind: str,
        login_id: int,
        pin: str | None,
        settings: Settings,
        make_session: sessionmaker,
        interactive: bool = True,
        factory: ClientFactory = default_client_factory,
        account_ids: list[int] | None = None,
        background: bool = True,
    ) -> Job:
        with self._lock:
            self._expire()
            if login_id in self._busy_logins:
                raise RuntimeError("Für diesen Bankzugang läuft schon ein Abruf.")
            self._busy_logins.add(login_id)
            job = Job(id=uuid.uuid4().hex, login_id=login_id, kind=kind, interactive=interactive)
            self._jobs[job.id] = job

        def target() -> None:
            try:
                run_job(job, pin, settings, make_session, factory, account_ids)
            finally:
                with self._lock:
                    self._busy_logins.discard(login_id)

        if background:
            threading.Thread(target=target, daemon=True, name=f"fints-{job.id[:8]}").start()
        else:
            target()
        return job

    def cancel_all(self) -> None:
        for job in list(self._jobs.values()):
            if job.status in ("running", "need_tan", "need_choice"):
                job.cancel()

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def _expire(self) -> None:
        cutoff = time.time() - 1800
        for key in [k for k, j in self._jobs.items() if j.created < cutoff and j.status in ("done", "error", "cancelled")]:
            del self._jobs[key]


jobs = JobManager()


# --- Job execution --------------------------------------------------------------------------------


def _challenge_of(resp: Any) -> dict:
    data: dict[str, Any] = {"text": getattr(resp, "challenge", "") or "", "decoupled": bool(getattr(resp, "decoupled", False))}
    html = getattr(resp, "challenge_html", None)
    if html:
        data["html"] = str(html)
    matrix = getattr(resp, "challenge_matrix", None)
    if matrix:
        mime, content = matrix
        data["image"] = f"data:{mime};base64,{base64.b64encode(content).decode()}"
    hhduc = getattr(resp, "challenge_hhduc", None)
    if hhduc:
        data["hhduc"] = hhduc
    return data


def _handle(job: Job, client: Any, resp: Any, db: Session | None = None) -> Any:
    """Resolve TAN prompts until the bank returns the actual result."""
    while is_tan_response(resp):
        if not job.interactive:
            raise TanRequired()
        if db is not None:
            db.commit()  # never hold a transaction while waiting for the user
        job.challenge = _challenge_of(resp)
        job.status = "need_tan"
        if job.challenge["decoupled"]:
            job.message = "Bitte den Auftrag in der Banking-App freigeben."
            deadline = time.time() + TAN_TIMEOUT
            while True:
                if time.time() > deadline:
                    raise TimeoutError("Die Freigabe hat zu lange gedauert.")
                job.wait_answer(DECOUPLED_POLL)
                next_resp = client.send_tan(resp, "")
                if is_tan_response(next_resp) and getattr(next_resp, "decoupled", False):
                    resp = next_resp
                    continue
                resp = next_resp
                break
        else:
            job.message = "Bitte die TAN eingeben."
            tan = job.wait_answer(TAN_TIMEOUT)
            if not tan:
                raise TimeoutError("Es wurde keine TAN eingegeben.")
            job.status = "running"
            job.message = "TAN wird geprüft …"
            resp = client.send_tan(resp, tan.strip())
        job.status = "running"
        job.challenge = None
    return resp


def _choose(job: Job, kind: str, options: list[dict], text: str, db: Session | None = None) -> str:
    if not job.interactive:
        raise TanRequired()
    if db is not None:
        db.commit()  # never hold a transaction while waiting for the user
    job.choices = options
    job.choice_kind = kind
    job.status = "need_choice"
    job.message = text
    answer = job.wait_answer(TAN_TIMEOUT)
    job.choices = None
    job.status = "running"
    if not answer:
        raise TimeoutError("Es wurde nichts ausgewählt.")
    return answer


def _prepare_tan(job: Job, client: Any, login: BankLogin, db: Session) -> None:
    if login.tan_mechanism:
        client.set_tan_mechanism(login.tan_mechanism)
        return
    job.message = "Frage TAN-Verfahren ab …"
    client.fetch_tan_mechanisms()
    mechanisms = client.get_tan_mechanisms()
    options = [{"value": sf, "label": getattr(p, "name", sf)} for sf, p in mechanisms.items() if sf != "999"]
    if not options:
        return
    choice = options[0]["value"] if len(options) == 1 else _choose(job, "tan_mechanism", options, "Welches TAN-Verfahren möchtest du nutzen?", db)
    client.set_tan_mechanism(choice)
    login.tan_mechanism = choice
    login.tan_mechanism_name = next(o["label"] for o in options if o["value"] == choice)
    if client.is_tan_media_required() and not login.tan_medium:
        _, media = client.get_tan_media()
        names = [m.tan_medium_name for m in media if getattr(m, "tan_medium_name", None)]
        if names:
            medium = names[0] if len(names) == 1 else _choose(job, "tan_medium", [{"value": n, "label": n} for n in names], "Welches Gerät soll die TAN erzeugen?", db)
            client.set_tan_medium(next(m for m in media if m.tan_medium_name == medium))
            login.tan_medium = medium


def _sepa(account: Account):
    from fints.models import SEPAAccount

    f = (account.details or {}).get("fints") or {}
    return SEPAAccount(iban=f.get("iban"), bic=f.get("bic"), accountnumber=f.get("accountnumber"), subaccount=f.get("subaccount"), blz=f.get("blz"))


def run_job(job: Job, pin: str | None, settings: Settings, make_session: sessionmaker, factory: ClientFactory, account_ids: list[int] | None) -> None:
    messages: list[tuple[str, str]] = []  # return codes the bank sent during this job
    client: Any = None
    with make_session() as db:
        login = db.get(BankLogin, job.login_id)
        try:
            if login is None:
                raise RuntimeError("Bankzugang nicht gefunden.")
            if not settings.fints_product_id:
                raise RuntimeError("FINTS_PRODUCT_ID ist nicht gesetzt.")
            if pin is None:
                if not login.pin_encrypted:
                    raise RuntimeError("Für diesen Bankzugang ist keine PIN gespeichert.")
                pin = decrypt(settings.secrets_key, login.pin_encrypted, f"bank_login:{login.id}")
            client = factory(login, pin, settings.fints_product_id)
            if hasattr(client, "add_response_callback"):
                client.add_response_callback(lambda _seg, resp: messages.append((str(resp.code), str(resp.text or "").strip())))
            db.commit()  # end the read transaction; the job may wait for the user
            _prepare_tan(job, client, login, db)
            job.message = "Verbinde mit der Bank …"
            with client:
                init = getattr(client, "init_tan_response", None)
                if is_tan_response(init):
                    _handle(job, client, init, db)
                if job.kind == "discover":
                    job.result = _discover(job, client, db, login)
                else:
                    job.result = _sync(job, client, db, login, account_ids)
            login.client_state = base64.b64encode(client.deconstruct(including_private=True)).decode()
            login.last_error = ""
            login.needs_tan = False
            if job.kind == "sync":
                login.last_sync_at = datetime.now(UTC)
            db.commit()
            cache.bump()
            job.status = "done"
            job.message = "Fertig."
        except JobCancelled:
            db.rollback()
            job.status = "cancelled"
            job.message = "Abgebrochen."
        except TanRequired:
            db.rollback()
            job.status = "error"
            job.error = "Die Bank verlangt eine TAN – bitte einmal von Hand aktualisieren."
            _record_error(make_session, job.login_id, job.error, needs_tan=True)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            job.status = "error"
            messages = messages + list(getattr(getattr(client, "connection", None), "codes", None) or [])
            job.error = _friendly_error(exc, messages)
            codes = [c for c, _ in (exc.messages if isinstance(exc, BankRejected) else messages) if c[:1] in "39"]
            log.warning("fints job failed: %s %s", exc.__class__.__name__, " ".join(codes))
            _record_error(make_session, job.login_id, job.error)
        finally:
            pin = None  # noqa: F841 - drop the PIN reference as early as possible


def _record_error(make_session: sessionmaker, login_id: int, message: str, needs_tan: bool = False) -> None:
    with make_session() as db:
        login = db.get(BankLogin, login_id)
        if login:
            login.last_error = message[:500]
            login.needs_tan = needs_tan
            db.commit()


PIN_CODES = {"9340", "9910", "9930", "9931", "9942"}


def _bank_text(messages: list[tuple[str, str]]) -> str | None:
    """Readable explanation from the bank's error codes (9xxx), with hints for the common ones."""
    errors = [(c, t) for c, t in messages if c.startswith("9") and c not in ("9800", "9050")]
    if not errors:
        errors = [(c, t) for c, t in messages if c.startswith("9")]
    if not errors:
        return None
    codes = {c for c, _ in errors}
    if codes & {"9078", "9079"}:
        return "Die Bank kennt die FinTS-Produkt-ID nicht (9078). Prüfe FINTS_PRODUCT_ID – eine frisch registrierte Nummer ist manchmal erst nach einigen Tagen bei allen Banken bekannt."
    if codes & PIN_CODES:
        return (
            "Die Bank hat die Anmeldung abgelehnt: Anmeldename oder PIN ist falsch. Gemeint ist der Anmeldename bzw. die "
            "Legitimations-ID aus dem Online-Banking, nicht dein Name. Achtung: Nach drei falschen Versuchen sperrt die Bank den Zugang."
        )
    if "9010" in codes:
        return "Die Bank lehnt die Anfrage ab – passen Bankleitzahl und FinTS-Adresse zusammen?"
    text = "; ".join(f"{c} {t}".strip() for c, t in errors[:2])
    return f"Die Bank meldet: {text}"


def _friendly_error(exc: Exception, messages: list[tuple[str, str]] | None = None) -> str:
    name = exc.__class__.__name__
    if isinstance(exc, BankRejected):
        return _bank_text(exc.messages) or _bank_text(messages or []) or f"Die Bank hat die Anfrage ohne Begründung abgelehnt (HTTP {exc.status})."
    explained = _bank_text(messages or [])
    if name == "FinTSClientPINError":
        return explained or "Die Bank hat die Anmeldung abgelehnt – stimmen Anmeldename und PIN?"
    if name == "FinTSClientTemporaryAuthError":
        return "Der Zugang ist bei der Bank vorübergehend gesperrt."
    if name == "FinTSSCARequiredError":
        return "Die Bank verlangt eine starke Authentifizierung (TAN)."
    if name == "FinTSConnectionError" and "Bad status code" in str(exc):
        return explained or f"Die Bank hat die Anfrage abgelehnt ({exc})."
    if name in ("FinTSConnectionError", "ConnectionError", "RequestException") or "Connection" in name:
        return "Die Bank ist nicht erreichbar – stimmt die FinTS-Adresse?"
    if isinstance(exc, SecretsError | TimeoutError | RuntimeError):
        return str(exc)
    if isinstance(exc, UnicodeEncodeError):
        return "Anmeldename oder Kunden-ID enthält Zeichen, die per FinTS nicht übertragen werden können. Nimm die Legitimations-ID aus dem Online-Banking."
    if name == "FinTSUnsupportedOperation":
        return "Die Bank bietet diese Abfrage per FinTS nicht an."
    return explained or f"Fehler beim Abruf ({name})."


def _discover(job: Job, client: Any, db: Session, login: BankLogin) -> dict:
    job.message = "Lese Konten …"
    _handle(job, client, client.get_sepa_accounts(), db)
    info = client.get_information()
    linked = {
        ((a.details or {}).get("fints") or {}).get("accountnumber"): a.id
        for a in db.scalars(select(Account).where(Account.bank_login_id == login.id)).all()
    }
    accounts = []
    for acc in info.get("accounts", []):
        number = acc.get("account_number")
        bank_id = acc.get("bank_identifier")
        blz = getattr(bank_id, "bank_code", None) or login.blz
        accounts.append(
            {
                "iban": acc.get("iban"),
                "accountnumber": number,
                "subaccount": acc.get("subaccount_number"),
                "blz": blz,
                "bic": None,
                "type": acc.get("type"),
                "suggested_kind": suggest_kind(acc.get("type")),
                "product_name": acc.get("product_name") or "",
                "owner": " / ".join(acc.get("owner_name") or []),
                "currency": acc.get("currency") or "EUR",
                "linked_account_id": linked.get(number),
            }
        )
    return {"bank": (info.get("bank") or {}).get("name", ""), "accounts": accounts}


def _sync(job: Job, client: Any, db: Session, login: BankLogin, account_ids: list[int] | None) -> dict:
    stmt = select(Account).where(Account.bank_login_id == login.id, Account.closed.is_(False))
    if account_ids:
        stmt = stmt.where(Account.id.in_(account_ids))
    summary: list[dict] = []
    for account in db.scalars(stmt).all():
        job.message = f"Aktualisiere {account.name} …"
        mode = kinds.KINDS[account.kind].mode
        entry: dict[str, Any] = {"account_id": account.id, "name": account.name}
        try:
            sepa = _sepa(account)
            if mode == kinds.HOLDINGS:
                holdings = _handle(job, client, client.get_holdings(sepa), db)
                entry.update(apply_holdings(db, account, holdings))
            else:
                balance = _handle(job, client, client.get_balance(sepa), db)
                if balance is not None:
                    entry["balance"] = str(apply_balance(db, account, balance))
                if mode == kinds.CASH:
                    start = _transactions_start(db, account)
                    txs = _handle(job, client, client.get_transactions(sepa, start, date.today()), db)
                    entry["new_transactions"] = apply_transactions(db, account, txs or [])
            db.commit()  # each account is saved on its own
        except (TanRequired, JobCancelled, TimeoutError):
            raise
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            entry["error"] = _friendly_error(exc)
        summary.append(entry)
    return {"accounts": summary}


def _transactions_start(db: Session, account: Account) -> date:
    last = db.scalar(select(func.max(Transaction.booking_date)).where(Transaction.account_id == account.id, Transaction.external_id.like("fints:%")))
    return (last - timedelta(days=10)) if last else date.today() - timedelta(days=FIRST_SYNC_DAYS)


def _dec(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    amount = getattr(value, "amount", value)
    return Decimal(str(amount))


def apply_balance(db: Session, account: Account, balance: Any) -> Decimal:
    amount = _dec(getattr(balance, "amount", balance))
    day = getattr(balance, "date", None) or date.today()
    day = date(day.year, day.month, day.day)
    if kinds.KINDS[account.kind].mode == kinds.LOAN:
        amount = -abs(amount)
    row = db.scalar(select(BalanceSnapshot).where(BalanceSnapshot.account_id == account.id, BalanceSnapshot.date == day))
    if row is None:
        row = BalanceSnapshot(account_id=account.id, date=day)
        db.add(row)
    row.amount = amount
    row.source = "fints"
    return amount


def _tx_fields(tx: Any) -> dict:
    data = getattr(tx, "data", tx) or {}
    booking = data.get("date") or data.get("entry_date")
    value = data.get("entry_date") or data.get("date")
    purpose = data.get("purpose") or ""
    if isinstance(purpose, list):
        purpose = " ".join(purpose)
    return {
        "booking_date": date(booking.year, booking.month, booking.day) if booking else None,
        "value_date": date(value.year, value.month, value.day) if value else None,
        "amount": _dec(data.get("amount")),
        "counterparty": (data.get("applicant_name") or data.get("recipient_name") or "")[:255],
        "purpose": purpose.strip(),
        "posting_text": data.get("posting_text") or "",
        "reference": data.get("end_to_end_reference") or data.get("customer_reference") or "",
        "iban": data.get("applicant_iban") or "",
    }


def apply_transactions(db: Session, account: Account, txs: list[Any]) -> int:
    seen: dict[tuple, int] = {}
    created = 0
    rows = []
    for tx in txs:
        f = _tx_fields(tx)
        if not f["booking_date"]:
            continue
        key = (f["booking_date"], f["amount"], f["counterparty"].lower(), f["purpose"].lower(), f["reference"])
        seen[key] = seen.get(key, 0) + 1
        ext = "fints:" + hashlib.sha1(f"{account.id}|{key}|{seen[key]}".encode()).hexdigest()[:24]
        rows.append((ext, f))
    existing = set(db.scalars(select(Transaction.external_id).where(Transaction.account_id == account.id, Transaction.external_id.in_([e for e, _ in rows]))).all()) if rows else set()
    for ext, f in rows:
        if ext in existing:
            continue
        kind = "interest" if "zins" in f["posting_text"].lower() and f["amount"] > 0 else "other"
        db.add(
            Transaction(
                account_id=account.id,
                booking_date=f["booking_date"],
                value_date=f["value_date"],
                amount=f["amount"],
                kind=kind,
                counterparty=f["counterparty"],
                purpose=f["purpose"],
                external_id=ext,
                raw={"posting_text": f["posting_text"], "reference": f["reference"], "iban": f["iban"]},
            )
        )
        created += 1
    return created


def apply_holdings(db: Session, account: Account, holdings: list[Any]) -> dict:
    """Store bank prices and compare quantities with our transactions.

    On the very first sync of an empty depot the holdings are booked as deliveries at the bank's
    acquisition price, so the depot is complete right away. Later differences are reported and can be
    corrected in the UI (they are usually trades that were not imported yet).
    """
    existing_trades = db.scalars(select(Trade).where(Trade.account_id == account.id)).all()
    positions = build_positions([TradeIn(t.date, t.type, t.instrument_id, t.quantity, t.amount, t.fees, t.taxes, t.id) for t in existing_trades])
    empty = not existing_trades
    differences = []
    booked = 0
    for h in holdings or []:
        isin = (getattr(h, "ISIN", None) or "").upper()
        name = getattr(h, "name", None) or isin
        pieces = _dec(getattr(h, "pieces", 0))
        price = getattr(h, "market_value", None)
        price_day = getattr(h, "valuation_date", None) or date.today()
        instrument = db.scalar(select(Instrument).where(Instrument.isin == isin)) if isin else None
        if instrument is None:
            instrument = Instrument(kind="stock", name=str(name)[:200], isin=isin or None, currency="EUR", price_source="manual", details={})
            db.add(instrument)
            db.flush()
        if price is not None and instrument.price_source == "manual":
            day = date(price_day.year, price_day.month, price_day.day)
            row = db.scalar(select(Price).where(Price.instrument_id == instrument.id, Price.date == day))
            if row is None:
                db.add(Price(instrument_id=instrument.id, date=day, close=_dec(price), source="bank"))
        if empty and pieces > 0:
            acq = getattr(h, "acquisitionprice", None)
            unit = _dec(acq) if acq else _dec(price)
            db.add(
                Trade(
                    account_id=account.id,
                    instrument_id=instrument.id,
                    date=date.today(),
                    type="deliver_in",
                    quantity=pieces,
                    price=unit,
                    amount=(pieces * unit).quantize(Decimal("0.01")),
                    note="Anfangsbestand laut Bank",
                    external_id=f"fints-initial:{isin or name}",
                )
            )
            booked += 1
            continue
        ours = positions.get(instrument.id)
        our_qty = ours.quantity if ours else Decimal("0")
        if our_qty != pieces:
            differences.append({"instrument_id": instrument.id, "name": instrument.name, "isin": isin, "bank": str(pieces), "ours": str(our_qty), "price": str(_dec(price)) if price is not None else None})
    # Positions we hold but the bank doesn't list anymore
    bank_isins = {(getattr(h, "ISIN", "") or "").upper() for h in holdings or []}
    for iid, pos in positions.items():
        inst = db.get(Instrument, iid)
        if pos.quantity > 0 and inst and inst.isin and inst.isin not in bank_isins and not empty:
            differences.append({"instrument_id": iid, "name": inst.name, "isin": inst.isin, "bank": "0", "ours": str(pos.quantity), "price": None})
    details = dict(account.details or {})
    details["fints_differences"] = differences
    account.details = details
    return {"positions": len(holdings or []), "initial_deliveries": booked, "differences": len(differences)}
