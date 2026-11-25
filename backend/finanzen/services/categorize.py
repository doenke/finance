"""Categorising bookings: user rules first, then built-in keywords. Categories set elsewhere (recurring) win."""

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Category, CategoryRule
from . import recurring as rec


@dataclass(frozen=True)
class Rule:
    id: int
    pattern: str
    field: str
    direction: str
    account_id: int | None
    category_id: int


def load_rules(db: Session) -> list[Rule]:
    rows = db.scalars(select(CategoryRule)).all()
    # explicit order first, then the more specific (longer) pattern
    rows = sorted(rows, key=lambda r: (r.sort, -len(r.pattern), r.id))
    return [Rule(r.id, r.pattern.strip().lower(), r.field, r.direction, r.account_id, r.category_id) for r in rows if r.pattern.strip()]


def rule_matches(rule: Rule, counterparty: str, purpose: str, amount, account_id: int) -> bool:
    if rule.account_id is not None and rule.account_id != account_id:
        return False
    if rule.direction == "in" and amount <= 0 or rule.direction == "out" and amount >= 0:
        return False
    if rule.field == "counterparty":
        text = counterparty
    elif rule.field == "purpose":
        text = purpose
    else:
        text = f"{counterparty} {purpose}"
    return rule.pattern in text.lower()


class Categorizer:
    """Finds the category of a booking: own category > user rule > built-in keyword rule."""

    def __init__(self, db: Session) -> None:
        self.categories = {c.id: c for c in db.scalars(select(Category)).all()}
        self.by_name = {c.name: c for c in self.categories.values()}
        self.rules = load_rules(db)

    def __call__(self, t: rec.Tx) -> tuple[Category | None, str | None]:
        if t.category_id in self.categories:
            return self.categories[t.category_id], "fixed"
        for rule in self.rules:
            if rule_matches(rule, t.counterparty, t.purpose, t.amount, t.account_id):
                return self.categories.get(rule.category_id), "rule"
        text = f"{t.counterparty} {t.purpose}".lower()
        for name, direction, words in rec.RULES:
            if direction and direction != t.direction:
                continue
            if name in self.by_name and any(re.search(rf"(?<![a-zäöü]){re.escape(w)}", text) for w in words):
                return self.by_name[name], "keyword"
        return None, None


def suggest_pattern(counterparty: str, purpose: str) -> str:
    """A short pattern for a new rule: the payee's first meaningful word, or the merchant behind PayPal & Co."""
    words = rec._words(counterparty or "")
    if words and not any(p in " ".join(words) for p in rec.PROCESSORS):
        return words[0]
    merchant = rec._words(purpose or "", min_len=3)
    return merchant[0] if merchant else (words[0] if words else "")
