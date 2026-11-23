"""Value of an account at a given day."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import kinds
from ..models import Account, BalanceSnapshot, Instrument, Price, Trade, Transaction, Valuation
from .deposit import deposit_value
from .fx import FxConverter
from .holdings import Position, TradeIn, build_positions
from .loan import LoanTerms, Prepayment, balance_at, expand_planned, schedule

ZERO = Decimal("0")


@dataclass
class AccountValue:
    value: Decimal
    as_of: date | None  # date of the underlying data (last balance, price, valuation)
    missing_prices: int = 0


def _dec(value, default: str = "0") -> Decimal:
    try:
        return Decimal(str(value)) if value not in (None, "") else Decimal(default)
    except ArithmeticError:
        return Decimal(default)


def _date(value) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def cash_balance(db: Session, account_id: int, on: date) -> AccountValue:
    snap = db.scalar(
        select(BalanceSnapshot)
        .where(BalanceSnapshot.account_id == account_id, BalanceSnapshot.date <= on)
        .order_by(BalanceSnapshot.date.desc())
        .limit(1)
    )
    q = select(func.coalesce(func.sum(Transaction.amount), 0), func.max(Transaction.booking_date)).where(
        Transaction.account_id == account_id, Transaction.booking_date <= on
    )
    if snap:
        q = q.where(Transaction.booking_date > snap.date)
    total, last = db.execute(q).one()
    base = snap.amount if snap else ZERO
    as_of = max(d for d in [snap.date if snap else None, last] if d) if (snap or last) else None
    return AccountValue(base + Decimal(total), as_of)


def trades_for(db: Session, account_id: int) -> list[TradeIn]:
    rows = db.scalars(select(Trade).where(Trade.account_id == account_id)).all()
    return [TradeIn(t.date, t.type, t.instrument_id, t.quantity, t.amount, t.fees, t.taxes, t.id) for t in rows]


def latest_price(db: Session, instrument_id: int, on: date) -> tuple[Decimal, date] | None:
    row = db.execute(
        select(Price.close, Price.date)
        .where(Price.instrument_id == instrument_id, Price.date <= on)
        .order_by(Price.date.desc())
        .limit(1)
    ).first()
    if row:
        return row[0], row[1]
    # Fallback: last trade price
    trade = db.execute(
        select(Trade.price, Trade.date)
        .where(Trade.instrument_id == instrument_id, Trade.price.is_not(None), Trade.date <= on)
        .order_by(Trade.date.desc())
        .limit(1)
    ).first()
    return (trade[0], trade[1]) if trade else None


def unit_factor(instrument: Instrument | None) -> Decimal:
    """Converts held quantity to price units (e.g. grams held, price per troy ounce)."""
    if instrument is None:
        return Decimal("1")
    details = instrument.details or {}
    fineness = _dec(details.get("fineness"), "1")
    price_unit = details.get("price_unit", instrument.unit)
    factor = fineness
    if instrument.unit == "g" and price_unit == "oz":
        factor = factor / Decimal("31.1034768")
    elif instrument.unit == "oz" and price_unit == "g":
        factor = factor * Decimal("31.1034768")
    return factor


def position_value(db: Session, instrument: Instrument | None, quantity: Decimal, on: date, fx: FxConverter) -> tuple[Decimal, Decimal, date] | None:
    """(value in EUR, price in instrument currency, price date) or None without a usable price."""
    if instrument is None:
        return None
    price = latest_price(db, instrument.id, on)
    if price is None:
        return None
    factor = fx.to_eur_factor(instrument.currency, on)
    if factor is None:
        return None
    value = (quantity * unit_factor(instrument) * price[0] * factor).quantize(Decimal("0.01"))
    return value, price[0], price[1]


def holdings_value(db: Session, account_id: int, on: date, fx: FxConverter | None = None) -> tuple[AccountValue, dict[int, Position]]:
    fx = fx or FxConverter(db)
    positions = build_positions(trades_for(db, account_id), until=on)
    total = ZERO
    missing = 0
    as_of: date | None = None
    for pos in positions.values():
        if pos.quantity == ZERO:
            continue
        result = position_value(db, db.get(Instrument, pos.instrument_id), pos.quantity, on, fx)
        if result is None:
            missing += 1
            total += pos.cost
            continue
        total += result[0]
        as_of = max(as_of, result[2]) if as_of else result[2]
    return AccountValue(total.quantize(Decimal("0.01")), as_of, missing), positions


def valuation_value(db: Session, account_id: int, on: date) -> AccountValue:
    row = db.scalar(
        select(Valuation).where(Valuation.account_id == account_id, Valuation.date <= on).order_by(Valuation.date.desc()).limit(1)
    )
    return AccountValue(row.value, row.date) if row else AccountValue(ZERO, None)


def loan_terms(account: Account) -> LoanTerms | None:
    d = account.details or {}
    principal = _dec(d.get("principal"))
    disbursed = _date(d.get("disbursed_on"))
    first = _date(d.get("first_payment"))
    if principal <= ZERO or not disbursed or not first:
        return None
    return LoanTerms(
        principal=principal,
        disbursed_on=disbursed,
        rate=_dec(d.get("rate")),
        first_payment=first,
        mode=d.get("mode") or "annuity",
        installment=_dec(d.get("installment")) or None,
        initial_repayment=_dec(d.get("initial_repayment")) or None,
        frequency=int(d.get("frequency") or 12),
        grace_until=_date(d.get("grace_until")),
        fixed_until=_date(d.get("fixed_until")),
        followup_rate=_dec(d.get("followup_rate")) if d.get("followup_rate") not in (None, "") else None,
    )


def loan_prepayments(db: Session, account: Account, include_planned: bool, until: date) -> list[Prepayment]:
    actual = db.scalars(select(Transaction).where(Transaction.account_id == account.id, Transaction.kind == "prepayment")).all()
    result = [Prepayment(t.booking_date, abs(t.amount)) for t in actual]
    if include_planned:
        result += expand_planned((account.details or {}).get("planned_prepayments") or [], until)
    return result


def loan_schedule(db: Session, account: Account, include_planned: bool = True):
    """Schedule anchored on the latest bank balance (if any). Returns (rows, start_balance, start_date)."""
    terms = loan_terms(account)
    if terms is None:
        return [], ZERO, None
    snap = db.scalar(
        select(BalanceSnapshot).where(BalanceSnapshot.account_id == account.id).order_by(BalanceSnapshot.date.desc()).limit(1)
    )
    horizon = date(terms.disbursed_on.year + 80, 12, 31)
    prepayments = loan_prepayments(db, account, include_planned, horizon)
    if snap:
        start, start_date = abs(snap.amount), snap.date
        rows = schedule(terms, prepayments, start_balance=start, start_date=start_date)
    else:
        start, start_date = terms.principal, terms.disbursed_on
        rows = schedule(terms, prepayments)
    return rows, start, start_date


def loan_value(db: Session, account: Account, on: date) -> AccountValue:
    snap = db.scalar(
        select(BalanceSnapshot)
        .where(BalanceSnapshot.account_id == account.id, BalanceSnapshot.date <= on)
        .order_by(BalanceSnapshot.date.desc())
        .limit(1)
    )
    terms = loan_terms(account)
    if terms is None:
        return AccountValue(-abs(snap.amount), snap.date) if snap else AccountValue(ZERO, None)
    if on < terms.disbursed_on:
        return AccountValue(ZERO, None)
    prepayments = loan_prepayments(db, account, include_planned=False, until=on)
    if snap:
        rows = schedule(terms, prepayments, start_balance=abs(snap.amount), start_date=snap.date)
        bal = balance_at(rows, abs(snap.amount), on)
    else:
        rows = schedule(terms, prepayments)
        bal = balance_at(rows, terms.principal, on)
    return AccountValue(-bal, on)


def deposit_account_value(account: Account, on: date) -> AccountValue:
    d = account.details or {}
    start = _date(d.get("start")) or account.opened_on
    if not start:
        return AccountValue(ZERO, None)
    value = deposit_value(_dec(d.get("amount")), _dec(d.get("rate")), start, _date(d.get("end")), on)
    return AccountValue(value, on)


def account_value(db: Session, account: Account, on: date) -> AccountValue:
    mode = kinds.KINDS[account.kind].mode if account.kind in kinds.KINDS else kinds.VALUATION
    if mode == kinds.CASH:
        return cash_balance(db, account.id, on)
    if mode == kinds.HOLDINGS:
        return holdings_value(db, account.id, on)[0]
    if mode == kinds.DEPOSIT:
        return deposit_account_value(account, on)
    if mode == kinds.LOAN:
        return loan_value(db, account, on)
    return valuation_value(db, account.id, on)
