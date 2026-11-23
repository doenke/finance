"""Bank logins (FinTS): manage logins, discover and link accounts, run syncs with TAN dialogs."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import kinds
from ..auth.session import current_user
from ..db import get_db
from ..models import Account, AccountOwner, BankLogin, Instrument, Trade, User
from ..secrets import SecretsError, encrypt
from ..services import fints_sync
from ..services.valuation import latest_price

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])


class BankLoginIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    blz: str = Field(min_length=8, max_length=8, pattern=r"^\d{8}$")
    server_url: str = Field(min_length=8, max_length=255)
    username: str = Field(min_length=1, max_length=120)
    customer_id: str = Field(default="", max_length=120)
    store_pin: bool = False
    pin: str | None = Field(default=None, max_length=64)
    auto_sync: bool = False
    reset_tan: bool = False

    @field_validator("server_url")
    @classmethod
    def https_only(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith("https://"):
            raise ValueError("Die FinTS-Adresse muss mit https:// beginnen.")
        return v


class BankLoginOut(BaseModel):
    id: int
    name: str
    blz: str
    server_url: str
    username: str
    customer_id: str
    tan_mechanism_name: str
    tan_medium: str | None
    store_pin: bool
    has_pin: bool
    auto_sync: bool
    last_sync_at: datetime | None
    last_error: str
    needs_tan: bool
    account_ids: list[int]


class RunIn(BaseModel):
    pin: str | None = Field(default=None, max_length=64)
    account_ids: list[int] | None = None


class AnswerIn(BaseModel):
    value: str = Field(max_length=64)


class LinkItem(BaseModel):
    iban: str | None = None
    accountnumber: str | None = None
    subaccount: str | None = None
    blz: str | None = None
    account_id: int | None = None  # link to an existing account
    create_kind: str | None = None  # or create a new one
    create_name: str | None = None


class LinkIn(BaseModel):
    items: list[LinkItem]


def _out(db: Session, login: BankLogin) -> BankLoginOut:
    ids = db.scalars(select(Account.id).where(Account.bank_login_id == login.id)).all()
    return BankLoginOut(
        id=login.id,
        name=login.name,
        blz=login.blz,
        server_url=login.server_url,
        username=login.username,
        customer_id=login.customer_id,
        tan_mechanism_name=login.tan_mechanism_name,
        tan_medium=login.tan_medium,
        store_pin=login.store_pin,
        has_pin=bool(login.pin_encrypted),
        auto_sync=login.auto_sync,
        last_sync_at=login.last_sync_at,
        last_error=login.last_error,
        needs_tan=login.needs_tan,
        account_ids=list(ids),
    )


def _get(db: Session, login_id: int) -> BankLogin:
    login = db.get(BankLogin, login_id)
    if login is None:
        raise HTTPException(404, "Bankzugang nicht gefunden")
    return login


def _apply(request: Request, login: BankLogin, data: BankLoginIn, db: Session) -> None:
    changed_access = login.id is not None and (login.blz != data.blz or login.username != data.username or login.server_url != data.server_url)
    login.name = data.name.strip()
    login.blz = data.blz
    login.server_url = data.server_url
    login.username = data.username.strip()
    login.customer_id = data.customer_id.strip()
    login.store_pin = data.store_pin
    if changed_access or data.reset_tan:
        login.tan_mechanism, login.tan_mechanism_name, login.tan_medium, login.client_state = None, "", None, None
    if not data.store_pin:
        login.pin_encrypted = None
        login.auto_sync = False
    else:
        if data.pin:
            if login.id is None:
                db.add(login)
                db.flush()
            try:
                login.pin_encrypted = encrypt(request.app.state.settings.secrets_key, data.pin, f"bank_login:{login.id}")
            except SecretsError as exc:
                raise HTTPException(422, str(exc)) from None
        login.auto_sync = data.auto_sync and bool(login.pin_encrypted)


@router.get("/fints/status")
def fints_status(request: Request) -> dict[str, Any]:
    s = request.app.state.settings
    return {"product_id": bool(s.fints_product_id), "secrets_key": bool(s.secrets_key), "schedule": s.fints_sync_schedule}


@router.get("/banks", response_model=list[BankLoginOut])
def list_banks(db: Session = Depends(get_db)) -> list[BankLoginOut]:
    return [_out(db, b) for b in db.scalars(select(BankLogin).order_by(BankLogin.name)).all()]


@router.post("/banks", response_model=BankLoginOut, status_code=201)
def create_bank(data: BankLoginIn, request: Request, db: Session = Depends(get_db)) -> BankLoginOut:
    login = BankLogin()
    _apply(request, login, data, db)
    db.add(login)
    db.commit()
    return _out(db, login)


@router.put("/banks/{login_id}", response_model=BankLoginOut)
def update_bank(login_id: int, data: BankLoginIn, request: Request, db: Session = Depends(get_db)) -> BankLoginOut:
    login = _get(db, login_id)
    _apply(request, login, data, db)
    db.commit()
    return _out(db, login)


@router.delete("/banks/{login_id}", status_code=204)
def delete_bank(login_id: int, db: Session = Depends(get_db)) -> Response:
    db.delete(_get(db, login_id))
    db.commit()
    return Response(status_code=204)


def _start(request: Request, kind: str, login_id: int, data: RunIn, db: Session) -> dict[str, Any]:
    settings = request.app.state.settings
    if not settings.fints_product_id:
        raise HTTPException(422, "FINTS_PRODUCT_ID fehlt in der Konfiguration.")
    login = _get(db, login_id)
    if not data.pin and not login.pin_encrypted:
        raise HTTPException(422, "Bitte die PIN eingeben.")
    try:
        job = fints_sync.jobs.start(
            kind,
            login.id,
            data.pin or None,
            settings,
            request.app.state.sessionmaker,
            factory=request.app.state.fints_factory,
            account_ids=data.account_ids,
        )
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from None
    return job.public()


@router.post("/banks/{login_id}/discover")
def discover(login_id: int, data: RunIn, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _start(request, "discover", login_id, data, db)


@router.post("/banks/{login_id}/sync")
def sync(login_id: int, data: RunIn, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _start(request, "sync", login_id, data, db)


@router.get("/fints/jobs/{job_id}")
def job_status(job_id: str) -> dict[str, Any]:
    job = fints_sync.jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Abruf nicht gefunden")
    return job.public()


@router.post("/fints/jobs/{job_id}/answer")
def job_answer(job_id: str, data: AnswerIn) -> dict[str, Any]:
    job = fints_sync.jobs.get(job_id)
    if job is None or job.status not in ("need_tan", "need_choice"):
        raise HTTPException(409, "Der Abruf wartet gerade auf keine Eingabe.")
    job.answer(data.value)
    return {"ok": True}


@router.post("/fints/jobs/{job_id}/cancel")
def job_cancel(job_id: str) -> dict[str, Any]:
    job = fints_sync.jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Abruf nicht gefunden")
    job.cancel()
    return {"ok": True}


@router.post("/banks/{login_id}/link")
def link_accounts(login_id: int, data: LinkIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    login = _get(db, login_id)
    linked = []
    for item in data.items:
        fints_ref = {"iban": item.iban, "bic": None, "accountnumber": item.accountnumber, "subaccount": item.subaccount, "blz": item.blz or login.blz}
        if item.account_id:
            account = db.get(Account, item.account_id)
            if account is None:
                raise HTTPException(404, "Konto nicht gefunden")
        elif item.create_kind:
            if item.create_kind not in kinds.KINDS:
                raise HTTPException(422, "Unbekannte Kontoart")
            account = Account(
                name=(item.create_name or item.iban or item.accountnumber or "Konto")[:120],
                kind=item.create_kind,
                asset_class=kinds.KINDS[item.create_kind].asset_class,
                institution=login.name,
                iban=item.iban or "",
                details={},
            )
            if user.person:
                account.owners = [AccountOwner(person_id=user.person.id, share=Decimal("1"))]
            db.add(account)
            db.flush()
        else:
            continue
        account.bank_login_id = login.id
        details = dict(account.details or {})
        details["fints"] = fints_ref
        account.details = details
        linked.append(account.id)
    db.commit()
    return {"linked": linked}


@router.post("/accounts/{account_id}/unlink")
def unlink_account(account_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(404, "Konto nicht gefunden")
    account.bank_login_id = None
    details = dict(account.details or {})
    details.pop("fints", None)
    details.pop("fints_differences", None)
    account.details = details
    db.commit()
    return {"ok": True}


@router.post("/accounts/{account_id}/reconcile")
def reconcile(account_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Books the differences reported by the last FinTS sync as deliveries at the current price."""
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(404, "Konto nicht gefunden")
    diffs = (account.details or {}).get("fints_differences") or []
    created = 0
    for d in diffs:
        delta = Decimal(d["bank"]) - Decimal(d["ours"])
        if delta == 0:
            continue
        instrument = db.get(Instrument, d["instrument_id"])
        price = latest_price(db, instrument.id, date.today()) if instrument else None
        unit = Decimal(d["price"]) if d.get("price") else (price[0] if price else Decimal("0"))
        db.add(
            Trade(
                account_id=account.id,
                instrument_id=d["instrument_id"],
                date=date.today(),
                type="deliver_in" if delta > 0 else "deliver_out",
                quantity=abs(delta),
                price=unit,
                amount=(abs(delta) * unit).quantize(Decimal("0.01")),
                note="Abgleich mit Bankbestand",
            )
        )
        created += 1
    details = dict(account.details or {})
    details["fints_differences"] = []
    account.details = details
    db.commit()
    return {"created": created}
