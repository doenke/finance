"""Accounts, balances, transactions, valuations, trades, instruments and prices."""

from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import kinds
from ..auth.session import current_user
from ..db import get_db
from ..models import Account, AccountOwner, BalanceSnapshot, Instrument, Person, Price, Trade, Transaction, User, Valuation
from ..services import valuation as val
from ..services.fx import FxConverter
from .prices import is_stale
from ..services.sync import sync_instrument_in_background

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])
ZERO = Decimal("0")


# --- Schemas -------------------------------------------------------------------------------------


class OwnerIn(BaseModel):
    person_id: int
    share: Decimal = Field(gt=0, le=1)


class AccountIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: str
    asset_class: str | None = None
    institution: str = Field(default="", max_length=120)
    iban: str = Field(default="", max_length=34)
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    opened_on: date | None = None
    closed: bool = False
    notes: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    settlement_account_id: int | None = None
    owners: list[OwnerIn] = Field(default_factory=list)

    @field_validator("kind")
    @classmethod
    def known_kind(cls, v: str) -> str:
        if v not in kinds.KINDS:
            raise ValueError("unbekannte Kontoart")
        return v

    @field_validator("asset_class")
    @classmethod
    def known_class(cls, v: str | None) -> str | None:
        if v is not None and v not in kinds.ASSET_CLASSES:
            raise ValueError("unbekannte Anlageklasse")
        return v


class OwnerOut(BaseModel):
    person_id: int
    share: Decimal


class AccountOut(BaseModel):
    id: int
    name: str
    kind: str
    kind_label: str
    mode: str
    asset_class: str
    liability: bool
    institution: str
    iban: str
    currency: str
    opened_on: date | None
    closed: bool
    notes: str
    details: dict[str, Any]
    settlement_account_id: int | None
    bank_login_id: int | None = None
    owners: list[OwnerOut]
    value: Decimal
    value_as_of: date | None
    missing_prices: int


class BalanceIn(BaseModel):
    date: date
    amount: Decimal


class BalanceOut(BalanceIn):
    id: int
    source: str


class TransactionIn(BaseModel):
    booking_date: date
    value_date: date | None = None
    amount: Decimal
    kind: str = "other"
    counterparty: str = Field(default="", max_length=255)
    purpose: str = ""
    transfer_account_id: int | None = None

    @field_validator("kind")
    @classmethod
    def known_kind(cls, v: str) -> str:
        if v not in kinds.TRANSACTION_KINDS:
            raise ValueError("unbekannte Buchungsart")
        return v


class TransactionOut(TransactionIn):
    id: int
    account_id: int


class ValuationIn(BaseModel):
    date: date
    value: Decimal
    note: str = ""


class ValuationOut(ValuationIn):
    id: int


class TradeIn(BaseModel):
    date: date
    type: str
    instrument_id: int | None = None
    quantity: Decimal = ZERO
    price: Decimal | None = None
    amount: Decimal = ZERO
    fees: Decimal = ZERO
    taxes: Decimal = ZERO
    note: str = ""

    @field_validator("type")
    @classmethod
    def known_type(cls, v: str) -> str:
        if v not in kinds.TRADE_TYPES:
            raise ValueError("unbekannte Transaktionsart")
        return v


class TradeOut(TradeIn):
    id: int


class InstrumentIn(BaseModel):
    kind: str
    name: str = Field(min_length=1, max_length=200)
    isin: str | None = Field(default=None, max_length=12)
    wkn: str | None = Field(default=None, max_length=6)
    symbol: str | None = Field(default=None, max_length=40)
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    unit: str = "piece"
    price_source: str = "manual"
    price_symbol: str | None = Field(default=None, max_length=40)
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("kind")
    @classmethod
    def known_kind(cls, v: str) -> str:
        if v not in kinds.INSTRUMENT_KINDS:
            raise ValueError("unbekannte Wertpapierart")
        return v

    @field_validator("isin", "wkn", "symbol", "price_symbol")
    @classmethod
    def blank_to_none(cls, v: str | None) -> str | None:
        v = (v or "").strip().upper()
        return v or None


