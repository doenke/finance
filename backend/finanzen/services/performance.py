"""Aggregated value series, net worth and returns for a scope (account, asset class, person, household)."""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import cache, kinds
from ..models import Account, Instrument
from .returns import ReturnResult, compute_returns, ttwror_series
from .series import Context, account_series, day_range, first_data_date, position_series

ZERO = Decimal("0")
PERIODS = ["1M", "YTD", "1Y", "3Y", "5Y", "ALL"]


def period_start(period: str, end: date, inception: date) -> date:
    """Base day of a period: the value at the end of this day is the starting value."""
    if period == "1M":
        base = _shift_months(end, -1)
    elif period == "YTD":
        base = date(end.year - 1, 12, 31)
    elif period in ("1Y", "3Y", "5Y"):
        base = _shift_months(end, -12 * int(period[0]))
    else:
        base = inception - timedelta(days=1)
    return max(base, inception - timedelta(days=1))


def _shift_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(y, m, day)
        except ValueError:
            continue
    raise ValueError


@dataclass
class Scope:
    account_id: int | None = None
    asset_class: str | None = None
    person_id: int | None = None

    def accounts(self, db: Session) -> list[Account]:
        stmt = select(Account)
        if self.account_id is not None:
            stmt = stmt.where(Account.id == self.account_id)
        if self.asset_class:
            stmt = stmt.where(Account.asset_class == self.asset_class)
        return list(db.scalars(stmt).all())

    def share(self, account: Account) -> Decimal:
        if self.person_id is None:
            return Decimal("1")
        for owner in account.owners:
            if owner.person_id == self.person_id:
                return owner.share
        return ZERO


def is_liability(account: Account) -> bool:
    kind = kinds.KINDS.get(account.kind)
    return bool(kind and kind.liability)


@dataclass
class Aggregate:
    dates: list[date]
    values: list[Decimal]  # invested assets (performance scope)
    flows: list[Decimal]
    assets: list[Decimal]
    liabilities: list[Decimal]
    by_class: dict[str, list[Decimal]]
    inception: date | None


def aggregate(db: Session, scope: Scope, start: date | None, end: date) -> Aggregate:
    key = ("aggregate", scope.account_id, scope.asset_class, scope.person_id, start, end)
    cached = cache.get(key)
    if cached is not None:
        return cached
    result = _aggregate(db, scope, start, end)
    cache.put(key, result)
    return result


def _aggregate(db: Session, scope: Scope, start: date | None, end: date) -> Aggregate:
    ctx = Context(db)
    accounts = [a for a in scope.accounts(db) if scope.share(a) > 0]
    inception = first_data_date(ctx, accounts)
    if inception is None:
        return Aggregate([], [], [], [], [], {}, None)
    start = start or inception - timedelta(days=1)
    days = day_range(start, end)
    n = len(days)
    values, flows = [ZERO] * n, [ZERO] * n
    assets, liabilities = [ZERO] * n, [ZERO] * n
    by_class: dict[str, list[Decimal]] = {}
    for account in accounts:
        share = scope.share(account)
        s = account_series(ctx, account, start, end)
        row = by_class.setdefault(account.asset_class, [ZERO] * n)
        liability = is_liability(account)
        for i in range(n):
            v = s.values[i] * share
            row[i] += v
            if liability or v < 0:
                liabilities[i] += v
            else:
                assets[i] += v
            if not liability:
                values[i] += v
                flows[i] += s.flows[i] * share
    return Aggregate(days, values, flows, assets, liabilities, by_class, inception)


def sample_indices(n: int, max_points: int = 400) -> list[int]:
    if n <= max_points:
        return list(range(n))
    step = n / (max_points - 1)
    idx = sorted({int(i * step) for i in range(max_points - 1)} | {n - 1})
    return idx


def returns_for(agg: Aggregate, base: date) -> ReturnResult:
    if not agg.dates:
        return compute_returns([], [], [])
    i = max(0, (base - agg.dates[0]).days)
    return compute_returns(agg.dates[i:], agg.values[i:], agg.flows[i:])


