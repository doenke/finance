"""Monthly cash flow: income, spending and savings from the actual bookings.

Every cash account has a role: "spending" (everyday accounts) or "saving" (reserves and investments).
The savings of a month are the net flow from spending to saving accounts plus savings paid out directly
(e.g. Riester, savings plans: category kind "transfer"). Transfers within one role do not count, nor do
bookings categorised as internal transfers ("Umbuchungen"). Income and spending are the remaining
bookings of the spending accounts.
"""

import re
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import kinds
from ..models import Account, Category, Transaction
from . import recurring as rec

ZERO = Decimal("0")
ROLES = ("spending", "saving")
ROLE_LABELS = {"spending": "Haushaltskonto", "saving": "Sparkonto"}
DEFAULT_ROLE = {"giro": "spending", "kreditkarte": "spending", "tagesgeld": "saving", "verrechnung": "saving", "festgeld": "saving"}


def role_of(account: Account) -> str | None:
    """Role of an account in the money flow; None for accounts without bookings of their own (pensions, loans …)."""
    chosen = (account.details or {}).get("flow_role")
    if chosen in ROLES:
        return chosen
    if account.kind in DEFAULT_ROLE:
        return DEFAULT_ROLE[account.kind]
    kind = kinds.KINDS.get(account.kind)
    if kind and kind.mode == kinds.HOLDINGS:
        return "saving"
    return None