class InstrumentOut(InstrumentIn):
    id: int
    last_price: Decimal | None = None
    last_price_date: date | None = None


class PriceIn(BaseModel):
    date: date
    close: Decimal = Field(gt=0)


class PriceOut(PriceIn):
    id: int
    source: str


class PositionOut(BaseModel):
    instrument: InstrumentOut
    quantity: Decimal
    cost: Decimal
    price: Decimal | None
    price_date: date | None
    value: Decimal
    gain: Decimal
    gain_pct: Decimal | None
    realized: Decimal
    income: Decimal
    stale: bool


class ScheduleRowOut(BaseModel):
    date: date
    payment: Decimal
    interest: Decimal
    principal: Decimal
    prepayment: Decimal
    balance: Decimal
    planned: bool


class ScheduleOut(BaseModel):
    rows: list[ScheduleRowOut]
    start_balance: Decimal
    start_date: date | None
    balance_today: Decimal
    balance_at_fixed_until: Decimal | None
    end_date: date | None
    interest_paid: Decimal
    interest_remaining: Decimal
    prepaid_this_year: Decimal
    prepayment_allowance: Decimal | None


# --- Helpers -------------------------------------------------------------------------------------


def get_account(db: Session, account_id: int) -> Account:
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(404, "Konto nicht gefunden")
    return account


def account_out(db: Session, account: Account, on: date) -> AccountOut:
    kind = kinds.KINDS.get(account.kind)
    value = val.account_value(db, account, on)
    return AccountOut(
        id=account.id,
        name=account.name,
        kind=account.kind,
        kind_label=kind.label if kind else account.kind,
        mode=kind.mode if kind else kinds.VALUATION,
        asset_class=account.asset_class,
        liability=kind.liability if kind else False,
        institution=account.institution,
        iban=account.iban,
        currency=account.currency,
        opened_on=account.opened_on,
        closed=account.closed,
        notes=account.notes,
        details=account.details or {},
        settlement_account_id=account.settlement_account_id,
        bank_login_id=account.bank_login_id,
        owners=[OwnerOut(person_id=o.person_id, share=o.share) for o in account.owners],
        value=value.value,
        value_as_of=value.as_of,
        missing_prices=value.missing_prices,
    )


def apply_owners(db: Session, account: Account, owners: list[OwnerIn], user: User) -> None:
    if not owners:
        if account.owners:
            return
        if user.person is None:
            raise HTTPException(422, "Bitte mindestens eine Person als Eigentümer angeben.")
        owners = [OwnerIn(person_id=user.person.id, share=Decimal("1"))]
    total = sum((o.share for o in owners), ZERO)
    if abs(total - 1) > Decimal("0.0001"):
        raise HTTPException(422, "Die Anteile müssen zusammen 100 % ergeben.")
    ids = [o.person_id for o in owners]
    if len(set(ids)) != len(ids) or len(db.scalars(select(Person.id).where(Person.id.in_(ids))).all()) != len(ids):
        raise HTTPException(422, "Unbekannte oder doppelte Person.")
    account.owners = [AccountOwner(person_id=o.person_id, share=o.share) for o in owners]


def instrument_out(db: Session, instrument: Instrument) -> InstrumentOut:
    price = db.execute(
        select(Price.close, Price.date).where(Price.instrument_id == instrument.id).order_by(Price.date.desc()).limit(1)
    ).first()
    return InstrumentOut(
        id=instrument.id,
        kind=instrument.kind,
        name=instrument.name,
        isin=instrument.isin,
        wkn=instrument.wkn,
        symbol=instrument.symbol,
        currency=instrument.currency,
        unit=instrument.unit,
        price_source=instrument.price_source,
        price_symbol=instrument.price_symbol,
        details=instrument.details or {},
        last_price=price[0] if price else None,
        last_price_date=price[1] if price else None,
    )


