"""Amortization schedule for loans (annuity or fixed repayment), with prepayments."""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal("0")
CENT = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def add_months(d: date, months: int, day: int | None = None) -> date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    target_day = day or d.day
    for dd in (target_day, 30, 29, 28):
        try:
            return date(year, month, min(dd, 31))
        except ValueError:
            continue
    raise ValueError("invalid date")


def days360(start: date, end: date) -> int:
    """German 30/360 day count."""
    d1 = min(start.day, 30)
    d2 = min(end.day, 30)
    return (end.year - start.year) * 360 + (end.month - start.month) * 30 + (d2 - d1)


@dataclass
class LoanTerms:
    principal: Decimal
    disbursed_on: date
    rate: Decimal  # nominal interest p.a. in percent
    first_payment: date
    mode: str = "annuity"  # annuity | fixed_repayment
    installment: Decimal | None = None  # payment per period (annuity) or principal part (fixed_repayment)
    initial_repayment: Decimal | None = None  # percent p.a., used if installment is missing
    frequency: int = 12  # payments per year (12 or 4)
    grace_until: date | None = None  # interest only up to and including this date
    fixed_until: date | None = None
    followup_rate: Decimal | None = None  # assumed rate after fixed_until
    installment_changes: tuple[tuple[date, Decimal], ...] = ()  # contract changes of the payment (past or future)


@dataclass
class Prepayment:
    date: date
    amount: Decimal
    planned: bool = False
    fee: bool = False  # a charge added to the debt (e.g. for changing the installment) instead of a repayment


@dataclass
class Row:
    date: date
    payment: Decimal
    interest: Decimal
    principal: Decimal
    prepayment: Decimal
    balance: Decimal
    planned: bool = False
    fee: Decimal = ZERO


def periodic_payment(terms: LoanTerms) -> Decimal:
    if terms.installment:
        return terms.installment
    initial = terms.initial_repayment or Decimal("2")
    if terms.mode == "fixed_repayment":
        return money(terms.principal * initial / 100 / terms.frequency)
    return money(terms.principal * (terms.rate + initial) / 100 / terms.frequency)


def schedule(
    terms: LoanTerms,
    prepayments: list[Prepayment] | None = None,
    start_balance: Decimal | None = None,
    start_date: date | None = None,
    max_years: int = 80,
    installment_changes: list[tuple[date, Decimal]] | None = None,
) -> list[Row]:
    """Rows in date order. Optionally starts from a known balance at a date (bank statement).

    `installment_changes`: from each date on, the payment per period (or the principal part for
    fixed repayment loans) becomes the given amount.
    """
    # fees first on the same day: they count before that day's payment
    prepayments = sorted(prepayments or [], key=lambda p: (p.date, not p.fee))
    changes = sorted(list(terms.installment_changes) + list(installment_changes or []), key=lambda c: c[0])
    step = 12 // terms.frequency
    base_payment = periodic_payment(terms)
    balance = start_balance if start_balance is not None else terms.principal
    last_date = start_date or terms.disbursed_on
    pay_date = terms.first_payment
    while pay_date <= last_date:
        pay_date = add_months(pay_date, step, terms.first_payment.day)

    rows: list[Row] = []
    pending = [p for p in prepayments if p.date > last_date]
    limit = add_months(last_date, 12 * max_years)
    first_period = True  # pro rata interest from disbursement or the anchor date
    while balance > ZERO and pay_date <= limit:
        # Prepayments before this payment reduce the balance immediately; fees up to and including
        # the payment date increase it (and are paid off with the installments).
        while pending and (pending[0].date < pay_date or (pending[0].fee and pending[0].date <= pay_date)) and balance > ZERO:
            p = pending.pop(0)
            if p.fee:
                balance += p.amount
                rows.append(Row(p.date, ZERO, ZERO, ZERO, ZERO, balance, p.planned, fee=p.amount))
                continue
            amount = min(p.amount, balance)
            balance -= amount
            rows.append(Row(p.date, ZERO, ZERO, ZERO, amount, balance, p.planned))
        if balance <= ZERO:
            break
        rate = terms.rate
        if terms.fixed_until and terms.followup_rate is not None and pay_date > terms.fixed_until:
            rate = terms.followup_rate
        payment = next((amount for day, amount in reversed(changes) if day <= pay_date), base_payment)
        if first_period:
            interest = money(balance * rate / 100 * days360(last_date, pay_date) / 360)
            first_period = False
        else:
            interest = money(balance * rate / 100 / terms.frequency)
        if terms.grace_until and pay_date <= terms.grace_until:
            principal = ZERO
            pay = interest
        elif terms.mode == "fixed_repayment":
            principal = min(payment, balance)
            pay = principal + interest
        else:
            principal = min(max(payment - interest, ZERO), balance)
            pay = principal + interest
        balance -= principal
        same_day = [p for p in pending if p.date == pay_date and not p.fee]
        prepay = ZERO
        for p in same_day:
            pending.remove(p)
            prepay += min(p.amount, balance - prepay)
        balance -= prepay
        rows.append(Row(pay_date, pay, interest, principal, prepay, balance, any(p.planned for p in same_day)))
        if payment <= interest and terms.mode == "annuity" and not (terms.grace_until and pay_date <= terms.grace_until):
            break  # payment does not cover interest – avoid an endless schedule
        pay_date = add_months(pay_date, step, terms.first_payment.day)
    return rows


def balance_at(rows: list[Row], start: Decimal, on: date) -> Decimal:
    balance = start
    for row in rows:
        if row.date > on:
            break
        balance = row.balance
    return balance


def expand_planned(planned: list[dict], until: date) -> list[Prepayment]:
    """Planned prepayments from account details: {date, amount, repeat: 'yearly'|None, until}."""
    result: list[Prepayment] = []
    for item in planned:
        try:
            d = date.fromisoformat(item["date"])
            amount = Decimal(str(item["amount"]))
        except (KeyError, ValueError):
            continue
        end = date.fromisoformat(item["until"]) if item.get("until") else until
        if item.get("repeat") == "yearly":
            while d <= min(end, until):
                result.append(Prepayment(d, amount, planned=True))
                d = add_months(d, 12)
        else:
            result.append(Prepayment(d, amount, planned=True))
    return result
