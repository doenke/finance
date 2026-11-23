"""Fixed-term deposits: value accrues until maturity."""

from datetime import date
from decimal import Decimal

from .loan import money


def deposit_value(amount: Decimal, rate: Decimal, start: date, end: date | None, on: date) -> Decimal:
    if on < start:
        return Decimal("0")
    until = min(on, end) if end else on
    years = Decimal((until - start).days) / Decimal(365)
    return money(amount * (1 + rate / 100) ** years)