def require_mode(account: Account, *modes: str) -> None:
    kind = kinds.KINDS.get(account.kind)
    if kind is None or kind.mode not in modes:
        raise HTTPException(422, "Das passt nicht zu dieser Kontoart.")


# --- Meta ----------------------------------------------------------------------------------------


@router.get("/meta")
def meta() -> dict[str, Any]:
    return {
        "kinds": [{"key": k.key, "label": k.label, "mode": k.mode, "asset_class": k.asset_class, "liability": k.liability} for k in kinds.KINDS.values()],
        "asset_classes": [{"key": k, "label": v} for k, v in kinds.ASSET_CLASSES.items()],
        "transaction_kinds": [{"key": k, "label": v} for k, v in kinds.TRANSACTION_KINDS.items()],
        "trade_types": [{"key": k, "label": v} for k, v in kinds.TRADE_TYPES.items()],
        "instrument_kinds": [{"key": k, "label": v} for k, v in kinds.INSTRUMENT_KINDS.items()],
        "units": [{"key": k, "label": v} for k, v in kinds.UNITS.items()],
    }


# --- Accounts ------------------------------------------------------------------------------------


@router.get("/accounts", response_model=list[AccountOut])
def list_accounts(on: date | None = None, db: Session = Depends(get_db)) -> list[AccountOut]:
    on = on or date.today()
    accounts = db.scalars(select(Account).order_by(Account.closed, Account.sort_order, Account.name)).all()
    return [account_out(db, a, on) for a in accounts]