def _month(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _months_back(end: date, n: int) -> list[str]:
    out = []
    y, m = end.year, end.month
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out[::-1]


def _mirror_ok(t: rec.Tx, names_own: list[str]) -> bool:
    """A mirrored booking only counts as a transfer if it is unlikely to be a coincidence."""
    a = abs(t.amount)
    has_cents = a != a.to_integral_value()
    return has_cents or a >= 500 or any(n in t.counterparty.lower() for n in names_own)


def cashflow(
    db: Session,
    months: int = 12,
    month: str | None = None,
    end: date | None = None,
    detail_months: list[str] | None = None,
    compare_months: list[str] | None = None,
    compare_until: date | None = None,
) -> dict:
    """Monthly rows plus a breakdown by category for one month, or for `detail_months` (a year view).

    With `compare_months` every breakdown entry also carries its sum over those months ("previous").
    """
    end = end or date.today()
    month_keys = _months_back(end, months)
    first = date(int(month_keys[0][:4]), int(month_keys[0][5:]), 1)
    accounts = list(db.scalars(select(Account)).all())
    roles = {a.id: role_of(a) for a in accounts}
    names = {a.id: a.name for a in accounts}
    iban_to_account = {re.sub(r"\s", "", a.iban).upper(): a.id for a in accounts if a.iban}
    from .categorize import Categorizer, suggest_pattern

    categorize = Categorizer(db)
    names_own = rec.own_names(db)

    txs = [t for t in rec.load_transactions(db, first) if t.date <= end]
    # also bookings without a match key (empty counterparty and purpose) count for the sums
    keyed = {t.id for t in txs}
    for t in db.scalars(select(Transaction).where(Transaction.booking_date >= first, Transaction.booking_date <= end)).all():
        if t.id not in keyed and roles.get(t.account_id) and t.amount != 0:
            txs.append(rec.Tx(t.id, t.account_id, t.booking_date, t.amount, t.counterparty or "", t.purpose or "", "", t.category_id))
    by_amount: dict[Decimal, list[rec.Tx]] = defaultdict(list)
    for t in txs:
        by_amount[abs(t.amount)].append(t)

    # Trades in depots/crypto: a debit that matches a purchase (amount incl. fees) or a credit that matches the
    # proceeds of a sale belongs to that depot – shown as "Giro → Depot" instead of a category.
    from ..models import Trade

    trade_amounts: dict[Decimal, list[tuple[date, int]]] = defaultdict(list)
    holdings_ids = [a.id for a in accounts if kinds.KINDS.get(a.kind) and kinds.KINDS[a.kind].mode == kinds.HOLDINGS]
    if holdings_ids:
        for tr in db.scalars(
            select(Trade).where(Trade.account_id.in_(holdings_ids), Trade.date >= first - timedelta(days=7), Trade.date <= end + timedelta(days=7), Trade.type.in_(("buy", "sell")))
        ).all():
            total = (tr.amount + tr.fees + tr.taxes) if tr.type == "buy" else (tr.amount - tr.fees - tr.taxes)
            trade_amounts[(-total if tr.type == "buy" else total).quantize(Decimal("0.01"))].append((tr.date, tr.account_id))
    trade_used: set[tuple[date, int, Decimal]] = set()

    def trade_account(t: rec.Tx) -> int | None:
        for d, acc in sorted(trade_amounts.get(t.amount.quantize(Decimal("0.01")), []), key=lambda x: abs((x[0] - t.date).days)):
            key = (d, acc, t.amount)
            if abs((d - t.date).days) <= 5 and key not in trade_used:
                trade_used.add(key)
                return acc
        return None

    def other_account(t: rec.Tx) -> int | None:
        for i in t.ibans:
            acc = iban_to_account.get(i)
            if acc is not None and acc != t.account_id:
                return acc
        depot = trade_account(t)
        if depot is not None and depot != t.account_id:
            return depot
        if not _mirror_ok(t, names_own):
            return None
        mirror = [u for u in by_amount[abs(t.amount)] if u.account_id != t.account_id and u.amount == -t.amount and abs((u.date - t.date).days) <= 4]
        return min(mirror, key=lambda u: abs((u.date - t.date).days)).account_id if mirror else None

    how: dict[int, tuple[Category | None, str | None]] = {}  # per booking: category and where it came from

    def guess_category(t: rec.Tx) -> Category | None:
        how[t.id] = categorize(t)
        return how[t.id][0]

    unknown: dict[str, dict] = {}  # spending without a category over the whole period, grouped by pattern

    stats = {m: {"income": ZERO, "expenses": ZERO, "savings": ZERO, "internal": ZERO} for m in month_keys}
    # default: the last complete month (the current one usually lacks the salary yet)
    detail_month = month if month in stats else (month_keys[-2] if len(month_keys) > 1 else month_keys[-1])
    detail_set = set(detail_months) if detail_months else {detail_month}
    compare_set = set(compare_months or [])
    detail = {"income": {}, "expenses": {}, "savings": {}, "uncategorized": []}
    previous: dict[str, dict[str, Decimal]] = {"income": defaultdict(lambda: ZERO), "expenses": defaultdict(lambda: ZERO), "savings": defaultdict(lambda: ZERO)}

    routed: set[int] = set()  # bookings counted by account pair – a category does not change them
    month_all: list[tuple[rec.Tx, str]] = []  # single-month view: every booking with where it counts

    def note(t: rec.Tx, m: str, where: str) -> None:
        if detail_months is None and m in detail_set:
            month_all.append((t, where))

    def add(section: str, label: str, amount: Decimal, t: rec.Tx, m: str) -> None:
        """Sum per label for the detail months and keep the single bookings behind it."""
        if m in compare_set and (compare_until is None or t.date <= compare_until):
            previous[section][label] += amount
        if m not in detail_set:
            return
        e = detail[section].setdefault(label, {"amount": ZERO, "bookings": []})
        e["amount"] += amount
        e["bookings"].append(t)

    for t in txs:
        m = _month(t.date)
        if m not in stats or roles.get(t.account_id) != "spending":
            continue  # saving accounts: only their flows with spending accounts count (seen from the spending side)
        s = stats[m]
        other = other_account(t)
        cat = guess_category(t)
        if other is not None:
            other_role = roles.get(other)
            if other_role == "saving":
                s["savings"] -= t.amount  # out = saved, in = taken from savings
                # net per pair of accounts, always seen from the everyday account
                add("savings", f"{names[t.account_id]} → {names[other]}", -t.amount, t, m)
                routed.add(t.id)
                note(t, m, "Gespart (zwischen Konten)")
            else:
                s["internal"] += abs(t.amount)
                routed.add(t.id)
                note(t, m, "Umbuchung zwischen Haushaltskonten")
            continue
        if cat is not None and cat.kind == "internal":
            s["internal"] += abs(t.amount)
            note(t, m, "Umbuchung (zählt nicht)")
            continue
        if cat is not None and cat.kind == "transfer":
            s["savings"] -= t.amount
            add("savings", f"{cat.name}: {rec.suggest_name(t.counterparty, t.purpose, t.key or '')}", -t.amount, t, m)
            note(t, m, "Gespart")
            continue
        label = cat.name if cat is not None else "Ohne Kategorie"
        if t.amount > 0:
            s["income"] += t.amount
            add("income", label, t.amount, t, m)
            note(t, m, "Einnahme")
        else:
            s["expenses"] -= t.amount
            add("expenses", label, -t.amount, t, m)
            note(t, m, "Ausgabe")
            if cat is None and m in detail_set:
                detail["uncategorized"].append(t)
            if cat is None:
                pattern = suggest_pattern(t.counterparty, t.purpose) or "?"
                g = unknown.setdefault(pattern, {"pattern": pattern, "count": 0, "total": ZERO, "example": t.counterparty or t.purpose, "purpose": t.purpose[:140], "last": t.date})
                g["count"] += 1
                g["total"] -= t.amount
                if t.date >= g["last"]:
                    g["last"], g["example"], g["purpose"] = t.date, (t.counterparty or t.purpose)[:80], t.purpose[:140]

    rows = []
    for m in month_keys:
        s = stats[m]
        rows.append(
            {
                "month": m,
                "income": s["income"],
                "expenses": s["expenses"],
                "savings": s["savings"],
                "savings_rate": float(s["savings"] / s["income"]) if s["income"] > 0 else None,
                "rest": s["income"] - s["expenses"] - s["savings"],
                "internal": s["internal"],
            }
        )

    def booking(t: rec.Tx) -> dict:
        cat, source = how.get(t.id, (None, None))
        return {
            "id": t.id,
            "date": t.date,
            "amount": t.amount,
            "counterparty": t.counterparty,
            "purpose": t.purpose[:200],
            "account": names[t.account_id],
            "category_id": cat.id if cat is not None else None,
            "category_source": source,  # fixed (set on the booking), rule, keyword or None
            "assignable": t.id not in routed,
            "pattern": suggest_pattern(t.counterparty, t.purpose) or "",  # proposal for a rule
            # a category left on a booking that counts by account pair: it has no effect, but can be removed
            "stale_category": t.id in routed and t.category_id is not None,
        }

    def sorted_items(section: str) -> list[dict]:
        d, prev = detail[section], previous[section]
        items = [
            {
                "name": k,
                "amount": v["amount"],
                "previous": prev.get(k, ZERO) if compare_set else None,
                "bookings": [booking(t) for t in sorted(v["bookings"], key=lambda t: (t.amount, t.date))],
            }
            for k, v in sorted(d.items(), key=lambda kv: kv[1]["amount"], reverse=True)
            if v["amount"] != 0
        ]
        # categories that only existed in the comparison period
        items += [{"name": k, "amount": ZERO, "previous": v, "bookings": []} for k, v in sorted(prev.items(), key=lambda kv: -kv[1]) if v != 0 and k not in d]
        return items

    top_unknown = sorted(detail["uncategorized"], key=lambda t: t.amount)[:10]
    return {
        "months": rows,
        "month": detail_month,
        "detail": {
            "income": sorted_items("income"),
            "expenses": sorted_items("expenses"),
            "savings": sorted_items("savings"),
            "uncategorized": [booking(t) for t in top_unknown],
            # single-month view only: all bookings of the household accounts, newest first
            "all": [booking(t) | {"counts_as": where} for t, where in sorted(month_all, key=lambda x: (x[0].date, x[0].id), reverse=True)],
        },
        "unknown_groups": sorted(unknown.values(), key=lambda g: g["total"], reverse=True)[:20],
        "accounts": [
            {"id": a.id, "name": a.name, "kind": a.kind, "role": roles[a.id], "automatic": (a.details or {}).get("flow_role") not in ROLES}
            for a in sorted(accounts, key=lambda a: a.name)
            if roles[a.id] is not None and not a.closed
        ],
    }


def _shift_year(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29 February
        return d.replace(year=d.year + years, day=28)


def _month_list(first: date, last: date) -> list[str]:
    out, y, m = [], first.year, first.month
    while (y, m) <= (last.year, last.month):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def year_balance(db: Session, period: str = "ytd", end: date | None = None) -> dict:
    """Income, spending and savings over a year-like period compared with the same period a year earlier.

    period: "ytd" (1 January to today), "12m" (the last twelve complete months) or a past calendar year ("2025").
    """
    end = end or date.today()
    if period == "ytd":
        start, stop, label = date(end.year, 1, 1), end, f"Seit Jahresbeginn {end.year}"
    elif period == "12m":
        stop = date(end.year, end.month, 1).replace(day=1)
        stop = date.fromordinal(stop.toordinal() - 1)  # last day of the previous month
        start = date(stop.year - 1, stop.month, 1)
        start = date(start.year + 1, 1, 1) if start.month == 12 else date(start.year, start.month + 1, 1)
        label = "Letzte 12 Monate"
    elif period.isdigit() and len(period) == 4 and 1990 < int(period) < end.year:
        year = int(period)
        start, stop, label = date(year, 1, 1), date(year, 12, 31), str(year)
    else:
        raise ValueError("Unbekannter Zeitraum")
    window = _month_list(start, stop)
    prev_start, prev_stop = _shift_year(start, -1), _shift_year(stop, -1)
    compare = _month_list(prev_start, prev_stop)
    data = cashflow(db, months=len(window) + 12, end=stop, detail_months=window, compare_months=compare, compare_until=prev_stop)
    rows = [r for r in data["months"] if r["month"] in set(window)]

    def totals(income: Decimal, expenses: Decimal, savings: Decimal, internal: Decimal | None = None) -> dict:
        return {
            "income": income,
            "expenses": expenses,
            "savings": savings,
            "rest": income - expenses - savings,
            "savings_rate": float(savings / income) if income > 0 else None,
            "internal": internal,
        }

    cur = totals(*(sum((r[k] for r in rows), ZERO) for k in ("income", "expenses", "savings", "internal")))
    prev = totals(*(sum(((e["previous"] or ZERO) for e in data["detail"][k]), ZERO) for k in ("income", "expenses", "savings")))
    has_previous = any(e["previous"] for k in ("income", "expenses", "savings") for e in data["detail"][k])
    n = len(window)
    first_tx = db.scalar(select(Transaction.booking_date).order_by(Transaction.booking_date).limit(1))
    return {
        "period": period,
        "label": label,
        "from": start,
        "to": stop,
        "compare_from": prev_start,
        "compare_to": prev_stop,
        "months": rows,
        "totals": cur,
        "previous": prev if has_previous else None,
        "average": {k: cur[k] / n for k in ("income", "expenses", "savings", "rest")},
        "detail": data["detail"],
        "years": list(range(end.year - 1, first_tx.year - 1, -1)) if first_tx else [],
    }
