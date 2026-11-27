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

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import kinds
from ..models import Account, Person, Transaction
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
# yearly increase of a running pension unless set on the contract (details.indexation, percent):
# statutory pensions follow wages (~ inflation, None), VBL/company pensions 1 % (VBLklassik), private contracts 0 %
DEFAULT_INDEXATION: dict[str, float | None] = {"gesetzlich": None, "bav": 0.01}


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


def _pension_burden(pensions: list[dict]) -> tuple[float, float]:
    """Monthly health/care insurance and taxable part of one person's pensions."""
    kv = taxable = 0.0
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
    return kv, taxable


def _months_between(a: date, b: date) -> int:
    return max(0, (b.year - a.year) * 12 + (b.month - a.month))


@dataclass
class Params:
    retire_on: date | None = None
    savings: float | None = None  # per month in today's money; default from the last 12 months
    inflation: float = 0.02
    years: int = 25  # withdrawal period
    returns: dict[str, float] | None = None


def projection(db: Session, person_id: int | None, params: Params, today: date | None = None) -> dict:
    """person_id None: the whole household (every account in full, pensions taxed per owner)."""
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

    def own_start(items: list) -> date | None:
        """A person's retirement: the statutory pension start, else the latest start of their contracts."""
        statutory = [_date(p[2].get("payout_start")) for p in items if p[2].get("product") == "gesetzlich"]
        statutory = [x for x in statutory if x]
        others = [x for x in (_date(p[2].get("payout_start")) for p in items) if x]
        return min(statutory) if statutory else (max(others) if others else None)

    by_person: dict[int | None, list] = {}
    for item in pensions_raw:
        by_person.setdefault(item[0].owners[0].person_id if item[0].owners else None, []).append(item)
    starts = [x for x in (own_start(items) for items in by_person.values()) if x]
    if not starts:
        default_retire = date(today.year + 25, today.month, 1)
    elif person_id is None:  # household: the average of everyone's retirement, to the first of a month
        mean = date.fromordinal(round(sum(x.toordinal() for x in starts) / len(starts)))
        default_retire = date(mean.year, mean.month, 1)
    else:
        default_retire = own_start(pensions_raw)
    retire_on = params.retire_on or default_retire
    years_to = max(0.0, (retire_on - today).days / 365.25)

    names = {p.id: p.name for p in db.scalars(select(Person)).all()}
    end_of_payout = date(retire_on.year + max(1, params.years), retire_on.month, 1)  # last year of the withdrawals
    pensions = []
    for a, share, d in pensions_raw:
        product = d.get("product") or "other"
        start = _date(d.get("payout_start")) or retire_on
        amount = _num(d.get("expected_pension")) * share
        if product == "gesetzlich":
            real = amount  # DRV figure without future increases ~ today's money
        else:
            real = amount / (1 + infl) ** max(0.0, (start - today).days / 365.25)
        # real value at the end of the withdrawal period: the yearly increase against inflation
        raw_idx = d.get("indexation")
        indexation = _num(raw_idx) / 100 if raw_idx not in (None, "") and _num(raw_idx) is not None else DEFAULT_INDEXATION.get(product, 0.0)
        years_paid = max(0.0, (end_of_payout - max(start, today)).days / 365.25)
        real_end = real if indexation is None else real * ((1 + indexation) / (1 + infl)) ** years_paid
        owner = a.owners[0].person_id if a.owners else None
        pensions.append(
            {
                "owner_id": owner,
                "owner": names.get(owner),
                "account_id": a.id,
                "name": a.name,
                "product": product,
                "product_label": PRODUCT_LABELS.get(product, product),
                "start": start,
                "nominal": round(amount, 2),
                "monthly": round(real, 2),
                "monthly_end": round(real_end, 2),
                "indexation": indexation,  # None: like inflation
                "indexation_set": raw_idx not in (None, ""),
                "after_retirement": start > retire_on,
                "statement_date": d.get("info_date"),
            }
        )
    pensions.sort(key=lambda p: (p["product"] != "gesetzlich", p["start"]))

    # savings: household savings of the last 12 complete months, scaled by the person's share of the capital
    capital_now = sum(c["value"] for c in capital_items)
    savings_default = 0.0
    savings_parts: dict[str, float] = {}
    try:
        yb = year_balance(db, "12m", today)
        # Contributions to contracts with a pension forecast are already part of that forecast: they must not
        # grow a second time as capital. Savings to own accounts (call money, depots: "A → B") always count;
        # direct contributions (category "Sparen & Anlegen") only as far as they exceed those contributions.
        routed = sum((e["amount"] for e in yb["detail"]["savings"] if " → " in e["name"]), Decimal(0))
        direct = sum((e["amount"] for e in yb["detail"]["savings"] if " → " not in e["name"]), Decimal(0))
        projected_ids = [a.id for a, _, _ in pensions_raw]
        in_pensions = Decimal(0)
        if projected_ids:
            in_pensions = db.scalar(
                select(func.coalesce(func.sum(func.abs(Transaction.amount)), 0)).where(
                    Transaction.account_id.in_(projected_ids),
                    Transaction.kind.in_(("contribution", "deposit")),
                    Transaction.booking_date >= yb["from"],
                    Transaction.booking_date <= yb["to"],
                )
            )
        # only what the direct savings really contain can be taken out; withdrawals (negative) stay in
        # Direct savings that go into a contract with a forecast are recognized by name ("Sparen & Anlegen: HDI …"
        # ↔ "HDI Basisrente"); otherwise by the contributions booked on the contracts.
        from .dedupe import words

        generic = {"rente", "renten", "rentenversicherung", "basisrente", "privatrente", "versicherung", "lebensversicherung", "gesetzliche", "private", "vorsorge", "altersvorsorge", "sparen", "anlegen", "bank", "deutsche"}
        contract_words = [words(a.name, a.institution or "") - generic for a, _, _ in pensions_raw if (a.details or {}).get("product") != "gesetzlich"]
        matched = Decimal(0)
        for e in yb["detail"]["savings"]:
            if " → " in e["name"] or e["amount"] <= 0:
                continue
            entry = words(e["name"].split(":", 1)[-1]) - generic
            if any(entry & cw for cw in contract_words if cw):
                matched += e["amount"]
        direct_paid = sum((e["amount"] for e in yb["detail"]["savings"] if " → " not in e["name"] and e["amount"] > 0), Decimal(0))
        contained = min(max(matched, Decimal(in_pensions)), direct_paid)
        household_savings = float(routed + direct - contained) / 12
        savings_parts = {
            "to_accounts": round(float(routed) / 12, 0),
            "direct": round(float(direct) / 12, 0),
            "in_pensions": round(float(contained) / 12, 0),
        }
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

        def burden(field: str) -> tuple[float, float, float]:
            """Gross pensions, health/care insurance and income tax (per owner, no joint assessment)."""
            kv = tax = 0.0
            by_owner: dict[int | None, list[dict]] = {}
            for p in pensions:
                by_owner.setdefault(p["owner_id"], []).append({**p, "monthly": p[field]})
            for owned in by_owner.values():
                owner_kv, taxable = _pension_burden(owned)
                kv += owner_kv
                tax += income_tax((taxable - owner_kv) * 12 - 102) / 12
            return sum(p[field] for p in pensions), kv, tax

        gross_pensions, kv, tax = burden("monthly")
        end_pensions, end_kv, end_tax = burden("monthly_end")
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
                # the same in the last year of the withdrawals (today's money): pensions that rise slower than
                # prices lose value; the capital withdrawal is constant in real terms
                "pensions_end": round(end_pensions, 0),
                "net_end": round(end_pensions + withdrawal - end_kv - end_tax - capital_tax, 0),
                "series": series,
            }
        )

    return {
        "person_id": person_id,
        "today": today,
        "retire_on": retire_on,
        "default_retire_on": default_retire,
        "years_to_retirement": round(years_to, 1),
        "end_of_payout": end_of_payout,
        "inputs": {"savings": savings, "savings_default": round(savings_default, 0), "savings_parts": savings_parts, "inflation": infl, "years": params.years, "returns": returns},
        "pensions": pensions,
        "capital": sorted(capital_items, key=lambda c: -c["value"]),
        "capital_now": round(capital_now, 2),
        "scenarios": scenarios,
    }