@router.post("/accounts", response_model=AccountOut, status_code=201)
def create_account(data: AccountIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> AccountOut:
    account = Account(
        name=data.name.strip(),
        kind=data.kind,
        asset_class=data.asset_class or kinds.KINDS[data.kind].asset_class,
        institution=data.institution.strip(),
        iban=data.iban.replace(" ", "").upper(),
        currency=data.currency.upper(),
        opened_on=data.opened_on,
        closed=data.closed,
        notes=data.notes,
        details=data.details,
        settlement_account_id=data.settlement_account_id,
    )
    apply_owners(db, account, data.owners, user)
    db.add(account)
    db.commit()
    return account_out(db, account, date.today())


@router.get("/accounts/{account_id}", response_model=AccountOut)
def get_account_detail(account_id: int, on: date | None = None, db: Session = Depends(get_db)) -> AccountOut:
    return account_out(db, get_account(db, account_id), on or date.today())


@router.put("/accounts/{account_id}", response_model=AccountOut)
def update_account(account_id: int, data: AccountIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> AccountOut:
    account = get_account(db, account_id)
    if data.kind != account.kind and kinds.KINDS[data.kind].mode != kinds.KINDS[account.kind].mode:
        raise HTTPException(422, "Die Kontoart lässt sich nur innerhalb derselben Gruppe ändern.")
    if data.settlement_account_id == account.id:
        raise HTTPException(422, "Ein Konto kann nicht sein eigenes Verrechnungskonto sein.")
    account.name = data.name.strip()
    account.kind = data.kind
    account.asset_class = data.asset_class or kinds.KINDS[data.kind].asset_class
    account.institution = data.institution.strip()
    account.iban = data.iban.replace(" ", "").upper()
    account.currency = data.currency.upper()
    account.opened_on = data.opened_on
    account.closed = data.closed
    account.notes = data.notes
    account.details = data.details
    account.settlement_account_id = data.settlement_account_id
    apply_owners(db, account, data.owners, user)
    db.commit()
    return account_out(db, account, date.today())


@router.delete("/accounts/{account_id}", status_code=204)
def delete_account(account_id: int, db: Session = Depends(get_db)) -> Response:
    db.delete(get_account(db, account_id))
    db.commit()
    return Response(status_code=204)


# --- Balances ------------------------------------------------------------------------------------


@router.get("/accounts/{account_id}/balances", response_model=list[BalanceOut])
def list_balances(account_id: int, db: Session = Depends(get_db)) -> list[BalanceOut]:
    get_account(db, account_id)
    rows = db.scalars(select(BalanceSnapshot).where(BalanceSnapshot.account_id == account_id).order_by(BalanceSnapshot.date.desc())).all()
    return [BalanceOut(id=r.id, date=r.date, amount=r.amount, source=r.source) for r in rows]


@router.post("/accounts/{account_id}/balances", response_model=BalanceOut, status_code=201)
def upsert_balance(account_id: int, data: BalanceIn, db: Session = Depends(get_db)) -> BalanceOut:
    account = get_account(db, account_id)
    require_mode(account, kinds.CASH, kinds.LOAN)
    row = db.scalar(select(BalanceSnapshot).where(BalanceSnapshot.account_id == account_id, BalanceSnapshot.date == data.date))
    if row is None:
        row = BalanceSnapshot(account_id=account_id, date=data.date)
        db.add(row)
    row.amount = data.amount
    row.source = "manual"
    db.commit()
    return BalanceOut(id=row.id, date=row.date, amount=row.amount, source=row.source)


@router.delete("/accounts/{account_id}/balances/{balance_id}", status_code=204)
def delete_balance(account_id: int, balance_id: int, db: Session = Depends(get_db)) -> Response:
    row = db.get(BalanceSnapshot, balance_id)
    if row is None or row.account_id != account_id:
        raise HTTPException(404, "Saldo nicht gefunden")
    db.delete(row)
    db.commit()
    return Response(status_code=204)


# --- Transactions --------------------------------------------------------------------------------


def transaction_out(t: Transaction) -> TransactionOut:
    return TransactionOut(
        id=t.id,
        account_id=t.account_id,
        booking_date=t.booking_date,
        value_date=t.value_date,
        amount=t.amount,
        kind=t.kind,
        counterparty=t.counterparty,
        purpose=t.purpose,
        transfer_account_id=t.transfer_account_id,
    )


@router.get("/accounts/{account_id}/transactions", response_model=list[TransactionOut])
def list_transactions(
    account_id: int,
    q: str = "",
    limit: int = Query(default=100, le=1000),
    offset: int = 0,
    db: Session = Depends(get_db),
) -> list[TransactionOut]:
    get_account(db, account_id)
    stmt = select(Transaction).where(Transaction.account_id == account_id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Transaction.counterparty.ilike(like), Transaction.purpose.ilike(like)))
    stmt = stmt.order_by(Transaction.booking_date.desc(), Transaction.id.desc()).limit(limit).offset(offset)
    return [transaction_out(t) for t in db.scalars(stmt).all()]


@router.post("/accounts/{account_id}/transactions", response_model=TransactionOut, status_code=201)
def create_transaction(account_id: int, data: TransactionIn, db: Session = Depends(get_db)) -> TransactionOut:
    get_account(db, account_id)
    t = Transaction(account_id=account_id, **data.model_dump())
    db.add(t)
    db.commit()
    return transaction_out(t)


@router.put("/accounts/{account_id}/transactions/{tx_id}", response_model=TransactionOut)
def update_transaction(account_id: int, tx_id: int, data: TransactionIn, db: Session = Depends(get_db)) -> TransactionOut:
    t = db.get(Transaction, tx_id)
    if t is None or t.account_id != account_id:
        raise HTTPException(404, "Buchung nicht gefunden")
    for k, v in data.model_dump().items():
        setattr(t, k, v)
    db.commit()
    return transaction_out(t)


@router.delete("/accounts/{account_id}/transactions/{tx_id}", status_code=204)
def delete_transaction(account_id: int, tx_id: int, db: Session = Depends(get_db)) -> Response:
    t = db.get(Transaction, tx_id)
    if t is None or t.account_id != account_id:
        raise HTTPException(404, "Buchung nicht gefunden")
    db.delete(t)
    db.commit()
    return Response(status_code=204)


# --- Valuations ----------------------------------------------------------------------------------


@router.get("/accounts/{account_id}/valuations", response_model=list[ValuationOut])
def list_valuations(account_id: int, db: Session = Depends(get_db)) -> list[ValuationOut]:
    get_account(db, account_id)
    rows = db.scalars(select(Valuation).where(Valuation.account_id == account_id).order_by(Valuation.date.desc())).all()
    return [ValuationOut(id=r.id, date=r.date, value=r.value, note=r.note) for r in rows]


@router.post("/accounts/{account_id}/valuations", response_model=ValuationOut, status_code=201)
def upsert_valuation(account_id: int, data: ValuationIn, db: Session = Depends(get_db)) -> ValuationOut:
    account = get_account(db, account_id)
    require_mode(account, kinds.VALUATION)
    row = db.scalar(select(Valuation).where(Valuation.account_id == account_id, Valuation.date == data.date))
    if row is None:
        row = Valuation(account_id=account_id, date=data.date)
        db.add(row)
    row.value = data.value
    row.note = data.note
    db.commit()
    return ValuationOut(id=row.id, date=row.date, value=row.value, note=row.note)


@router.delete("/accounts/{account_id}/valuations/{valuation_id}", status_code=204)
def delete_valuation(account_id: int, valuation_id: int, db: Session = Depends(get_db)) -> Response:
    row = db.get(Valuation, valuation_id)
    if row is None or row.account_id != account_id:
        raise HTTPException(404, "Bewertung nicht gefunden")
    db.delete(row)
    db.commit()
    return Response(status_code=204)


# --- Trades and positions ------------------------------------------------------------------------


def validate_trade(db: Session, data: TradeIn) -> None:
    if data.type in kinds.INSTRUMENT_TYPES and data.instrument_id is None:
        raise HTTPException(422, "Bitte ein Wertpapier auswählen.")
    if data.instrument_id is not None and db.get(Instrument, data.instrument_id) is None:
        raise HTTPException(422, "Unbekanntes Wertpapier.")
    if data.type in kinds.QUANTITY_TYPES and data.quantity <= 0:
        raise HTTPException(422, "Die Stückzahl muss größer als 0 sein.")


def trade_out(t: Trade) -> TradeOut:
    return TradeOut(
        id=t.id,
        date=t.date,
        type=t.type,
        instrument_id=t.instrument_id,
        quantity=t.quantity,
        price=t.price,
        amount=t.amount,
        fees=t.fees,
        taxes=t.taxes,
        note=t.note,
    )


def fill_amount(data: TradeIn) -> dict[str, Any]:
    values = data.model_dump()
    if data.type in ("buy", "sell", "deliver_in", "deliver_out") and not data.amount and data.price:
        values["amount"] = (data.quantity * data.price).quantize(Decimal("0.01"))
    if data.type in ("buy", "sell", "deliver_in", "deliver_out") and not data.price and data.amount and data.quantity:
        values["price"] = data.amount / data.quantity
    return values


@router.get("/accounts/{account_id}/trades", response_model=list[TradeOut])
def list_trades(account_id: int, db: Session = Depends(get_db)) -> list[TradeOut]:
    get_account(db, account_id)
    rows = db.scalars(select(Trade).where(Trade.account_id == account_id).order_by(Trade.date.desc(), Trade.id.desc())).all()
    return [trade_out(t) for t in rows]


@router.post("/accounts/{account_id}/trades", response_model=TradeOut, status_code=201)
def create_trade(account_id: int, data: TradeIn, db: Session = Depends(get_db)) -> TradeOut:
    require_mode(get_account(db, account_id), kinds.HOLDINGS)
    validate_trade(db, data)
    t = Trade(account_id=account_id, **fill_amount(data))
    db.add(t)
    db.commit()
    return trade_out(t)


@router.put("/accounts/{account_id}/trades/{trade_id}", response_model=TradeOut)
def update_trade(account_id: int, trade_id: int, data: TradeIn, db: Session = Depends(get_db)) -> TradeOut:
    t = db.get(Trade, trade_id)
    if t is None or t.account_id != account_id:
        raise HTTPException(404, "Transaktion nicht gefunden")
    validate_trade(db, data)
    for k, v in fill_amount(data).items():
        setattr(t, k, v)
    db.commit()
    return trade_out(t)


@router.delete("/accounts/{account_id}/trades/{trade_id}", status_code=204)
def delete_trade(account_id: int, trade_id: int, db: Session = Depends(get_db)) -> Response:
    t = db.get(Trade, trade_id)
    if t is None or t.account_id != account_id:
        raise HTTPException(404, "Transaktion nicht gefunden")
    db.delete(t)
    db.commit()
    return Response(status_code=204)


@router.get("/accounts/{account_id}/positions", response_model=list[PositionOut])
def list_positions(request: Request, account_id: int, on: date | None = None, closed: bool = False, db: Session = Depends(get_db)) -> list[PositionOut]:
    account = get_account(db, account_id)
    require_mode(account, kinds.HOLDINGS)
    on = on or date.today()
    fx = FxConverter(db)
    _, positions = val.holdings_value(db, account_id, on, fx)
    result: list[PositionOut] = []
    for pos in positions.values():
        if pos.quantity == ZERO and not closed:
            continue
        instrument = db.get(Instrument, pos.instrument_id)
        priced = val.position_value(db, instrument, pos.quantity, on, fx)
        value = priced[0] if priced else pos.cost.quantize(Decimal("0.01"))
        gain = value - pos.cost
        result.append(
            PositionOut(
                instrument=instrument_out(db, instrument),
                quantity=pos.quantity,
                cost=pos.cost.quantize(Decimal("0.01")),
                price=priced[1] if priced else None,
                price_date=priced[2] if priced else None,
                value=value,
                gain=gain.quantize(Decimal("0.01")),
                gain_pct=(gain / pos.cost * 100).quantize(Decimal("0.01")) if pos.cost else None,
                realized=pos.realized.quantize(Decimal("0.01")),
                income=pos.income.quantize(Decimal("0.01")),
                stale=instrument.price_source != "manual" and is_stale(priced[2] if priced else None, request.app.state.settings.price_stale_days),
            )
        )
    result.sort(key=lambda p: p.value, reverse=True)
    return result


# --- Loans ---------------------------------------------------------------------------------------


@router.get("/accounts/{account_id}/schedule", response_model=ScheduleOut)
def loan_schedule(account_id: int, planned: bool = True, db: Session = Depends(get_db)) -> ScheduleOut:
    account = get_account(db, account_id)
    require_mode(account, kinds.LOAN)
    terms = val.loan_terms(account)
    if terms is None:
        raise HTTPException(422, "Für den Tilgungsplan fehlen Darlehensbetrag, Auszahlungsdatum oder erste Rate.")
    rows, start, start_date = val.loan_schedule(db, account, include_planned=planned)
    today = date.today()
    balance_today = val.balance_at(rows, start, today) if start_date and start_date <= today else start
    at_fixed = val.balance_at(rows, start, terms.fixed_until) if terms.fixed_until else None
    allowance_pct = account.details.get("prepayment_allowance_pct") if account.details else None
    allowance = (terms.principal * Decimal(str(allowance_pct)) / 100).quantize(Decimal("0.01")) if allowance_pct else None
    prepaid = sum(
        (abs(t.amount) for t in db.scalars(select(Transaction).where(Transaction.account_id == account_id, Transaction.kind == "prepayment")).all() if t.booking_date.year == today.year),
        ZERO,
    )
    return ScheduleOut(
        rows=[ScheduleRowOut(**r.__dict__) for r in rows],
        start_balance=start,
        start_date=start_date,
        balance_today=balance_today,
        balance_at_fixed_until=at_fixed,
        end_date=rows[-1].date if rows and rows[-1].balance <= 0 else None,
        interest_paid=sum((r.interest for r in rows if r.date <= today), ZERO),
        interest_remaining=sum((r.interest for r in rows if r.date > today), ZERO),
        prepaid_this_year=prepaid,
        prepayment_allowance=allowance,
    )


# --- Instruments and prices ----------------------------------------------------------------------


@router.get("/instruments", response_model=list[InstrumentOut])
def list_instruments(q: str = "", db: Session = Depends(get_db)) -> list[InstrumentOut]:
    stmt = select(Instrument).order_by(Instrument.name)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Instrument.name.ilike(like), Instrument.isin.ilike(like), Instrument.wkn.ilike(like), Instrument.symbol.ilike(like)))
    return [instrument_out(db, i) for i in db.scalars(stmt.limit(200)).all()]


