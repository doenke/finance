"""Parsing of CSV exports: generic bank bookings and Portfolio Performance transactions."""

from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

DATE_FORMATS = ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y", "%d/%m/%Y", "%m/%d/%Y", "%Y%m%d")


class ImportError_(Exception):
    pass


def sniff(text: str) -> tuple[str, list[list[str]]]:
    """Detect the delimiter and return all rows (bank exports often have preamble lines)."""
    sample = "\n".join(text.splitlines()[:50])
    counts = {d: sample.count(d) for d in (";", ",", "\t", "|")}
    delimiter = max(counts, key=counts.get) if any(counts.values()) else ";"
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=delimiter) if any(c.strip() for c in r)]
    return delimiter, rows


def header_index(rows: list[list[str]]) -> int:
    """Index of the header row: the first row with the most columns among the first 30 rows."""
    if not rows:
        return 0
    widest = max(len(r) for r in rows[:30])
    for i, r in enumerate(rows[:30]):
        if len(r) == widest and sum(1 for c in r if c.strip()) >= max(2, widest // 2):
            return i
    return 0


def parse_decimal(value: str) -> Decimal:
    s = value.strip().replace(" ", "").replace(" ", "").replace("€", "").replace("EUR", "")
    negative = s.endswith("-") or (s.startswith("(") and s.endswith(")"))
    s = s.strip("()-+") if negative else s.lstrip("+")
    if s.startswith("-"):
        negative, s = True, s[1:]
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    try:
        result = Decimal(s)
    except InvalidOperation as exc:
        raise ImportError_(f"„{value}“ ist keine Zahl") from exc
    return -result if negative else result


def parse_date(value: str, fmt: str | None = None) -> date:
    v = value.strip()
    candidates = [v, v[:10], v[:8]]
    for f in [fmt] if fmt else DATE_FORMATS:
        for c in candidates:
            try:
                return datetime.strptime(c, f).date()
            except (ValueError, TypeError):
                continue
    raise ImportError_(f"„{value}“ ist kein Datum")


GUESS = {
    "booking_date": ["buchungstag", "buchungsdatum", "buchung", "datum", "date", "booking date"],
    "value_date": ["valuta", "wertstellung", "valutadatum", "value date"],
    "amount": ["betrag", "umsatz", "amount", "betrag (€)", "betrag (eur)", "betrag in eur"],
    "counterparty": ["beguenstigter/zahlungspflichtiger", "begünstigter/zahlungspflichtiger", "empfänger", "zahlungsempfänger*in", "name zahlungsbeteiligter", "auftraggeber / begünstigter", "gegenpartei", "name", "payee", "beschreibung"],
    "purpose": ["verwendungszweck", "buchungstext", "purpose", "zweck", "description", "umsatzbeschreibung"],
}


def guess_mapping(header: list[str]) -> dict[str, int | None]:
    lower = [h.strip().lower() for h in header]
    mapping: dict[str, int | None] = {}
    for key, names in GUESS.items():
        idx = next((lower.index(n) for n in names if n in lower), None)
        if idx is None:
            idx = next((i for i, h in enumerate(lower) for n in names if n in h and i not in mapping.values()), None)
        mapping[key] = idx
    return mapping


@dataclass
class ParsedBooking:
    line: int
    booking_date: date | None = None
    value_date: date | None = None
    amount: Decimal | None = None
    counterparty: str = ""
    purpose: str = ""
    error: str = ""
    external_id: str = ""
    raw: dict = field(default_factory=dict)


def booking_id(account_id: int, b: "ParsedBooking", occurrence: int) -> str:
    key = f"{account_id}|{b.booking_date}|{b.amount}|{b.counterparty.strip().lower()}|{b.purpose.strip().lower()}|{occurrence}"
    return "csv:" + hashlib.sha1(key.encode()).hexdigest()[:24]


def parse_bookings(text: str, mapping: dict[str, int | None], account_id: int, date_format: str | None = None) -> tuple[list[str], list[ParsedBooking]]:
    _, rows = sniff(text)
    h = header_index(rows)
    header = rows[h] if rows else []
    result: list[ParsedBooking] = []
    seen: dict[tuple, int] = {}

    def col(row: list[str], key: str) -> str:
        i = mapping.get(key)
        return row[i].strip() if i is not None and i < len(row) else ""

    for n, row in enumerate(rows[h + 1 :], start=h + 2):
        b = ParsedBooking(line=n, raw={header[i] if i < len(header) else str(i): v for i, v in enumerate(row)})
        try:
            if not col(row, "booking_date") and not col(row, "amount"):
                continue
            b.booking_date = parse_date(col(row, "booking_date"), date_format)
            if col(row, "value_date"):
                try:
                    b.value_date = parse_date(col(row, "value_date"), date_format)
                except ImportError_:
                    b.value_date = None
            b.amount = parse_decimal(col(row, "amount"))
            b.counterparty = col(row, "counterparty")[:255]
            b.purpose = col(row, "purpose")
            key = (b.booking_date, b.amount, b.counterparty.lower(), b.purpose.lower())
            seen[key] = seen.get(key, 0) + 1
            b.external_id = booking_id(account_id, b, seen[key])
        except ImportError_ as exc:
            b.error = str(exc)
        result.append(b)
    return header, result


# --- Portfolio Performance ------------------------------------------------------------------------

PP_TYPES = {
    "kauf": "buy",
    "buy": "buy",
    "verkauf": "sell",
    "sell": "sell",
    "einlieferung": "deliver_in",
    "delivery (inbound)": "deliver_in",
    "auslieferung": "deliver_out",
    "delivery (outbound)": "deliver_out",
    "dividende": "dividend",
    "dividend": "dividend",
    "zinsen": "interest",
    "interest": "interest",
    "steuern": "tax",
    "taxes": "tax",
    "steuerrückerstattung": "tax_refund",
    "tax refund": "tax_refund",
    "gebühren": "fee",
    "fees": "fee",
}


@dataclass
class ParsedTrade:
    line: int
    date: date | None = None
    type: str = ""
    isin: str = ""
    wkn: str = ""
    symbol: str = ""
    name: str = ""
    quantity: Decimal = Decimal("0")
    amount: Decimal = Decimal("0")
    fees: Decimal = Decimal("0")
    taxes: Decimal = Decimal("0")
    currency: str = "EUR"
    note: str = ""
    error: str = ""
    skipped: str = ""
    external_id: str = ""


def _find(header: list[str], *names: str) -> int | None:
    lower = [h.strip().lower() for h in header]
    for n in names:
        if n in lower:
            return lower.index(n)
    return None


def parse_portfolio_performance(text: str, account_id: int) -> list[ParsedTrade]:
    """CSV export of 'Alle Buchungen' / account transactions from Portfolio Performance (German or English)."""
    _, rows = sniff(text)
    h = header_index(rows)
    header = rows[h] if rows else []
    c = {
        "date": _find(header, "datum", "date"),
        "type": _find(header, "typ", "type"),
        "value": _find(header, "wert", "value"),
        "gross": _find(header, "bruttobetrag", "gross amount"),
        "fees": _find(header, "gebühren", "fees"),
        "taxes": _find(header, "steuern", "taxes"),
        "shares": _find(header, "stück", "shares"),
        "isin": _find(header, "isin"),
        "wkn": _find(header, "wkn"),
        "symbol": _find(header, "ticker-symbol", "ticker symbol", "symbol"),
        "name": _find(header, "wertpapiername", "security name", "wertpapier", "security"),
        "currency": _find(header, "buchungswährung", "transaction currency", "währung"),
        "note": _find(header, "notiz", "note"),
    }
    if c["date"] is None or c["type"] is None or c["value"] is None:
        raise ImportError_("Das sieht nicht nach einem Export aus Portfolio Performance aus (Spalten Datum, Typ, Wert fehlen).")
    result: list[ParsedTrade] = []
    seen: dict[tuple, int] = {}

    def get(row: list[str], key: str) -> str:
        i = c[key]
        return row[i].strip() if i is not None and i < len(row) else ""

    for n, row in enumerate(rows[h + 1 :], start=h + 2):
        t = ParsedTrade(line=n)
        try:
            t.date = parse_date(get(row, "date")[:10])
            raw_type = get(row, "type").lower()
            t.type = PP_TYPES.get(raw_type, "")
            if not t.type:
                t.skipped = f"„{get(row, 'type')}“ wird nicht übernommen (Kontobuchung)"
            value = abs(parse_decimal(get(row, "value"))) if get(row, "value") else Decimal("0")
            t.fees = abs(parse_decimal(get(row, "fees"))) if get(row, "fees") else Decimal("0")
            t.taxes = abs(parse_decimal(get(row, "taxes"))) if get(row, "taxes") else Decimal("0")
            t.quantity = abs(parse_decimal(get(row, "shares"))) if get(row, "shares") else Decimal("0")
            gross = abs(parse_decimal(get(row, "gross"))) if get(row, "gross") else None
            # PP "Wert" is the net cash amount; derive the gross amount for our model.
            if t.type == "buy":
                t.amount = gross if gross is not None else value - t.fees - t.taxes
            elif t.type in ("sell", "dividend", "interest"):
                t.amount = gross if gross is not None else value + t.fees + t.taxes
            else:
                t.amount = gross if gross is not None else value
            t.isin = get(row, "isin").upper()
            t.wkn = get(row, "wkn").upper()
            t.symbol = get(row, "symbol").upper()
            t.name = get(row, "name")
            t.currency = (get(row, "currency") or "EUR").upper()
            t.note = get(row, "note")
            if t.type in ("buy", "sell", "deliver_in", "deliver_out", "dividend") and not (t.isin or t.name):
                t.error = "Wertpapier fehlt"
            if t.currency != "EUR" and not t.skipped:
                t.error = f"Nur Euro-Buchungen werden übernommen ({t.currency})"
            key = (t.date, t.type, t.isin or t.name, t.quantity, t.amount)
            seen[key] = seen.get(key, 0) + 1
            t.external_id = "pp:" + hashlib.sha1(f"{account_id}|{key}|{seen[key]}".encode()).hexdigest()[:24]
        except ImportError_ as exc:
            t.error = str(exc)
        result.append(t)
    return result