def performance(db: Session, scope: Scope, period: str = "ALL", end: date | None = None) -> dict:
    end = end or date.today()
    agg = aggregate(db, scope, None, end)
    if agg.inception is None:
        return {"from": None, "to": end, "summary": None, "periods": {}, "series": []}
    base = period_start(period, end, agg.inception)
    summary = returns_for(agg, base)
    periods = {p: _result_dict(returns_for(agg, period_start(p, end, agg.inception))) for p in PERIODS}
    i = max(0, (base - agg.dates[0]).days)
    dates, values, flows = agg.dates[i:], agg.values[i:], agg.flows[i:]
    cumulative = ttwror_series(values, flows)
    invested = []
    running = values[0] if values else ZERO
    for k, f in enumerate(flows):
        if k:
            running += f
        invested.append(running)
    series = [
        {"date": dates[k], "value": values[k], "invested": invested[k], "ttwror": cumulative[k]}
        for k in sample_indices(len(dates))
    ]
    return {"from": base, "to": end, "inception": agg.inception, "summary": _result_dict(summary), "periods": periods, "series": series}


def net_worth(db: Session, scope: Scope, period: str = "1Y", end: date | None = None) -> dict:
    end = end or date.today()
    agg = aggregate(db, scope, None, end)
    if agg.inception is None:
        return {"series": [], "current": None}
    base = period_start(period, end, agg.inception)
    i = max(0, (base - agg.dates[0]).days)
    idx = [i + k for k in sample_indices(len(agg.dates) - i)]
    series = [
        {
            "date": agg.dates[k],
            "assets": agg.assets[k],
            "liabilities": agg.liabilities[k],
            "net": agg.assets[k] + agg.liabilities[k],
            "by_class": {c: v[k] for c, v in agg.by_class.items() if v[k] != 0},
        }
        for k in idx
    ]

    def net_at(d: date) -> Decimal | None:
        j = (d - agg.dates[0]).days
        return agg.assets[j] + agg.liabilities[j] if 0 <= j < len(agg.dates) else None

    last = len(agg.dates) - 1
    current_net = agg.assets[last] + agg.liabilities[last]
    month_ago, year_ago = net_at(_shift_months(end, -1)), net_at(date(end.year - 1, 12, 31))
    return {
        "series": series,
        "current": {
            "assets": agg.assets[last],
            "liabilities": agg.liabilities[last],
            "net": current_net,
            "by_class": {c: v[last] for c, v in agg.by_class.items() if v[last] != 0},
            "change_month": current_net - month_ago if month_ago is not None else None,
            "change_ytd": current_net - year_ago if year_ago is not None else None,
        },
        "inception": agg.inception,
    }


def benchmark(db: Session, instrument_id: int, start: date, end: date) -> list[dict]:
    """Performance of an instrument in EUR, cumulative from the start day (sampled)."""
    instrument = db.get(Instrument, instrument_id)
    if instrument is None:
        return []
    ctx = Context(db)
    prices = ctx.price_series(instrument_id)
    days = day_range(start, end)
    eur = []
    for d in days:
        p = prices.at(d)
        f = ctx.eur_factor(instrument.currency, d)
        eur.append(p * f if p is not None and f is not None else None)
    base = next((v for v in eur if v), None)
    if base is None:
        return []
    return [{"date": days[k], "ttwror": (eur[k] / base - 1) if eur[k] else None} for k in sample_indices(len(days))]


def _result_dict(r: ReturnResult) -> dict:
    return {
        "start_value": r.start_value,
        "end_value": r.end_value,
        "net_flows": r.net_flows,
        "gain": r.gain,
        "ttwror": r.ttwror,
        "ttwror_pa": r.ttwror_pa,
        "irr": r.irr,
        "days": r.days,
    }


def _avg_capital(agg: Aggregate, base: date, end: date) -> Decimal:
    """Average invested capital over (base, end] (Modified Dietz): value at base plus time-weighted net flows.

    Uses the same period length for every account, so the capitals of all accounts add up to the household's.
    """
    total_days = (end - base).days
    if not agg.dates or total_days <= 0:
        return ZERO
    i = (base - agg.dates[0]).days
    capital = agg.values[i] if i >= 0 else ZERO
    for k in range(max(i + 1, 0), len(agg.dates)):
        if agg.flows[k]:
            capital += agg.flows[k] * Decimal((end - agg.dates[k]).days) / Decimal(total_days)
    return capital