@router.post("/instruments", response_model=InstrumentOut, status_code=201)
def create_instrument(data: InstrumentIn, request: Request, db: Session = Depends(get_db)) -> InstrumentOut:
    instrument = Instrument(**data.model_dump())
    db.add(instrument)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Ein Wertpapier mit dieser ISIN gibt es schon.") from None
    if instrument.price_source != "manual" and instrument.price_symbol and request.app.state.settings.scheduler:
        sync_instrument_in_background(request.app.state.sessionmaker, instrument.id)
    return instrument_out(db, instrument)


@router.put("/instruments/{instrument_id}", response_model=InstrumentOut)
def update_instrument(instrument_id: int, data: InstrumentIn, db: Session = Depends(get_db)) -> InstrumentOut:
    instrument = db.get(Instrument, instrument_id)
    if instrument is None:
        raise HTTPException(404, "Wertpapier nicht gefunden")
    for k, v in data.model_dump().items():
        setattr(instrument, k, v)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Ein Wertpapier mit dieser ISIN gibt es schon.") from None
    return instrument_out(db, instrument)


@router.get("/instruments/{instrument_id}/prices", response_model=list[PriceOut])
def list_prices(instrument_id: int, limit: int = Query(default=100, le=5000), db: Session = Depends(get_db)) -> list[PriceOut]:
    rows = db.scalars(select(Price).where(Price.instrument_id == instrument_id).order_by(Price.date.desc()).limit(limit)).all()
    return [PriceOut(id=r.id, date=r.date, close=r.close, source=r.source) for r in rows]


@router.post("/instruments/{instrument_id}/prices", response_model=PriceOut, status_code=201)
def upsert_price(instrument_id: int, data: PriceIn, db: Session = Depends(get_db)) -> PriceOut:
    if db.get(Instrument, instrument_id) is None:
        raise HTTPException(404, "Wertpapier nicht gefunden")
    row = db.scalar(select(Price).where(Price.instrument_id == instrument_id, Price.date == data.date))
    if row is None:
        row = Price(instrument_id=instrument_id, date=data.date)
        db.add(row)
    row.close = data.close
    row.source = "manual"
    db.commit()
    return PriceOut(id=row.id, date=row.date, close=row.close, source=row.source)


@router.delete("/instruments/{instrument_id}/prices/{price_id}", status_code=204)
def delete_price(instrument_id: int, price_id: int, db: Session = Depends(get_db)) -> Response:
    row = db.get(Price, price_id)
    if row is None or row.instrument_id != instrument_id:
        raise HTTPException(404, "Kurs nicht gefunden")
    db.delete(row)
    db.commit()
    return Response(status_code=204)
