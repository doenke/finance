"""Categories and recurring payments (contracts, subscriptions, salary) with an overview."""

import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..auth.session import current_user
from ..db import get_db
from ..models import Account, Category, CategoryRule, RecurringPayment, Transaction
from ..services import recurring as rec

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])
ZERO = Decimal("0")
# transfer = savings (counted as savings rate); internal = between own accounts (not counted at all)
CATEGORY_KINDS = ("expense", "income", "transfer", "internal")


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: str = "expense"


class RecurringIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    match_key: str = Field(min_length=1, max_length=200)
    direction: str = Field(pattern="^(in|out)$")
    interval: str
    amount_min: Decimal | None = None
    amount_max: Decimal | None = None
    category_id: int | None = None
    status: str = "active"


class RecurringUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    interval: str
    category_id: int | None = None
    status: str = "active"
    note: str = Field(default="", max_length=2000)


def _check(db: Session, interval: str, status: str, category_id: int | None) -> None:
    if interval not in rec.INTERVALS:
        raise HTTPException(422, "Unbekanntes Intervall")
    if status not in ("active", "ended", "ignored"):
        raise HTTPException(422, "Unbekannter Status")
    if category_id is not None and db.get(Category, category_id) is None:
        raise HTTPException(422, "Unbekannte Kategorie")


def _categories(db: Session) -> list[Category]:
    return list(db.scalars(select(Category).order_by(Category.sort, Category.name)).all())


# --- categories ------------------------------------------------------------------------------------


