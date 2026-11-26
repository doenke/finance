"""Comparison of individual positions: price performance, risk, correlation and weight."""

import math
from bisect import bisect_right
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import kinds
from ..models import Account, Instrument, Price
from .fx import FxConverter
from .holdings import ZERO
from .performance import PERIODS, Scope, period_start
from .valuation import holdings_value, position_value

MAX_POINTS = 300


def _close_series(db: Session, instrument: Instrument, start: date, end: date, fx: FxConverter) -> tuple[list[date], list[float]]:
    """Daily closes in EUR (only days with a price)."""
    rows = db.execute(
        select(Price.date, Price.close).where(Price.instrument_id == instrument.id, Price.date >= start, Price.date <= end).order_by(Price.date)
    ).all()
    dates, closes = [], []
    for d, close in rows:
        factor = fx.to_eur_factor(instrument.currency, d)
        if factor is None or close is None or close <= 0:
            continue
        dates.append(d)
        closes.append(float(close * factor))
    return dates, closes


def _value_at(dates: list[date], closes: list[float], day: date) -> float | None:
    i = bisect_right(dates, day) - 1
    return closes[i] if i >= 0 else None


def _change(dates: list[date], closes: list[float], base: date, end: date) -> float | None:
    """Price change from the close on/before `base` to the close on/before `end`; None if there is no price near base."""
    i = bisect_right(dates, base) - 1
    if i < 0 or (base - dates[i]).days > 10:
        return None
    last = _value_at(dates, closes, end)
    return last / closes[i] - 1 if last else None


def _log_returns(dates: list[date], closes: list[float], start: date) -> dict[date, float]:
    out = {}
    for k in range(1, len(dates)):
        if dates[k] > start:
            out[dates[k]] = math.log(closes[k] / closes[k - 1])
    return out


def _volatility(dates: list[date], closes: list[float], start: date, end: date) -> float | None:
    rets = list(_log_returns(dates, closes, start).values())
    if len(rets) < 20:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    years = max((end - start).days / 365.25, 1 / 365.25)
    per_year = len(rets) / years  # ~252 for stocks, ~365 for crypto
    return math.sqrt(var * per_year)


def _max_drawdown(dates: list[date], closes: list[float], start: date) -> float | None:
    peak = None
    worst = 0.0
    for d, c in zip(dates, closes, strict=True):
        if d < start:
            continue
        peak = c if peak is None else max(peak, c)
        worst = min(worst, c / peak - 1)
    return worst if peak is not None else None


def _correlation(a: dict[date, float], b: dict[date, float]) -> float | None:
    common = sorted(set(a) & set(b))
    if len(common) < 20:
        return None
    xs, ys = [a[d] for d in common], [b[d] for d in common]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    vx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    vy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return cov / (vx * vy) if vx and vy else None


def compare(
    db: Session, account_id: int | None = None, person_id: int | None = None, period: str = "1Y", end: date | None = None, extra_ids: list[int] | None = None
) -> dict:
    """Held positions compared with each other; `extra_ids` are candidates (e.g. a fund you think about buying)."""
    end = end or date.today()
    fx = FxConverter(db)
    scope = Scope(person_id=person_id)
    accounts = [
        a
        for a in db.scalars(select(Account).where(Account.closed.is_(False))).all()
        if kinds.KINDS.get(a.kind) and kinds.KINDS[a.kind].mode == kinds.HOLDINGS and (account_id is None or a.id == account_id)
    ]
    # positions per instrument (summed over the chosen depots, weighted by the person's share)
    qty: dict[int, Decimal] = defaultdict(lambda: ZERO)
    cost: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for account in accounts:
        share = scope.share(account)
        if share <= 0:
            continue
        _, positions = holdings_value(db, account.id, end, fx)
        for p in positions.values():
            if p.quantity > 0:
                qty[p.instrument_id] += p.quantity * share
                cost[p.instrument_id] += p.cost * share
    items = []
    for instrument_id in sorted(qty):  # stable order = stable colors
        inst = db.get(Instrument, instrument_id)
        priced = position_value(db, inst, qty[instrument_id], end, fx)
        value = priced[0] if priced else cost[instrument_id].quantize(Decimal("0.01"))
        items.append({"instrument": inst, "quantity": qty[instrument_id], "cost": cost[instrument_id].quantize(Decimal("0.01")), "value": value})
    total = sum((i["value"] for i in items), ZERO)
    for instrument_id in extra_ids or []:
        if instrument_id in qty:
            continue
        inst = db.get(Instrument, instrument_id)
        if inst is not None:
            items.append({"instrument": inst, "quantity": ZERO, "cost": ZERO, "value": ZERO, "candidate": True})

    history_start = end - timedelta(days=365 * 5 + 40)  # enough for the 5-year figures
    series = {it["instrument"].id: _close_series(db, it["instrument"], history_start, end, fx) for it in items}
    first_prices = [ds[0] for ds, _ in series.values() if ds]
    inception = min(first_prices) if first_prices else end
    base = period_start(period, end, inception)

    # common calendar for the chart: all dates with any price in the period, forward filled
    calendar = sorted({d for ds, _ in series.values() for d in ds if base <= d <= end})
    step = max(1, math.ceil(len(calendar) / MAX_POINTS))
    sampled = calendar[::step]
    if calendar and sampled[-1] != calendar[-1]:
        sampled.append(calendar[-1])

    out_items = []
    returns_by_id: dict[int, dict[date, float]] = {}
    for it in items:
        inst = it["instrument"]
        ds, cs = series[inst.id]
        start_close = None
        i0 = bisect_right(ds, base) - 1
        if i0 >= 0 and (base - ds[i0]).days <= 10:
            start_close = cs[i0]
        elif ds and base < ds[0] <= end:
            start_close = cs[0]  # younger than the period: indexed from its first price
        points = []
        for d in sampled:
            v = _value_at(ds, cs, d)
            points.append(None if (v is None or start_close is None or (ds and d < ds[0])) else v / start_close - 1)
        returns_by_id[inst.id] = _log_returns(ds, cs, base)
        gain = it["value"] - it["cost"]
        out_items.append(
            {
                "instrument_id": inst.id,
                "name": inst.name,
                "isin": inst.isin,
                "kind": inst.kind,
                "quantity": it["quantity"],
                "value": it["value"],
                "cost": it["cost"],
                "gain": gain.quantize(Decimal("0.01")),
                "gain_pct": float(gain / it["cost"]) if it["cost"] > 0 else None,
                "weight": float(it["value"] / total) if total > 0 and not it.get("candidate") else None,
                "returns": {p: _change(ds, cs, period_start(p, end, ds[0] if ds else end), end) for p in PERIODS if p != "ALL"},
                "period_return": points[-1] if points else None,
                "volatility": _volatility(ds, cs, max(base, end - timedelta(days=365)), end),
                "max_drawdown": _max_drawdown(ds, cs, base),
                "history_from": ds[0] if ds else None,
                "points": points,
                "candidate": it.get("candidate", False),
            }
        )
    ids = [i["instrument_id"] for i in out_items]
    correlation = [[1.0 if a == b else _correlation(returns_by_id[a], returns_by_id[b]) for b in ids] for a in ids]
    return {
        "from": base,
        "to": end,
        "total_value": total,
        "dates": sampled,
        "items": out_items,
        "correlation": correlation,
    }
