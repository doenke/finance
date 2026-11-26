"""Matching bank bookings from different sources (CSV import vs. FinTS) to avoid duplicates.

Two bookings are the same when they are on the same account, have the same amount, are at most
three days apart (booking vs. value date differ between sources) and share a word of the payee
or the purpose (or both have none). Each booking matches at most one other.
"""

import re
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Transaction

WINDOW = timedelta(days=3)
_WORD = re.compile(r"[a-zäöüß0-9]{3,}")
_NOISE = {"und", "der", "die", "das", "gmbh", "sagt", "danke", "herr", "frau", "sepa", "eref", "mref", "cred", "svwz", "abwa", "iban", "bic"}


def words(*texts: str) -> set[str]:
    return {w for t in texts for w in _WORD.findall((t or "").lower()) if w not in _NOISE}


def similar(a_cp: str, a_purpose: str, b_cp: str, b_purpose: str) -> bool:
    wa, wb = words(a_cp, a_purpose), words(b_cp, b_purpose)
    if not wa and not wb:
        return True
    return bool(wa & wb)


def find_twin(candidates: list[Transaction], used: set[int], day, amount: Decimal, counterparty: str, purpose: str) -> Transaction | None:
    for t in candidates:
        if t.id in used or t.amount != amount or abs(t.booking_date - day) > WINDOW:
            continue
        if similar(t.counterparty or "", t.purpose or "", counterparty, purpose):
            return t
    return None


def remove_fints_duplicates(db: Session, account_id: int | None = None) -> int:
    """Deletes bookings fetched via FinTS that already exist from another source (e.g. a CSV import)."""
    stmt = select(Transaction).where(Transaction.external_id.like("fints:%"))
    if account_id is not None:
        stmt = stmt.where(Transaction.account_id == account_id)
    fetched = db.scalars(stmt.order_by(Transaction.booking_date)).all()
    removed = 0
    by_account: dict[int, list[Transaction]] = {}
    for t in fetched:
        by_account.setdefault(t.account_id, []).append(t)
    for acc_id, rows in by_account.items():
        lo, hi = rows[0].booking_date - WINDOW, rows[-1].booking_date + WINDOW
        others = db.scalars(
            select(Transaction).where(
                Transaction.account_id == acc_id,
                Transaction.booking_date >= lo,
                Transaction.booking_date <= hi,
                (Transaction.external_id.is_(None)) | (~Transaction.external_id.like("fints:%")),
            )
        ).all()
        used: set[int] = set()
        for t in rows:
            twin = find_twin(others, used, t.booking_date, t.amount, t.counterparty or "", t.purpose or "")
            if twin is not None:
                used.add(twin.id)
                if twin.category_id is None and t.category_id is not None:
                    twin.category_id = t.category_id
                db.delete(t)
                removed += 1
    return removed