def _position_returns(db: Session, account: Account, share: Decimal, base: date, end: date) -> list[dict]:
    """Return of each position of a holdings account over (base, end], scaled to the person's share."""
    ctx = Context(db)
    start = base - timedelta(days=1)
    out = []
    for iid, s in position_series(ctx, account, start, end).items():
        values = [v * share for v in s.values]
        flows = [f * share for f in s.flows]
        if not any(values) and not any(flows[1:]):
            continue  # nothing held in the period
        agg = Aggregate(s.dates, values, flows, values, [ZERO] * len(values), {}, s.first)
        r = returns_for(agg, base)
        instrument = ctx.instrument(iid)
        out.append(
            {
                "instrument_id": iid,
                "name": instrument.name if instrument else "?",
                "start_value": r.start_value,
                "end_value": r.end_value,
                "net_flows": r.net_flows,
                "gain": r.gain,
                "irr": r.irr,
                "ttwror": r.ttwror,
                "ttwror_pa": r.ttwror_pa,
                "avg_capital": _avg_capital(agg, base, end),
                "sold": values[-1] == 0,
            }
        )
    out.sort(key=lambda p: (p["irr"] is None, -(p["irr"] or ZERO)))
    return out


def breakdown(db: Session, person_id: int | None, period: str = "1Y", end: date | None = None) -> dict:
    """Return per account and each account's contribution to the total return of the period.

    Gains add up exactly; contributions are gain / average capital of the whole household (Modified Dietz),
    so they add up to the total simple return of the period.
    """
    end = end or date.today()
    scope = Scope(person_id=person_id)
    total = aggregate(db, scope, None, end)
    if total.inception is None:
        return {"from": None, "to": end, "total": None, "items": []}
    base = period_start(period, end, total.inception)
    items = []
    for account in scope.accounts(db):
        if scope.share(account) <= 0 or is_liability(account):
            continue
        agg = aggregate(db, Scope(account_id=account.id, person_id=person_id), None, end)
        if not agg.dates or agg.dates[-1] < base:
            continue
        r = returns_for(agg, base)
        capital = _avg_capital(agg, base, end)
        if r.start_value == 0 and r.end_value == 0 and r.net_flows == 0:
            continue
        kind = kinds.KINDS.get(account.kind)
        positions = _position_returns(db, account, scope.share(account), base, end) if kind and kind.mode == kinds.HOLDINGS else None
        items.append(
            {
                "positions": positions,
                "account_id": account.id,
                "name": account.name,
                "kind": account.kind,
                "kind_label": kind.label if kind else account.kind,
                "asset_class": account.asset_class,
                "start_value": r.start_value,
                "end_value": r.end_value,
                "net_flows": r.net_flows,
                "gain": r.gain,
                "irr": r.irr,
                "ttwror": r.ttwror,
                "ttwror_pa": r.ttwror_pa,
                "avg_capital": capital,
            }
        )
    total_gain = sum((i["gain"] for i in items), ZERO)
    total_capital = sum((i["avg_capital"] for i in items), ZERO)
    for i in items:
        i["contribution"] = i["gain"] / total_capital if total_capital > 0 else None
        i["weight"] = i["avg_capital"] / total_capital if total_capital > 0 else None
        for p in i["positions"] or []:
            p["contribution"] = p["gain"] / total_capital if total_capital > 0 else None
    items.sort(key=lambda i: (i["irr"] is None, -(i["irr"] or ZERO)))
    overall = returns_for(total, base)
    return {
        "from": base,
        "to": end,
        "total": {
            "gain": total_gain,
            "avg_capital": total_capital,
            "simple_return": total_gain / total_capital if total_capital > 0 else None,
            "irr": overall.irr,
            "ttwror": overall.ttwror,
            "ttwror_pa": overall.ttwror_pa,
        },
        "items": items,
    }
