"""Guesses the kind of a bank booking from its texts (used by CSV import, FinTS and a data migration)."""

import re
from decimal import Decimal

# Credit interest: "Zinsen für Guthaben", "Haben-Zins", "Habenzinsen", "Zinsgutschrift", "Zinszahlung" (Trade Republic) …
INTEREST = re.compile(r"zinsen f(ü|ue)r guthaben|haben-?zins|guthabenzins|zinsgutschrift|zinszahlung|zinsertrag|\binterest\b", re.IGNORECASE)


def guess_kind(counterparty: str, purpose: str, amount: Decimal, posting_text: str = "") -> str:
    """'interest' for credited interest, else 'other'. Debits are never interest income."""
    if amount <= 0:
        return "other"
    if "zins" in (posting_text or "").lower():
        return "interest"
    if INTEREST.search(f"{counterparty or ''} {purpose or ''}"):
        return "interest"
    return "other"
