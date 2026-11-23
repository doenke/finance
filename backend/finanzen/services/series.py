"""Daily value series and external cash flows per account, computed in memory."""

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import kinds
from ..models import Account, BalanceSnapshot, FxRate, Instrument, Price, Trade, Transaction, Valuation
from .deposit import deposit_value
from .loan import schedule
from .valuation import _dec, _date, loan_prepayments, loan_terms, unit_factor

ZERO = Decimal("0")
CENT = Decimal("0.01")


def day_range(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


class StepSeries:
    """Forward-filled values at dates (last known value on or before a day)."""

    def __init__(self, points: list[tuple[date, Decimal]]) -> None:
        points = sorted(points)
        self.dates = [d for d, _ in points]
        self.values = [v for _, v in points]

    def at(self, d: date) -> Decimal | None:
        i = bisect_right(self.dates, d)
        return self.values[i - 1] if i else None

    @property
    def first(self) -> date | None:
        return self.dates[0] if self.dates else None


@dataclass
class AccountSeries:
    account: Account
    dates: list[date]
    values: list[Decimal]
    flows: list[Decimal]
    first: date | None = None  # first day with data

    def value_at(self, d: date) -> Decimal:
        if not self.dates or d < self.dates[0]:
            return ZERO
        return self.values[min((d - self.dates[0]).days, len(self.values) - 1)]


@dataclass
class Context:
    """Shared, preloaded data (prices, fx) for many accounts."""

    db: Session
    prices: dict[int, StepSeries] = field(default_factory=dict)
    fx: dict[str, StepSeries] = field(default_factory=dict)
    instruments: dict[int, Instrument] = field(default_factory=dict)
    _arrays: dict = field(default_factory=dict)

    def instrument(self, iid: int) -> Instrument | None:
        if iid not in self.instruments:
            self.instruments[iid] = self.db.get(Instrument, iid)
        return self.instruments[iid]

    def price_series(self, iid: int) -> StepSeries:
        if iid not in self.prices:
            rows = self.db.execute(select(Price.date, Price.close).where(Price.instrument_id == iid)).all()
            points = [(d, c) for d, c in rows]
            first_market = min((d for d, _ in points), default=None)
            # Trade prices fill the time before the first market price (and instruments without prices).
            trades = self.db.execute(
                select(Trade.date, Trade.price).where(Trade.instrument_id == iid, Trade.price.is_not(None))
            ).all()
            points += [(d, p) for d, p in trades if first_market is None or d < first_market]
            dedup: dict[date, Decimal] = {}
            for d, p in points:
                dedup.setdefault(d, p)
            self.prices[iid] = StepSeries(list(dedup.items()))
        return self.prices[iid]

    def multiplier_array(self, iid: int, days: list[date]) -> list[Decimal | None]:
        """Per day: EUR value of one held unit (unit factor x price x fx), forward-filled."""
        key = (iid, days[0], days[-1])
        cached = self._arrays.get(key)
        if cached is not None:
            return cached
        inst = self.instrument(iid)
        if inst is None:
            return [None] * len(days)
        unit = unit_factor(inst)
        prices = self._fill(self.price_series(iid), days)
        if inst.currency.upper() == "EUR":
            result = [unit * p if p is not None else None for p in prices]
        else:
            self.eur_factor(inst.currency, days[0])  # loads the series
            fx = self._fill(self.fx[inst.currency.upper()], days)
            result = [unit * p * f if p is not None and f is not None else None for p, f in zip(prices, fx, strict=True)]
        self._arrays[key] = result
        return result

    @staticmethod
    def _fill(series: "StepSeries", days: list[date]) -> list[Decimal | None]:
        out: list[Decimal | None] = []
        i = bisect_right(series.dates, days[0]) - 1
        current = series.values[i] if i >= 0 else None
        j = i + 1
        for d in days:
            while j < len(series.dates) and series.dates[j] <= d:
                current = series.values[j]
                j += 1
            out.append(current)
        return out

    def eur_factor(self, currency: str, d: date) -> Decimal | None:
        currency = currency.upper()
        if currency == "EUR":
            return Decimal("1")
        if currency not in self.fx:
            rows = self.db.execute(select(FxRate.date, FxRate.rate).where(FxRate.currency == currency)).all()
            self.fx[currency] = StepSeries([(d2, Decimal("1") / r) for d2, r in rows if r])
        return self.fx[currency].at(d)


def _cash_series(ctx: Context, account: Account, days: list[date]) -> tuple[list[Decimal], list[Decimal], date | None]:
    db = ctx.db
    snaps = sorted(db.execute(select(BalanceSnapshot.date, BalanceSnapshot.amount).where(BalanceSnapshot.account_id == account.id)).all())
    txs = db.execute(select(Transaction.booking_date, Transaction.amount, Transaction.kind).where(Transaction.account_id == account.id)).all()
    delta: dict[date, Decimal] = defaultdict(lambda: ZERO)
    interest: dict[date, Decimal] = defaultdict(lambda: ZERO)
    for d, amount, kind in txs:
        delta[d] += amount
        if kind == "interest":
            interest[d] += amount
    snap_map = dict(snaps)
    first = min([d for d, _ in snaps] + list(delta.keys()), default=None)
    values, flows = [], []
    current = ZERO
    # Start value: replay everything before the first day.
    start = days[0]
    base_snap = max((d for d in snap_map if d < start), default=None)
    current = snap_map[base_snap] if base_snap else ZERO
    current += sum((v for d, v in delta.items() if d < start and (base_snap is None or d > base_snap)), ZERO)
    prev = current
    for d in days:
        if d in snap_map:
            current = snap_map[d]
        else:
            current += delta.get(d, ZERO)
        # For cash every change is external except interest.
        flows.append(current - prev - interest.get(d, ZERO))
        values.append(current)
        prev = current
    if values:
        flows[0] = ZERO
    return values, flows, first


def _holdings_series(ctx: Context, account: Account, days: list[date]) -> tuple[list[Decimal], list[Decimal], date | None]:
    trades = ctx.db.scalars(select(Trade).where(Trade.account_id == account.id).order_by(Trade.date, Trade.id)).all()
    if not trades:
        return [ZERO] * len(days), [ZERO] * len(days), None
    flow_by_day: dict[date, Decimal] = defaultdict(lambda: ZERO)
    events: dict[date, list[Trade]] = defaultdict(list)
    for t in trades:
        events[t.date].append(t)
        if t.type == "buy":
            flow_by_day[t.date] += t.amount + t.fees + t.taxes
        elif t.type == "deliver_in":
            flow_by_day[t.date] += t.amount
        elif t.type == "sell":
            flow_by_day[t.date] -= t.amount - t.fees - t.taxes
        elif t.type == "deliver_out":
            flow_by_day[t.date] -= t.amount
        elif t.type in ("dividend", "interest"):
            flow_by_day[t.date] -= t.amount - t.taxes - t.fees
        elif t.type in ("tax", "fee", "advance_tax"):
            flow_by_day[t.date] += t.amount + t.taxes + t.fees
        elif t.type == "tax_refund":
            flow_by_day[t.date] -= t.amount
    quantities: dict[int, Decimal] = defaultdict(lambda: ZERO)

    def apply(t: Trade) -> None:
        if t.instrument_id is None:
            return
        if t.type in ("buy", "deliver_in"):
            quantities[t.instrument_id] += t.quantity
        elif t.type in ("sell", "deliver_out"):
            quantities[t.instrument_id] -= t.quantity
        elif t.type == "split" and t.quantity > 0:
            quantities[t.instrument_id] *= t.quantity

    start = days[0]
    for d in sorted(k for k in events if k < start):
        for t in events[d]:
            apply(t)
    values, flows = [], []
    arrays: dict[int, list[Decimal | None]] = {}
    for k, d in enumerate(days):
        for t in events.get(d, []):
            apply(t)
        total = ZERO
        for iid, qty in quantities.items():
            if qty == ZERO:
                continue
            arr = arrays.get(iid)
            if arr is None:
                arr = arrays[iid] = ctx.multiplier_array(iid, days)
            m = arr[k]
            if m is not None:
                total += qty * m
        values.append(total.quantize(CENT))
        flows.append(flow_by_day.get(d, ZERO))
    return values, flows, trades[0].date


def _valuation_series(ctx: Context, account: Account, days: list[date]) -> tuple[list[Decimal], list[Decimal], date | None]:
    """Value = last valuation plus contributions/withdrawals since then (before the first valuation: paid in so far)."""
    db = ctx.db
    vals = dict(db.execute(select(Valuation.date, Valuation.value).where(Valuation.account_id == account.id)).all())
    d = account.details or {}
    purchase_date = _date(d.get("purchase_date"))
    purchase_price = _dec(d.get("purchase_price"))
    purchase_costs = _dec(d.get("purchase_costs"))
    flow_by_day: dict[date, Decimal] = defaultdict(lambda: ZERO)  # external flows for returns
    capital_by_day: dict[date, Decimal] = defaultdict(lambda: ZERO)  # flows that change the asset's value
    if purchase_date and purchase_price:
        flow_by_day[purchase_date] += purchase_price + purchase_costs
        vals.setdefault(purchase_date, purchase_price)
    txs = db.execute(select(Transaction.booking_date, Transaction.amount, Transaction.kind).where(Transaction.account_id == account.id)).all()
    for t_date, amount, kind in txs:
        if kind in ("contribution", "deposit"):
            flow_by_day[t_date] += abs(amount)
            capital_by_day[t_date] += abs(amount)
        elif kind == "withdrawal":
            flow_by_day[t_date] -= abs(amount)
            capital_by_day[t_date] -= abs(amount)
        elif kind == "income":
            flow_by_day[t_date] -= abs(amount)
        elif kind in ("fee", "tax"):
            flow_by_day[t_date] += abs(amount)
    candidates = [k for k in list(vals) + list(flow_by_day) if k]
    first = min(candidates, default=None)

    # Replay everything before the first day, then walk day by day.
    base = ZERO
    since = ZERO
    has_valuation = False
    for k in sorted(set(vals) | set(capital_by_day)):
        if k >= days[0]:
            break
        if k in vals:
            base, since, has_valuation = vals[k], ZERO, True
        else:
            since += capital_by_day[k]
    values, flows = [], []
    first_valuation_without_flows = not purchase_date and vals and not any(k <= min(vals) for k in capital_by_day)
    for day in days:
        if day in vals:
            base, since, has_valuation = vals[day], ZERO, True
        else:
            since += capital_by_day.get(day, ZERO)
        value = base + since if has_valuation else since
        values.append(max(value, ZERO))
        flow = flow_by_day.get(day, ZERO)
        if first_valuation_without_flows and day == min(vals):
            flow += vals[day]  # the first statement brings in the starting capital
        flows.append(flow)
    return values, flows, first


def _deposit_series(ctx: Context, account: Account, days: list[date]) -> tuple[list[Decimal], list[Decimal], date | None]:
    d = account.details or {}
    start = _date(d.get("start")) or account.opened_on
    if not start:
        return [ZERO] * len(days), [ZERO] * len(days), None
    amount, rate, end = _dec(d.get("amount")), _dec(d.get("rate")), _date(d.get("end"))
    values = [deposit_value(amount, rate, start, end, day) for day in days]
    flows = [amount if day == start else ZERO for day in days]
    return values, flows, start


def _loan_series(ctx: Context, account: Account, days: list[date]) -> tuple[list[Decimal], list[Decimal], date | None]:
    terms = loan_terms(account)
    snaps = sorted(ctx.db.execute(select(BalanceSnapshot.date, BalanceSnapshot.amount).where(BalanceSnapshot.account_id == account.id)).all())
    if terms is None:
        series = StepSeries([(d, -abs(a)) for d, a in snaps])
        values = [series.at(day) or ZERO for day in days]
        return values, [ZERO] * len(days), series.first
    prepayments = loan_prepayments(ctx.db, account, include_planned=False, until=days[-1])
    base_rows = schedule(terms, prepayments)
    points = [(terms.disbursed_on, terms.principal)] + [(r.date, r.balance) for r in base_rows]
    if snaps:
        snap_date, snap_amount = snaps[-1]
        anchored = schedule(terms, prepayments, start_balance=abs(snap_amount), start_date=snap_date)
        points = [p for p in points if p[0] < snap_date] + [(snap_date, abs(snap_amount))] + [(r.date, r.balance) for r in anchored]
    series = StepSeries(points)
    values = [-(series.at(day) or ZERO) if day >= terms.disbursed_on else ZERO for day in days]
    return values, [ZERO] * len(days), terms.disbursed_on


BUILDERS = {
    kinds.CASH: _cash_series,
    kinds.HOLDINGS: _holdings_series,
    kinds.VALUATION: _valuation_series,
    kinds.DEPOSIT: _deposit_series,
    kinds.LOAN: _loan_series,
}


def account_series(ctx: Context, account: Account, start: date, end: date) -> AccountSeries:
    days = day_range(start, end)
    mode = kinds.KINDS[account.kind].mode if account.kind in kinds.KINDS else kinds.VALUATION
    values, flows, first = BUILDERS[mode](ctx, account, days)
    return AccountSeries(account, days, values, flows, first)


def first_data_date(ctx: Context, accounts: list[Account]) -> date | None:
    """Earliest day any of the accounts has data (to start 'since inception' views)."""
    best: date | None = None
    probe_end = date.today()
    for account in accounts:
        s = account_series(ctx, account, probe_end, probe_end)
        if s.first and (best is None or s.first < best):
            best = s.first
    return best
