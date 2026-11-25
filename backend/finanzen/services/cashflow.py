"""Monthly cash flow: income, spending and savings from the actual bookings.

Every cash account has a role: "spending" (everyday accounts) or "saving" (reserves and investments).
The savings of a month are the net flow from spending to saving accounts plus savings paid out directly
(e.g. Riester, savings plans: category kind "transfer"). Transfers within one role do not count, nor do
bookings categorised as internal transfers ("Umbuchungen"). Income and spending are the remaining
bookings of the spending accounts.
"""

import re
from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import kinds
from ..models import Account, Category, Transaction
from . import recurring as rec

ZERO = Decimal("0")
ROLES = ("spending", "saving")
ROLE_LABELS = {"spending": "Alltag", "saving": "Sparen"}
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


def cashflow(db: Session, months: int = 12, month: str | None = None, end: date | None = None) -> dict:
    end = end or date.today()
    month_keys = _months_back(end, months)
    first = date(int(month_keys[0][:4]), int(month_keys[0][5:]), 1)
    accounts = list(db.scalars(select(Account)).all())
    roles = {a.id: role_of(a) for a in accounts}
    names = {a.id: a.name for a in accounts}
    iban_to_account = {re.sub(r"\s", "", a.iban).upper(): a.id for a in accounts if a.iban}
    categories = {c.id: c for c in db.scalars(select(Category)).all()}
    by_name = {c.name: c for c in categories.values()}
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

    def other_account(t: rec.Tx) -> int | None:
        for i in t.ibans:
            acc = iban_to_account.get(i)
            if acc is not None and acc != t.account_id:
                return acc
        if not _mirror_ok(t, names_own):
            return None
        mirror = [u for u in by_amount[abs(t.amount)] if u.account_id != t.account_id and u.amount == -t.amount and abs((u.date - t.date).days) <= 4]
        return min(mirror, key=lambda u: abs((u.date - t.date).days)).account_id if mirror else None

    def guess_category(t: rec.Tx) -> Category | None:
        if t.category_id in categories:
            return categories[t.category_id]
        text = f"{t.counterparty} {t.purpose}".lower()
        for name, direction, words in rec.RULES:
            if direction and direction != t.direction:
                continue
            if any(re.search(rf"(?<![a-zäöü]){re.escape(w)}", text) for w in words) and name in by_name:
                return by_name[name]
        return None

    stats = {m: {"income": ZERO, "expenses": ZERO, "savings": ZERO, "internal": ZERO} for m in month_keys}
    # default: the last complete month (the current one usually lacks the salary yet)
    detail_month = month if month in stats else (month_keys[-2] if len(month_keys) > 1 else month_keys[-1])
    detail = {"income": defaultdict(lambda: ZERO), "expenses": defaultdict(lambda: ZERO), "savings": defaultdict(lambda: ZERO), "uncategorized": []}

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
                if m == detail_month:
                    # net per pair of accounts, always seen from the everyday account
                    detail["savings"][f"{names[t.account_id]} → {names[other]}"] -= t.amount
            else:
                s["internal"] += abs(t.amount)
            continue
        if cat is not None and cat.kind == "internal":
            s["internal"] += abs(t.amount)
            continue
        if cat is not None and cat.kind == "transfer":
            s["savings"] -= t.amount
            if m == detail_month:
                detail["savings"][f"{cat.name}: {rec.suggest_name(t.counterparty, t.purpose, t.key or '')}"] -= t.amount
            continue
        label = cat.name if cat is not None else "Ohne Kategorie"
        if t.amount > 0:
            s["income"] += t.amount
            if m == detail_month:
                detail["income"][label] += t.amount
        else:
            s["expenses"] -= t.amount
            if m == detail_month:
                detail["expenses"][label] -= t.amount
                if cat is None:
                    detail["uncategorized"].append(t)

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

    def sorted_items(d: dict) -> list[dict]:
        return [{"name": k, "amount": v} for k, v in sorted(d.items(), key=lambda kv: kv[1], reverse=True) if v != 0]

    top_unknown = sorted(detail["uncategorized"], key=lambda t: t.amount)[:10]
    return {
        "months": rows,
        "month": detail_month,
        "detail": {
            "income": sorted_items(detail["income"]),
            "expenses": sorted_items(detail["expenses"]),
            "savings": sorted_items(detail["savings"]),
            "uncategorized": [{"date": t.date, "amount": t.amount, "counterparty": t.counterparty, "purpose": t.purpose[:120], "account": names[t.account_id]} for t in top_unknown],
        },
        "accounts": [
            {"id": a.id, "name": a.name, "kind": a.kind, "role": roles[a.id], "automatic": (a.details or {}).get("flow_role") not in ROLES}
            for a in sorted(accounts, key=lambda a: a.name)
            if roles[a.id] is not None and not a.closed
        ],
    }
