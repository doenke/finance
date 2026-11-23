"""Return calculations on daily values and external cash flows.

Conventions:
- values[i] is the value at the end of day i,
- flows[i] is the external cash flow on day i, positive = money put in, negative = money taken out,
- flows happen at the end of the day (trades are booked at the closing price):
  r_i = (V_i - F_i) / V_{i-1} - 1. Days without capital at the start (V_{i-1} <= 0) are skipped.
"""

import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

ZERO = Decimal("0")
ONE = Decimal("1")


@dataclass
class ReturnResult:
    start_value: Decimal
    end_value: Decimal
    net_flows: Decimal
    gain: Decimal
    ttwror: Decimal | None  # cumulative, e.g. 0.12 = +12 %
    ttwror_pa: Decimal | None
    irr: Decimal | None  # annualized
    days: int


def ttwror_series(values: list[Decimal], flows: list[Decimal]) -> list[Decimal]:
    """Cumulative time-weighted return per day, relative to the first day (first entry = 0)."""
    result = [ZERO]
    factor = ONE
    for i in range(1, len(values)):
        base = values[i - 1]
        if base > ZERO:
            factor *= (values[i] - flows[i]) / base
        result.append(factor - ONE)
    return result


def annualize(cumulative: Decimal, days: int) -> Decimal | None:
    if days <= 0 or cumulative <= Decimal("-1"):
        return None
    if days < 365:
        return None  # annualizing short periods exaggerates
    return Decimal(str(math.pow(float(ONE + cumulative), 365.0 / days) - 1))


def xirr(cashflows: list[tuple[date, float]]) -> float | None:
    """Annual internal rate of return; cashflows from the investor's view (negative = paid in)."""
    flows = [(d, a) for d, a in cashflows if a != 0]
    if len(flows) < 2 or not (any(a < 0 for _, a in flows) and any(a > 0 for _, a in flows)):
        return None
    t0 = flows[0][0]
    times = [((d - t0).days / 365.0, a) for d, a in flows]
    if times[-1][0] <= 0:
        return None

    def npv(rate: float) -> float:
        return sum(a / math.pow(1 + rate, t) for t, a in times)

    low, high = -0.9999, 10.0
    f_low, f_high = npv(low), npv(high)
    if f_low * f_high > 0:
        return None
    for _ in range(200):
        mid = (low + high) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-7:
            return mid
        if f_low * f_mid < 0:
            high, f_high = mid, f_mid
        else:
            low, f_low = mid, f_mid
    return (low + high) / 2


def compute_returns(dates: list[date], values: list[Decimal], flows: list[Decimal]) -> ReturnResult:
    """Returns for the whole given period. The first day's flow belongs to the start value."""
    if not dates:
        return ReturnResult(ZERO, ZERO, ZERO, ZERO, None, None, None, 0)
    start_value, end_value = values[0], values[-1]
    net_flows = sum(flows[1:], ZERO)
    gain = end_value - start_value - net_flows
    days = (dates[-1] - dates[0]).days
    has_capital = start_value > ZERO or any(f > ZERO for f in flows[1:])
    cumulative = ttwror_series(values, flows)[-1] if has_capital and len(values) > 1 else None
    cash = [(dates[0], -float(start_value))] if start_value else []
    cash += [(dates[i], -float(flows[i])) for i in range(1, len(dates)) if flows[i]]
    cash.append((dates[-1], float(end_value)))
    rate = xirr(cash) if has_capital else None
    return ReturnResult(
        start_value=start_value,
        end_value=end_value,
        net_flows=net_flows,
        gain=gain,
        ttwror=cumulative,
        ttwror_pa=annualize(cumulative, days) if cumulative is not None else None,
        irr=Decimal(str(rate)) if rate is not None else None,
        days=days,
    )
