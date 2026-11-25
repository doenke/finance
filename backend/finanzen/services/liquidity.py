"""Available vs. bound assets: what the household could use at short notice and what is tied up."""

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import kinds
from ..models import Account
from .performance import Scope
from .valuation import account_value

ZERO = Decimal("0")


def _date(value) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def is_bound(account: Account) -> bool:
    """Per-account choice in details.liquidity ("available" | "bound"), else the default of the kind."""
    choice = (account.details or {}).get("liquidity")
    if choice in ("available", "bound"):
        return choice == "bound"
    kind = kinds.KINDS.get(account.kind)
    return bool(kind and kind.bound)


def free_from(account: Account) -> tuple[date | None, str | None]:
    """When a bound asset becomes available (if known) and what that date means."""
    d = account.details or {}
    if account.kind == "festgeld" and _date(d.get("end")):
        return _date(d.get("end")), "Fälligkeit"
    if account.kind == "altersvorsorge" and _date(d.get("payout_start")):
        return _date(d.get("payout_start")), "Rentenbeginn"
    if _date(d.get("free_from")):
        return _date(d.get("free_from")), "frei ab"
    return None, None


def liquidity(db: Session, person_id: int | None = None, on: date | None = None) -> dict:
    on = on or date.today()
    scope = Scope(person_id=person_id)
    from .cashflow import role_of

    available = bound = liabilities = ZERO
    current = invested = ZERO  # available split: everyday accounts vs. invested (call money, depots, crypto …)
    items = []
    for account in db.scalars(select(Account).where(Account.closed.is_(False)).order_by(Account.name)).all():
        share = scope.share(account)
        if share <= 0:
            continue
        value = (account_value(db, account, on).value * share).quantize(Decimal("0.01"))
        if value == 0:
            continue
        kind = kinds.KINDS.get(account.kind)
        if kind and kind.liability and kind.mode == kinds.LOAN:
            bucket = "liability"
            liabilities += value
        elif is_bound(account):
            bucket = "bound"
            bound += value
        else:
            bucket = "available"  # incl. credit cards, which reduce what is available
            available += value
            if role_of(account) == "spending":
                current += value
            else:
                invested += value
        when, why = free_from(account) if bucket == "bound" else (None, None)
        if when is not None and when <= on:
            when, why = None, None  # already due
        items.append(
            {
                "account_id": account.id,
                "name": account.name,
                "kind": account.kind,
                "kind_label": kind.label if kind else account.kind,
                "value": value,
                "bucket": bucket,
                "group": ("current" if role_of(account) == "spending" else "invested") if bucket == "available" else bucket,
                "automatic": (account.details or {}).get("liquidity") not in ("available", "bound"),
                "free_from": when,
                "free_reason": why,
            }
        )
    items.sort(key=lambda i: (i["bucket"], i["free_from"] or date.max, -abs(i["value"])))
    assets = available + bound
    return {
        "as_of": on,
        "available": available,
        "current": current,
        "invested": invested,
        "bound": bound,
        "liabilities": liabilities,
        "net": available + bound + liabilities,
        "available_share": available / assets if assets > 0 else None,
        "items": items,
    }
