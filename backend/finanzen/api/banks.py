"""Banks (shared) and personal bank logins (FinTS): manage them, discover and link accounts, run syncs with TAN dialogs."""

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
from ..models import Account, AccountOwner, Bank, BankLogin, Instrument, Trade, User
from ..secrets import SecretsError, encrypt
from ..services import fints_sync
from ..services.valuation import latest_price

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])


class BankIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    blz: str = Field(min_length=8, max_length=8, pattern=r"^\d{8}$")
    server_url: str = Field(min_length=8, max_length=255)

    @field_validator("server_url")
    @classmethod
    def https_only(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith("https://"):
            raise ValueError("Die FinTS-Adresse muss mit https:// beginnen.")
        return v


class BankLoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    customer_id: str = Field(default="", max_length=120)
    store_pin: bool = False
    pin: str | None = Field(default=None, max_length=64)
    auto_sync: bool = False
    reset_tan: bool = False


class BankLoginOut(BaseModel):
    id: int
    bank_id: int
    name: str
    blz: str
    server_url: str
    owner: str
    mine: bool
    username: str  # only filled for the owner
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


class BankOut(BaseModel):
    id: int
    name: str
    blz: str
    server_url: str
    logins: list[BankLoginOut]


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


def _out(db: Session, login: BankLogin, user: User) -> BankLoginOut:
    ids = db.scalars(select(Account.id).where(Account.bank_login_id == login.id)).all()
    mine = login.user_id == user.id
    return BankLoginOut(
        id=login.id,
        bank_id=login.bank_id,
        name=login.name,
        blz=login.blz,
        server_url=login.server_url,
        owner=login.user.name if login.user else "",
        mine=mine,
        username=login.username if mine else "",
        customer_id=login.customer_id if mine else "",
        tan_mechanism_name=login.tan_mechanism_name,
        tan_medium=login.tan_medium if mine else None,
        store_pin=login.store_pin,
        has_pin=bool(login.pin_encrypted),
        auto_sync=login.auto_sync,
        last_sync_at=login.last_sync_at,
        last_error=login.last_error,
        needs_tan=login.needs_tan,
        account_ids=list(ids),
    )


def _bank_out(db: Session, bank: Bank, user: User) -> BankOut:
    logins = sorted(bank.logins, key=lambda lg: (lg.user_id != user.id, lg.user.name if lg.user else "", lg.id))
    return BankOut(id=bank.id, name=bank.name, blz=bank.blz, server_url=bank.server_url, logins=[_out(db, lg, user) for lg in logins])


def _get_bank(db: Session, bank_id: int) -> Bank:
    bank = db.get(Bank, bank_id)
    if bank is None:
        raise HTTPException(404, "Bank nicht gefunden")
    return bank


def _get(db: Session, login_id: int, user: User | None = None, allow_admin: bool = False) -> BankLogin:
    """Loads a login; with `user`, only its owner (or an admin, if allowed) may use it."""
    login = db.get(BankLogin, login_id)
    if login is None:
        raise HTTPException(404, "Bankzugang nicht gefunden")
    if user is not None and login.user_id != user.id and not (allow_admin and user.is_admin):
        raise HTTPException(403, "Das ist der Bankzugang einer anderen Person.")
    return login


def _reset_tan(login: BankLogin) -> None:
    login.tan_mechanism, login.tan_mechanism_name, login.tan_medium, login.client_state = None, "", None, None


def _apply(request: Request, login: BankLogin, data: BankLoginIn, db: Session) -> None:
    changed_access = login.id is not None and login.username != data.username.strip()
    login.username = data.username.strip()
    login.customer_id = data.customer_id.strip()
    login.store_pin = data.store_pin
    if changed_access or data.reset_tan:
        _reset_tan(login)
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


@router.get("/banks", response_model=list[BankOut])
def list_banks(db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[BankOut]:
    return [_bank_out(db, b, user) for b in db.scalars(select(Bank).order_by(Bank.name)).unique().all()]


@router.post("/banks", response_model=BankOut, status_code=201)
def create_bank(data: BankIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> BankOut:
    bank = Bank(name=data.name.strip(), blz=data.blz, server_url=data.server_url)
    db.add(bank)
    db.commit()
    return _bank_out(db, bank, user)


@router.put("/banks/{bank_id}", response_model=BankOut)
def update_bank(bank_id: int, data: BankIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> BankOut:
    bank = _get_bank(db, bank_id)
    if bank.blz != data.blz or bank.server_url != data.server_url:
        for login in bank.logins:
            _reset_tan(login)
    bank.name, bank.blz, bank.server_url = data.name.strip(), data.blz, data.server_url
    db.commit()
    return _bank_out(db, bank, user)


@router.delete("/banks/{bank_id}", status_code=204)
def delete_bank(bank_id: int, db: Session = Depends(get_db)) -> Response:
    bank = _get_bank(db, bank_id)
    if bank.logins:
        raise HTTPException(409, "Für diese Bank gibt es noch Zugänge – erst die Zugänge löschen.")
    db.delete(bank)
    db.commit()
    return Response(status_code=204)


@router.get("/bank-logins", response_model=list[BankLoginOut])
def list_logins(db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[BankLoginOut]:
    return [_out(db, lg, user) for lg in db.scalars(select(BankLogin).order_by(BankLogin.id)).unique().all()]


@router.post("/banks/{bank_id}/logins", response_model=BankLoginOut, status_code=201)
def create_login(bank_id: int, data: BankLoginIn, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)) -> BankLoginOut:
    bank = _get_bank(db, bank_id)
    login = BankLogin(bank=bank, user_id=user.id)
    _apply(request, login, data, db)
    db.add(login)
    db.commit()
    db.refresh(login)
    return _out(db, login, user)


@router.put("/bank-logins/{login_id}", response_model=BankLoginOut)
def update_login(login_id: int, data: BankLoginIn, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)) -> BankLoginOut:
    login = _get(db, login_id, user)
    _apply(request, login, data, db)
    db.commit()
    return _out(db, login, user)


@router.delete("/bank-logins/{login_id}", status_code=204)
def delete_login(login_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> Response:
    login = _get(db, login_id, user, allow_admin=True)
    for account in db.scalars(select(Account).where(Account.bank_login_id == login.id)).all():
        account.bank_login_id = None
    db.delete(login)
    db.commit()
    return Response(status_code=204)


def _start(request: Request, kind: str, login_id: int, data: RunIn, db: Session, user: User) -> dict[str, Any]:
    settings = request.app.state.settings
    if not settings.fints_product_id:
        raise HTTPException(422, "FINTS_PRODUCT_ID fehlt in der Konfiguration.")
    login = _get(db, login_id, user)
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


@router.post("/bank-logins/{login_id}/discover")
def discover(login_id: int, data: RunIn, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    return _start(request, "discover", login_id, data, db, user)


@router.post("/bank-logins/{login_id}/sync")
def sync(login_id: int, data: RunIn, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    return _start(request, "sync", login_id, data, db, user)


def _job(job_id: str, db: Session, user: User):
    job = fints_sync.jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Abruf nicht gefunden")
    login = db.get(BankLogin, job.login_id)
    if login is None or login.user_id != user.id:
        raise HTTPException(404, "Abruf nicht gefunden")
    return job


@router.get("/fints/jobs/{job_id}")
def job_status(job_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    return _job(job_id, db, user).public()


@router.post("/fints/jobs/{job_id}/answer")
def job_answer(job_id: str, data: AnswerIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    job = _job(job_id, db, user)
    if job.status not in ("need_tan", "need_choice"):
        raise HTTPException(409, "Der Abruf wartet gerade auf keine Eingabe.")
    job.answer(data.value)
    return {"ok": True}


@router.post("/fints/jobs/{job_id}/cancel")
def job_cancel(job_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    _job(job_id, db, user).cancel()
    return {"ok": True}


@router.post("/bank-logins/{login_id}/link")
def link_accounts(login_id: int, data: LinkIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    login = _get(db, login_id, user)
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
