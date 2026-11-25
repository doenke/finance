"""Audit log: every state-changing action with user, time, channel (app or MCP), object and a short detail.

Writes from the web app are recorded by a middleware (see `main.py`) from the request path and a small,
whitelisted part of the JSON body. MCP tools record themselves. Secrets (PINs, TANs, user names at the bank,
push keys) are never recorded: only the fields in DETAIL_FIELDS are read.
"""

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session

from .. import kinds

from ..models import (
    Account,
    AuditEntry,
    Bank,
    BankLogin,
    Category,
    CategoryRule,
    ImportBatch,
    Instrument,
    OAuthClient,
    Person,
    RecurringPayment,
    Transaction,
    User,
    UserSession,
)

MAX_BODY = 64 * 1024

# (method, path regex) -> German label. The first match wins.
_ROUTES: list[tuple[str, str, str]] = [
    ("POST", r"/api/accounts", "Konto angelegt"),
    ("PUT", r"/api/accounts/\d+", "Konto geändert"),
    ("DELETE", r"/api/accounts/\d+", "Konto gelöscht"),
    ("POST", r"/api/accounts/\d+/balances", "Kontostand eingetragen"),
    ("DELETE", r"/api/accounts/\d+/balances/\d+", "Kontostand gelöscht"),
    ("POST", r"/api/accounts/\d+/transactions", "Buchung angelegt"),
    ("PUT", r"/api/accounts/\d+/transactions/\d+", "Buchung geändert"),
    ("DELETE", r"/api/accounts/\d+/transactions/\d+", "Buchung gelöscht"),
    ("POST", r"/api/accounts/\d+/valuations", "Bewertung eingetragen"),
    ("DELETE", r"/api/accounts/\d+/valuations/\d+", "Bewertung gelöscht"),
    ("POST", r"/api/accounts/\d+/trades", "Depot-Transaktion angelegt"),
    ("PUT", r"/api/accounts/\d+/trades/\d+", "Depot-Transaktion geändert"),
    ("DELETE", r"/api/accounts/\d+/trades/\d+", "Depot-Transaktion gelöscht"),
    ("PUT", r"/api/accounts/\d+/flow-role", "Rolle im Geldfluss geändert"),
    ("POST", r"/api/accounts/\d+/unlink", "Bankverknüpfung gelöst"),
    ("POST", r"/api/accounts/\d+/reconcile", "Kontostand abgeglichen"),
    ("POST", r"/api/instruments", "Wertpapier angelegt"),
    ("PUT", r"/api/instruments/\d+", "Wertpapier geändert"),
    ("POST", r"/api/instruments/\d+/prices", "Kurs eingetragen"),
    ("DELETE", r"/api/instruments/\d+/prices/\d+", "Kurs gelöscht"),
    ("POST", r"/api/categories", "Kategorie angelegt"),
    ("PUT", r"/api/categories/\d+", "Kategorie geändert"),
    ("DELETE", r"/api/categories/\d+", "Kategorie gelöscht"),
    ("PUT", r"/api/transactions/\d+/category", "Kategorie einer Buchung geändert"),
    ("POST", r"/api/category-rules", "Kategorieregel angelegt"),
    ("PUT", r"/api/category-rules/\d+", "Kategorieregel geändert"),
    ("DELETE", r"/api/category-rules/\d+", "Kategorieregel gelöscht"),
    ("POST", r"/api/recurring", "Vertrag angelegt"),
    ("PUT", r"/api/recurring/\d+", "Vertrag geändert"),
    ("DELETE", r"/api/recurring/\d+", "Vertrag gelöscht"),
    ("POST", r"/api/banks", "Bank angelegt"),
    ("PUT", r"/api/banks/\d+", "Bank geändert"),
    ("DELETE", r"/api/banks/\d+", "Bank gelöscht"),
    ("POST", r"/api/banks/\d+/logins", "Bankzugang angelegt"),
    ("PUT", r"/api/bank-logins/\d+", "Bankzugang geändert"),
    ("DELETE", r"/api/bank-logins/\d+", "Bankzugang gelöscht"),
    ("POST", r"/api/bank-logins/\d+/discover", "Konten bei der Bank abgefragt"),
    ("POST", r"/api/bank-logins/\d+/sync", "Bankabruf gestartet"),
    ("POST", r"/api/bank-logins/\d+/link", "Bankkonten verknüpft"),
    ("POST", r"/api/fints/jobs/[^/]+/cancel", "Bankabruf abgebrochen"),
    ("POST", r"/api/persons", "Person angelegt"),
    ("PUT", r"/api/persons/\d+", "Person geändert"),
    ("DELETE", r"/api/persons/\d+", "Person gelöscht"),
    ("POST", r"/api/prices/sync", "Kursabruf gestartet"),
    ("POST", r"/api/prices/switch-to-onvista", "Kursquelle auf onvista umgestellt"),
    ("POST", r"/api/prices/instruments/\d+", "Kurse eines Wertpapiers abgerufen"),
    ("POST", r"/api/import/bookings/commit", "Buchungen importiert"),
    ("POST", r"/api/import/portfolio-performance/commit", "Portfolio Performance importiert"),
    ("POST", r"/api/import/bsdex/commit", "BSDEX-Umsätze importiert"),
    ("DELETE", r"/api/import/batches/\d+", "Import rückgängig gemacht"),
    ("POST", r"/api/admin/backups", "Sicherung erstellt"),
    ("PUT", r"/api/notifications/prefs", "Benachrichtigungen geändert"),
    ("POST", r"/api/notifications/subscriptions", "Gerät für Push angemeldet"),
    ("POST", r"/api/notifications/subscriptions/remove", "Gerät für Push abgemeldet"),
    ("DELETE", r"/api/notifications/log", "Benachrichtigungsverlauf geleert"),
    ("DELETE", r"/api/mcp/clients/[^/]+", "Assistent getrennt"),
    ("DELETE", r"/api/sessions/\d+", "Gerät abgemeldet"),
    ("POST", r"/api/sessions/revoke-others", "Alle anderen Geräte abgemeldet"),
    ("POST", r"/api/admin/users/\d+/logout", "Benutzer überall abgemeldet"),
    ("PUT", r"/api/admin/users/\d+/disabled", "Benutzer gesperrt oder entsperrt"),
]
_COMPILED = [(m, re.compile(p + "$"), label) for m, p, label in _ROUTES]

