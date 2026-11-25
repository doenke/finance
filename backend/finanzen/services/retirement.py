"""Retirement projection for one person: pensions plus withdrawals from invested capital, in today's money.

All results are rough estimates and labelled as such in the UI:
- statutory pension (product "gesetzlich"): the projected pension from the DRV statement is taken as today's money
  (the DRV figure assumes no future pension increases, which roughly matches constant purchasing power);
- other contracts with an expected pension: nominal amounts at their start, deflated with the inflation assumption;
- invested capital (depots, crypto, call money, fixed-term deposits, participations, capital contracts) grows with the
  scenario return and the monthly savings until retirement and is then paid out as an annuity over `years` years;
- net: health/long-term care insurance for pensioners (KVdR) and income tax with the 2025 basic tariff, plus flat-rate
  tax on the gain share of the capital withdrawals. No splitting, church tax, allowances or special cases.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import kinds
from ..models import Account
from .cashflow import role_of, year_balance
from .performance import Scope
from .valuation import account_value, holdings_value

SCENARIOS = {"vorsichtig": 0.03, "mittel": 0.05, "optimistisch": 0.07}
SCENARIO_LABELS = {"vorsichtig": "Vorsichtig", "mittel": "Mittel", "optimistisch": "Optimistisch"}
PRODUCT_LABELS = {
    "gesetzlich": "Gesetzliche Rente",
    "riester": "Riester",
    "ruerup": "Basisrente",
    "bav": "Betriebsrente",
    "rente": "Private Rente",
    "leben": "Lebensversicherung",
    "bauspar": "Bausparvertrag",
    "other": "Sonstiges",
}
CAPITAL_KINDS = {"depot", "krypto", "edelmetall", "stak", "tagesgeld", "festgeld", "verrechnung"}

# health and long-term care insurance of pensioners (statutory insurance, with children)
KV_STATUTORY = 0.0875 + 0.036  # half of 14.6 % + half of ~2.9 % average additional rate, plus care 3.6 %
KV_BAV = 0.175 + 0.036  # company pensions: full rate above the allowance
BAV_ALLOWANCE = 187.25  # per month
FLAT_TAX = 0.26375  # capital gains tax incl. solidarity surcharge
PRIVATE_SHARE = 0.17  # taxable share of a private annuity starting at 67 (Ertragsanteil)


def _date(value) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _num(value) -> float | None:
    try:
        return float(Decimal(str(value))) if value not in (None, "") else None
    except Exception:
        return None


def taxable_share_statutory(start_year: int) -> float:
    """Besteuerungsanteil of statutory pensions and Basisrente: 82.5 % for 2023, +0.5 points per year, 100 % from 2058."""
    return min(1.0, max(0.5, 0.825 + 0.005 * (start_year - 2023)))


def income_tax(zve: float) -> float:
    """German income tax, basic tariff 2025 (§ 32a EStG), without solidarity surcharge."""
    x = int(max(zve, 0))
    if x <= 12096:
        return 0.0
    if x <= 17443:
        y = (x - 12096) / 10000
        return (932.30 * y + 1400) * y
    if x <= 68480:
        z = (x - 17443) / 10000
        return (176.64 * z + 2397) * z + 1015.13
    if x <= 277825:
        return 0.42 * x - 10911.92
    return 0.45 * x - 19246.67


def _months_between(a: date, b: date) -> int:
    return max(0, (b.year - a.year) * 12 + (b.month - a.month))


@dataclass
class Params:
    retire_on: date | None = None
    savings: float | None = None  # per month in today's money; default from the last 12 months
    inflation: float = 0.02
    years: int = 25  # withdrawal period
    returns: dict[str, float] | None = None


def projection(db: Session, person_id: int, params: Params, today: date | None = None) -> dict:
    today = today or date.today()
    scope = Scope(person_id=person_id)
    accounts = [a for a in db.scalars(select(Account).where(Account.closed.is_(False))).all() if scope.share(a) > 0]
    returns = {**SCENARIOS, **(params.returns or {})}
    infl = params.inflation

    pensions_raw = []
    capital_items = []
    for a in accounts:
        share = float(scope.share(a))
        d = a.details or {}
        if a.kind == "altersvorsorge" and _num(d.get("expected_pension")):
            pensions_raw.append((a, share, d))
            continue
        if a.kind in CAPITAL_KINDS or (a.kind == "altersvorsorge" and d.get("product") != "gesetzlich"):
            if role_of(a) == "spending":
                continue
            value = float(account_value(db, a, today).value) * share
            if value <= 0:
                continue
            cost = value
            if kinds.KINDS[a.kind].mode == kinds.HOLDINGS:
                _, positions = holdings_value(db, a.id, today)
                cost = float(sum((p.cost for p in positions.values()), Decimal(0))) * share
            capital_items.append({"account_id": a.id, "name": a.name, "kind": a.kind, "value": round(value, 2), "cost": round(cost, 2)})

    statutory = [p for p in pensions_raw if (p[2].get("product") == "gesetzlich")]
    starts = [_date(p[2].get("payout_start")) for p in (statutory or pensions_raw)]
    starts = [s for s in starts if s]
    default_retire = (min(starts) if statutory else max(starts)) if starts else date(today.year + 25, today.month, 1)
    retire_on = params.retire_on or default_retire
    years_to = max(0.0, (retire_on - today).days / 365.25)

    pensions = []
    for a, share, d in pensions_raw:
        product = d.get("product") or "other"
        start = _date(d.get("payout_start")) or retire_on
        amount = _num(d.get("expected_pension")) * share
        if product == "gesetzlich":
            real = amount  # DRV figure without future increases ~ today's money
        else:
            real = amount / (1 + infl) ** max(0.0, (start - today).days / 365.25)
        pensions.append(
            {
                "account_id": a.id,
                "name": a.name,
                "product": product,
                "product_label": PRODUCT_LABELS.get(product, product),
                "start": start,
                "nominal": round(amount, 2),
                "monthly": round(real, 2),
                "after_retirement": start > retire_on,
                "statement_date": d.get("info_date"),
            }
        )
    pensions.sort(key=lambda p: (p["product"] != "gesetzlich", p["start"]))

    # savings: household savings of the last 12 complete months, scaled by the person's share of the capital
    capital_now = sum(c["value"] for c in capital_items)
    savings_default = 0.0
    try:
        yb = year_balance(db, "12m", today)
        household_savings = float(yb["totals"]["savings"]) / 12
        household_capital = 0.0
        for a in db.scalars(select(Account).where(Account.closed.is_(False))).all():
            if (a.kind in CAPITAL_KINDS or (a.kind == "altersvorsorge" and not _num((a.details or {}).get("expected_pension")) and (a.details or {}).get("product") != "gesetzlich")) and role_of(a) != "spending":
                household_capital += max(0.0, float(account_value(db, a, today).value))
        ratio = capital_now / household_capital if household_capital > 0 else 1.0
        savings_default = max(0.0, household_savings * ratio)
    except Exception:  # no bookings yet
        savings_default = 0.0
    savings = params.savings if params.savings is not None else round(savings_default, 0)

    months = _months_between(today, retire_on)
    cost_now = sum(c["cost"] for c in capital_items)
    scenarios = []
    for key, nominal in returns.items():
        rr = ((1 + nominal) / (1 + infl)) ** (1 / 12) - 1  # real monthly return
        series = []
        value = capital_now
        for m in range(months + 1):
            if m % 12 == 0 or m == months:
                series.append({"date": date(today.year + (today.month - 1 + m) // 12, (today.month - 1 + m) % 12 + 1, 1), "value": round(value, 0)})
            if m < months:
                value = value * (1 + rr) + savings
        capital = value
        n = max(1, params.years) * 12
        withdrawal = capital * rr / (1 - (1 + rr) ** -n) if abs(rr) > 1e-9 else capital / n
        invested = cost_now + savings * months
        gain_share = max(0.0, 1 - invested / capital) if capital > 0 else 0.0

        gross_pensions = sum(p["monthly"] for p in pensions)
        kv = 0.0
        taxable = 0.0
        for p in pensions:
            amt = p["monthly"]
            if p["product"] == "gesetzlich":
                kv += amt * KV_STATUTORY
                taxable += amt * taxable_share_statutory(p["start"].year)
            elif p["product"] == "ruerup":
                taxable += amt * taxable_share_statutory(p["start"].year)
            elif p["product"] == "bav":
                kv += max(0.0, amt - BAV_ALLOWANCE) * KV_BAV
                taxable += amt
            elif p["product"] == "riester":
                taxable += amt
            else:
                taxable += amt * PRIVATE_SHARE
        zve = (taxable - kv) * 12 - 102
        tax = income_tax(zve) / 12
        capital_tax = withdrawal * gain_share * FLAT_TAX
        gross = gross_pensions + withdrawal
        scenarios.append(
            {
                "key": key,
                "label": SCENARIO_LABELS.get(key, key),
                "return": nominal,
                "capital": round(capital, 0),
                "withdrawal": round(withdrawal, 0),
                "pensions": round(gross_pensions, 0),
                "gross": round(gross, 0),
                "health": round(kv, 0),
                "income_tax": round(tax, 0),
                "capital_tax": round(capital_tax, 0),
                "net": round(gross - kv - tax - capital_tax, 0),
                "series": series,
            }
        )

    return {
        "person_id": person_id,
        "today": today,
        "retire_on": retire_on,
        "default_retire_on": default_retire,
        "years_to_retirement": round(years_to, 1),
        "inputs": {"savings": savings, "savings_default": round(savings_default, 0), "inflation": infl, "years": params.years, "returns": returns},
        "pensions": pensions,
        "capital": sorted(capital_items, key=lambda c: -c["value"]),
        "capital_now": round(capital_now, 2),
        "scenarios": scenarios,
    }
