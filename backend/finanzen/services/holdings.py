"""Positions from portfolio transactions with FIFO cost basis."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

ZERO = Decimal("0")


@dataclass
class TradeIn:
    date: date
    type: str
    instrument_id: int | None
    quantity: Decimal = ZERO
    amount: Decimal = ZERO
    fees: Decimal = ZERO
    taxes: Decimal = ZERO
    id: int = 0


@dataclass
class Lot:
    date: date
    quantity: Decimal
    cost: Decimal  # total cost of the remaining quantity incl. fees


@dataclass
class Sale:
    """Realized gain of one sale, split by whether the sold lots were held longer than a year (§ 23 EStG)."""

    date: date
    short_gain: Decimal = ZERO  # lots held one year or less
    long_gain: Decimal = ZERO


def free_from(acquired: date) -> date:
    """First day a lot can be sold outside the one-year holding period (§ 23 EStG, §§ 187/188 BGB).

    The period ends on the anniversary of the acquisition day (28 Feb for a 29 Feb purchase);
    a sale on the following day is no longer a private sale within the period.
    """
    try:
        anniversary = acquired.replace(year=acquired.year + 1)
    except ValueError:  # 29 February
        anniversary = acquired.replace(year=acquired.year + 1, day=28)
    return date.fromordinal(anniversary.toordinal() + 1)


@dataclass
class Position:
    instrument_id: int
    lots: list[Lot] = field(default_factory=list)
    realized: Decimal = ZERO  # realized gain from sales (after fees, before taxes)
    income: Decimal = ZERO  # dividends/interest received (gross)
    taxes: Decimal = ZERO
    fees: Decimal = ZERO
    sales: list[Sale] = field(default_factory=list)

    @property
    def quantity(self) -> Decimal:
        return sum((lot.quantity for lot in self.lots), ZERO)

    @property
    def cost(self) -> Decimal:
        return sum((lot.cost for lot in self.lots), ZERO)


def _sort_key(t: TradeIn) -> tuple:
    # On the same day: inflows before outflows, so a same-day buy/sell works.
    order = {"buy": 0, "deliver_in": 0, "split": 1}
    return (t.date, order.get(t.type, 2), t.id)


def build_positions(trades: list[TradeIn], until: date | None = None) -> dict[int, Position]:
    positions: dict[int, Position] = defaultdict(lambda: Position(0))
    for t in sorted(trades, key=_sort_key):
        if until is not None and t.date > until:
            break
        if t.instrument_id is None:
            continue
        pos = positions[t.instrument_id]
        pos.instrument_id = t.instrument_id
        pos.fees += t.fees
        pos.taxes += t.taxes
        if t.type in ("buy", "deliver_in"):
            fees = t.fees if t.type == "buy" else ZERO
            pos.lots.append(Lot(t.date, t.quantity, t.amount + fees))
        elif t.type in ("sell", "deliver_out"):
            remaining = t.quantity
            cost_out = ZERO
            sale = Sale(t.date)
            net = t.amount - t.fees
            while remaining > ZERO and pos.lots:
                lot = pos.lots[0]
                take = min(remaining, lot.quantity)
                part = (lot.cost * take / lot.quantity) if lot.quantity else ZERO
                cost_out += part
                if t.type == "sell" and t.quantity:
                    gain = net * take / t.quantity - part
                    if t.date >= free_from(lot.date):
                        sale.long_gain += gain
                    else:
                        sale.short_gain += gain
                lot.quantity -= take
                lot.cost -= part
                remaining -= take
                if lot.quantity <= ZERO:
                    pos.lots.pop(0)
            if t.type == "sell":
                pos.realized += t.amount - t.fees - cost_out
                pos.sales.append(sale)
        elif t.type == "split":
            factor = t.quantity
            if factor > ZERO:
                for lot in pos.lots:
                    lot.quantity *= factor
        elif t.type in ("dividend", "interest"):
            pos.income += t.amount
    return {k: v for k, v in positions.items() if v.instrument_id}