@router.get("/categories")
def list_categories(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return [{"id": c.id, "name": c.name, "kind": c.kind} for c in _categories(db)]


@router.post("/categories", status_code=201)
def create_category(data: CategoryIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    if data.kind not in CATEGORY_KINDS:
        raise HTTPException(422, "Unbekannte Art")
    c = Category(name=data.name.strip(), kind=data.kind, sort=1000)
    db.add(c)
    db.commit()
    return {"id": c.id, "name": c.name, "kind": c.kind}


@router.put("/categories/{category_id}")
def update_category(category_id: int, data: CategoryIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    c = db.get(Category, category_id)
    if c is None:
        raise HTTPException(404, "Kategorie nicht gefunden")
    if data.kind not in CATEGORY_KINDS:
        raise HTTPException(422, "Unbekannte Art")
    c.name, c.kind = data.name.strip(), data.kind
    db.commit()
    return {"id": c.id, "name": c.name, "kind": c.kind}


@router.delete("/categories/{category_id}", status_code=204)
def delete_category(category_id: int, db: Session = Depends(get_db)) -> Response:
    c = db.get(Category, category_id)
    if c is None:
        raise HTTPException(404, "Kategorie nicht gefunden")
    db.delete(c)  # transactions and recurring payments keep no category (ON DELETE SET NULL)
    db.commit()
    return Response(status_code=204)


# --- overview --------------------------------------------------------------------------------------


def _assign(rules: list[RecurringPayment], txs: list[rec.Tx]) -> tuple[dict[int, list[rec.Tx]], list[rec.Tx]]:
    # Rules with an amount range are more specific and win.
    # Specific rules win: with an amount range, then payee + purpose, then payee only.
    ordered = sorted(rules, key=lambda r: (r.amount_min is None, "|" not in r.match_key, r.id))
    by_rule: dict[int, list[rec.Tx]] = {r.id: [] for r in rules}
    free: list[rec.Tx] = []
    for t in txs:
        rule = next((r for r in ordered if rec.matches(r, t)), None)
        if rule is None:
            free.append(t)
        else:
            by_rule[rule.id].append(t)
    return by_rule, free


def _apply_categories(db: Session, rules: list[RecurringPayment], by_rule: dict[int, list[rec.Tx]]) -> None:
    """Gives matched transactions without a category the category of their recurring payment."""
    changed = False
    for r in rules:
        if r.category_id is None or r.status == "ignored":
            continue
        ids = [t.id for t in by_rule[r.id] if t.category_id is None]
        if ids:
            db.execute(update(Transaction).where(Transaction.id.in_(ids)).values(category_id=r.category_id))
            for t in by_rule[r.id]:
                t.category_id = t.category_id or r.category_id
            changed = True
    if changed:
        db.commit()


def overview(db: Session, today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    txs = rec.load_transactions(db, today - timedelta(days=rec.LOOKBACK_DAYS))
    rules = list(db.scalars(select(RecurringPayment)).all())
    by_rule, free = _assign(rules, txs)
    _apply_categories(db, rules, by_rule)
    cats = {c.id: c for c in _categories(db)}
    accounts = {a.id: a.name for a in db.scalars(select(Account)).all()}
    ibans = rec.own_ibans(db)
    names_own = rec.own_names(db)
    iban_to_account = {re.sub(r"\s", "", a.iban).upper(): a.id for a in db.scalars(select(Account)).all() if a.iban}

    items = []
    for r in rules:
        if r.status == "ignored":
            continue
        info = rec.describe(by_rule[r.id], r.interval, today)
        cat = cats.get(r.category_id) if r.category_id else None
        items.append(
            {
                "id": r.id,
                "name": r.name,
                "direction": r.direction,
                "interval": r.interval,
                "interval_label": rec.INTERVAL_LABELS[r.interval],
                "status": r.status,
                "note": r.note,
                "category_id": r.category_id,
                "category": cat.name if cat else None,
                "category_kind": cat.kind if cat else ("income" if r.direction == "in" else "expense"),
                "account": accounts.get(info["account_id"]) if info["account_id"] else None,
                **info,
            }
        )
        if cat and cat.kind in ("internal", "transfer") and by_rule[r.id]:
            src, dst = rec.transfer_route(by_rule[r.id], txs, iban_to_account)
            if src is not None or dst is not None:
                items[-1]["route"] = {"from": accounts.get(src) if src else None, "to": accounts.get(dst) if dst else None}

    suggestions = []
    for c in rec.detect(free, today):
        first = c.txs[-1]
        info = rec.describe(c.txs, c.interval, today)
        category_id = rec.suggest_category(db, first.counterparty, first.purpose, c.direction, ibans, names_own)
        suggestions.append(
            {
                "match_key": c.key,
                "direction": c.direction,
                "interval": c.interval,
                "interval_label": rec.INTERVAL_LABELS[c.interval],
                "amount_min": c.amount_min,
                "amount_max": c.amount_max,
                "name": rec.suggest_name(first.counterparty, first.purpose, c.key),
                "category_id": category_id,
                "example": first.purpose[:140],
                "account": accounts.get(info["account_id"]),
                **info,
            }
        )
    suggestions.sort(key=lambda s: s["monthly"], reverse=True)

    active = [i for i in items if i["status"] == "active"]
    summary = {"income": ZERO, "costs": ZERO, "savings": ZERO}
    by_category: dict[str, Decimal] = {}
    for i in active:
        kind = i["category_kind"]
        if kind == "internal":
            continue  # transfers between own accounts are neither income, costs nor savings
        if i["direction"] == "in":
            summary["income"] += i["monthly"] if kind != "transfer" else ZERO
        elif kind == "transfer":
            summary["savings"] += i["monthly"]
        else:
            summary["costs"] += i["monthly"]
            label = i["category"] or "Ohne Kategorie"
            by_category[label] = by_category.get(label, ZERO) + i["monthly"]
    summary["free"] = summary["income"] - summary["costs"] - summary["savings"]
    upcoming = sorted(
        ({"id": i["id"], "name": i["name"], "date": i["next_date"], "amount": i["amount"], "direction": i["direction"], "overdue": i["overdue"]} for i in active if i["next_date"] and i["next_date"] <= today + timedelta(days=30) and i["category_kind"] != "internal"),
        key=lambda u: u["date"],
    )
    items.sort(key=lambda i: (i["status"] != "active", i["direction"] == "in", -i["monthly"]))
    return {
        "as_of": today,
        "summary": summary,
        "by_category": [{"name": k, "monthly": v} for k, v in sorted(by_category.items(), key=lambda kv: kv[1], reverse=True)],
        "items": items,
        "suggestions": suggestions,
        "upcoming": upcoming,
        "categories": [{"id": c.id, "name": c.name, "kind": c.kind} for c in cats.values()],
        "intervals": [{"key": k, "label": v} for k, v in rec.INTERVAL_LABELS.items()],
        "has_transactions": bool(txs),
    }


class RuleIn(BaseModel):
    pattern: str = Field(min_length=2, max_length=120)
    field: str = "any"
    direction: str = "out"
    account_id: int | None = None
    category_id: int | None = None  # required when saving, not for a preview


def _check_rule(db: Session, data: RuleIn, need_category: bool = True) -> None:
    if data.field not in ("any", "counterparty", "purpose"):
        raise HTTPException(422, "Unbekanntes Feld")
    if data.direction not in ("any", "in", "out"):
        raise HTTPException(422, "Unbekannte Richtung")
    if data.account_id is not None and db.get(Account, data.account_id) is None:
        raise HTTPException(422, "Unbekanntes Konto")
    if need_category and (data.category_id is None or db.get(Category, data.category_id) is None):
        raise HTTPException(422, "Bitte eine Kategorie wählen")


def _rule_txs(db: Session) -> list[rec.Tx]:
    return rec.load_transactions(db, date.today() - timedelta(days=rec.LOOKBACK_DAYS))


def _rule_out(r: CategoryRule, cats: dict[int, Category], txs: list[rec.Tx]) -> dict[str, Any]:
    from ..services.categorize import Rule, rule_matches

    rule = Rule(r.id, r.pattern.strip().lower(), r.field, r.direction, r.account_id, r.category_id)
    hits = [t for t in txs if rule_matches(rule, t.counterparty, t.purpose, t.amount, t.account_id)]
    return {
        "id": r.id,
        "pattern": r.pattern,
        "field": r.field,
        "direction": r.direction,
        "account_id": r.account_id,
        "category_id": r.category_id,
        "category": cats[r.category_id].name if r.category_id in cats else None,
        "count": len(hits),
        "total": sum((abs(t.amount) for t in hits), ZERO),
    }


@router.get("/category-rules")
def list_rules(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    cats = {c.id: c for c in _categories(db)}
    txs = _rule_txs(db)
    rows = sorted(db.scalars(select(CategoryRule)).all(), key=lambda r: (r.sort, -len(r.pattern), r.id))
    return [_rule_out(r, cats, txs) for r in rows]


@router.post("/category-rules/preview")
def preview_rule(data: RuleIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    from ..services.categorize import Categorizer, Rule, rule_matches

    _check_rule(db, data, need_category=False)
    rule = Rule(0, data.pattern.strip().lower(), data.field, data.direction, data.account_id, data.category_id or 0)
    categorize = Categorizer(db)
    accounts = {a.id: a.name for a in db.scalars(select(Account)).all()}
    hits = sorted((t for t in _rule_txs(db) if rule_matches(rule, t.counterparty, t.purpose, t.amount, t.account_id)), key=lambda t: t.date, reverse=True)
    examples = []
    for t in hits[:8]:
        cat, source = categorize(t)
        examples.append(
            {
                "date": t.date,
                "amount": t.amount,
                "counterparty": t.counterparty,
                "purpose": t.purpose[:100],
                "account": accounts.get(t.account_id),
                "current": cat.name if cat else None,
                "fixed": source == "fixed",  # set by a contract; a rule does not change it
            }
        )
    return {"count": len(hits), "total": sum((abs(t.amount) for t in hits), ZERO), "fixed": sum(1 for t in hits if t.category_id is not None), "examples": examples}


@router.post("/category-rules", status_code=201)
def create_rule(data: RuleIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    _check_rule(db, data)
    r = CategoryRule(pattern=data.pattern.strip(), field=data.field, direction=data.direction, account_id=data.account_id, category_id=data.category_id)
    db.add(r)
    db.commit()
    return _rule_out(r, {c.id: c for c in _categories(db)}, _rule_txs(db))


@router.put("/category-rules/{rule_id}")
def update_rule(rule_id: int, data: RuleIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    r = db.get(CategoryRule, rule_id)
    if r is None:
        raise HTTPException(404, "Regel nicht gefunden")
    _check_rule(db, data)
    r.pattern, r.field, r.direction, r.account_id, r.category_id = data.pattern.strip(), data.field, data.direction, data.account_id, data.category_id
    db.commit()
    return _rule_out(r, {c.id: c for c in _categories(db)}, _rule_txs(db))


@router.delete("/category-rules/{rule_id}", status_code=204)
def delete_rule(rule_id: int, db: Session = Depends(get_db)) -> Response:
    r = db.get(CategoryRule, rule_id)
    if r is None:
        raise HTTPException(404, "Regel nicht gefunden")
    db.delete(r)
    db.commit()
    return Response(status_code=204)


class FlowRoleIn(BaseModel):
    role: str | None = None  # spending | saving | None (automatic)


@router.get("/cashflow")
def get_cashflow(months: int = 12, month: str | None = None, db: Session = Depends(get_db)) -> dict[str, Any]:
    from ..services.cashflow import cashflow

    return cashflow(db, max(1, min(months, 36)), month)


@router.get("/flow-roles")
def list_flow_roles(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    from ..services.cashflow import role_of

    accounts = sorted(db.scalars(select(Account).where(Account.closed.is_(False))).all(), key=lambda a: a.name)
    return [
        {"id": a.id, "name": a.name, "kind": a.kind, "role": role_of(a), "automatic": (a.details or {}).get("flow_role") not in ("spending", "saving")}
        for a in accounts
        if role_of(a) is not None
    ]


@router.put("/accounts/{account_id}/flow-role")
def set_flow_role(account_id: int, data: FlowRoleIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    from ..services.cashflow import ROLES, role_of

    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(404, "Konto nicht gefunden")
    if data.role is not None and data.role not in ROLES:
        raise HTTPException(422, "Unbekannte Rolle")
    details = dict(account.details or {})
    if data.role is None:
        details.pop("flow_role", None)
    else:
        details["flow_role"] = data.role
    account.details = details
    db.commit()
    return {"id": account.id, "role": role_of(account), "automatic": data.role is None}


@router.get("/recurring")
def get_overview(db: Session = Depends(get_db)) -> dict[str, Any]:
    return overview(db)


@router.post("/recurring", status_code=201)
def create_recurring(data: RecurringIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    _check(db, data.interval, data.status, data.category_id)
    r = RecurringPayment(**data.model_dump())
    db.add(r)
    db.commit()
    return {"id": r.id}


@router.put("/recurring/{rec_id}")
def update_recurring(rec_id: int, data: RecurringUpdate, db: Session = Depends(get_db)) -> dict[str, Any]:
    r = db.get(RecurringPayment, rec_id)
    if r is None:
        raise HTTPException(404, "Nicht gefunden")
    _check(db, data.interval, data.status, data.category_id)
    if data.category_id != r.category_id:
        # move the transactions that carried the old category along
        txs = rec.load_transactions(db, date.today() - timedelta(days=rec.LOOKBACK_DAYS))
        ids = [t.id for t in txs if rec.matches(r, t) and t.category_id in (None, r.category_id)]
        if ids:
            db.execute(update(Transaction).where(Transaction.id.in_(ids)).values(category_id=data.category_id))
    r.name, r.interval, r.category_id, r.status, r.note = data.name.strip(), data.interval, data.category_id, data.status, data.note
    db.commit()
    return {"id": r.id}


@router.delete("/recurring/{rec_id}", status_code=204)
def delete_recurring(rec_id: int, db: Session = Depends(get_db)) -> Response:
    r = db.get(RecurringPayment, rec_id)
    if r is None:
        raise HTTPException(404, "Nicht gefunden")
    db.delete(r)
    db.commit()
    return Response(status_code=204)


@router.get("/recurring/{rec_id}/transactions")
def recurring_transactions(rec_id: int, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    r = db.get(RecurringPayment, rec_id)
    if r is None:
        raise HTTPException(404, "Nicht gefunden")
    txs = rec.load_transactions(db, date.today() - timedelta(days=rec.LOOKBACK_DAYS))
    rules = list(db.scalars(select(RecurringPayment)).all())
    by_rule, _ = _assign(rules, txs)
    accounts = {a.id: a.name for a in db.scalars(select(Account)).all()}
    return [
        {"id": t.id, "date": t.date, "amount": t.amount, "counterparty": t.counterparty, "purpose": t.purpose, "account": accounts.get(t.account_id)}
        for t in sorted(by_rule[r.id], key=lambda t: t.date, reverse=True)
    ]