# Requests that change nothing (previews, calculations) or carry secrets (TAN answers) are not recorded.
_SKIP = re.compile(r"(/preview$|/scenarios$|^/api/fints/jobs/[^/]+/answer$|^/api/notifications/test$)")

# Object referenced in the path -> how to name it.
_TARGETS: list[tuple[re.Pattern, type, str, str]] = [
    (re.compile(r"^/api/accounts/(\d+)"), Account, "name", "Konto"),
    (re.compile(r"^/api/(?:prices/)?instruments/(\d+)"), Instrument, "name", "Wertpapier"),
    (re.compile(r"^/api/persons/(\d+)"), Person, "name", "Person"),
    (re.compile(r"^/api/banks/(\d+)"), Bank, "name", "Bank"),
    (re.compile(r"^/api/bank-logins/(\d+)"), BankLogin, "name", "Bankzugang"),
    (re.compile(r"^/api/categories/(\d+)"), Category, "name", "Kategorie"),
    (re.compile(r"^/api/category-rules/(\d+)"), CategoryRule, "pattern", "Regel"),
    (re.compile(r"^/api/recurring/(\d+)"), RecurringPayment, "name", "Vertrag"),
    (re.compile(r"^/api/transactions/(\d+)"), Transaction, "counterparty", "Buchung"),
    (re.compile(r"^/api/import/batches/(\d+)"), ImportBatch, "filename", "Import"),
    (re.compile(r"^/api/admin/users/(\d+)"), User, "name", "Benutzer"),
    (re.compile(r"^/api/sessions/(\d+)"), UserSession, "user_agent", "Gerät"),
]
_MCP_CLIENT = re.compile(r"^/api/mcp/clients/([^/]+)$")

# Only these body fields end up in the log, in this order.
DETAIL_FIELDS = ["name", "pattern", "date", "booking_date", "type", "kind", "amount", "value", "quantity", "price", "counterparty", "purpose", "filename"]


def label(method: str, path: str) -> str | None:
    """German label for a state-changing API request, or None if it is not recorded."""
    if _SKIP.search(path):
        return None
    for m, pattern, text in _COMPILED:
        if m == method and pattern.match(path):
            return text
    return f"{method} {path}"


def target(db: Session, path: str) -> str:
    """Names the object a path refers to, e.g. 'Konto Girokonto'. Call before the request runs (deletes)."""
    match = _MCP_CLIENT.match(path)
    if match:
        client = db.get(OAuthClient, match.group(1))
        return f"Assistent {client.name}" if client else "Assistent"
    for pattern, model, attr, noun in _TARGETS:
        match = pattern.match(path)
        if match:
            obj = db.get(model, int(match.group(1)))
            name = str(getattr(obj, attr) or "") if obj is not None else ""
            return f"{noun} {name}".strip() if name else f"{noun} #{match.group(1)}"
    return ""


def _fmt(value: Any) -> str:
    if isinstance(value, bool):
        return "ja" if value else "nein"
    text = str(value)
    if re.fullmatch(r"-?\d+\.\d+", text):
        try:
            # German number format: 1.234,56
            return f"{Decimal(text):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        except InvalidOperation:
            pass
    return text


def detail(data: Any) -> str:
    """Short summary from whitelisted fields of a JSON object (request body or MCP arguments)."""
    if not isinstance(data, dict):
        return ""
    parts = []
    for key in DETAIL_FIELDS:
        value = data.get(key)
        if value is None or value == "" or isinstance(value, (dict, list)):
            continue
        if key == "kind" and isinstance(value, str):
            value = kinds.KINDS[value].label if value in kinds.KINDS else kinds.TRANSACTION_KINDS.get(value, value)
        elif key == "type" and isinstance(value, str):
            value = kinds.TRADE_TYPES.get(value, value)
        parts.append(_fmt(value)[:120])
    return " · ".join(parts)[:500]


def detail_from_body(body: bytes) -> str:
    if not body or len(body) > MAX_BODY:
        return ""
    try:
        return detail(json.loads(body))
    except ValueError:
        return ""


def record(
    db: Session,
    *,
    user_id: int | None,
    actor: str,
    action: str,
    via: str = "app",
    client: str = "",
    target: str = "",
    detail: str = "",
) -> None:
    """Adds an audit entry; the caller commits."""
    db.add(AuditEntry(user_id=user_id, actor=actor[:255], via=via, client=client[:200], action=action[:120], target=target[:255], detail=detail[:500]))
