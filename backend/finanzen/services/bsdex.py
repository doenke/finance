"""Import of the BSDEX (Börse Stuttgart Digital Exchange) transaction export.

The export has duplicate and partly misleading column names (e.g. the executed crypto amount sits
under "Ausgeführter Gesamtbetrag"), so values are identified by their unit ("BTC", "€") instead of
by column name. Only executed orders are imported; rejected or cancelled orders are skipped.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .csvimport import ImportError_, parse_date, parse_decimal

# Yahoo symbols for common coins (EUR quotes)
COINS = {
    "bitcoin": ("BTC", "BTC-EUR"),
    "ethereum": ("ETH", "ETH-EUR"),
    "litecoin": ("LTC", "LTC-EUR"),
    "bitcoin cash": ("BCH", "BCH-EUR"),
    "xrp": ("XRP", "XRP-EUR"),
    "ripple": ("XRP", "XRP-EUR"),
    "cardano": ("ADA", "ADA-EUR"),
    "polkadot": ("DOT", "DOT-EUR"),
    "solana": ("SOL", "SOL-EUR"),
    "chainlink": ("LINK", "LINK-EUR"),
    "dogecoin": ("DOGE", "DOGE-EUR"),
    "avalanche": ("AVAX", "AVAX-EUR"),
    "polygon": ("MATIC", "MATIC-EUR"),
    "stellar": ("XLM", "XLM-EUR"),
    "uniswap": ("UNI", "UNI-EUR"),
    "tezos": ("XTZ", "XTZ-EUR"),
}

UNIT = re.compile(r"^\s*([-+]?[\d.,]+)\s*([A-Za-z€]+)\s*$")


@dataclass
class BsdexRow:
    line: int
    date: date | None = None
    kind: str = ""  # buy | sell | deposit | withdrawal
    coin: str = ""
    symbol: str = ""
    quantity: Decimal = Decimal("0")
    price: Decimal | None = None
    amount: Decimal = Decimal("0")  # EUR value of the order (without fee) or of the deposit
    fee: Decimal = Decimal("0")
    skipped: str = ""
    error: str = ""
    external_id: str = ""


def _split(value: str) -> tuple[Decimal, str] | None:
    m = UNIT.match(value or "")
    if not m:
        return None
    try:
        return parse_decimal(m.group(1)), m.group(2)
    except ImportError_:
        return None


def _euro(value: str) -> Decimal | None:
    parts = _split(value)
    return parts[0] if parts and parts[1] in ("€", "EUR") else None


def is_bsdex(text: str) -> bool:
    head = text.lstrip("﻿").splitlines()[0] if text.strip() else ""
    return "Kryptowährung" in head and "Ausführungspreis" in head and "Transaktionsentgelt" in head


def parse_bsdex(text: str, account_id: int) -> list[BsdexRow]:
    text = text.lstrip("﻿")
    if not is_bsdex(text):
        raise ImportError_("Das sieht nicht nach einem BSDEX-Export aus (Spalten Kryptowährung, Ausführungspreis, Transaktionsentgelt fehlen).")
    rows = list(csv.reader(io.StringIO(text), delimiter=","))
    header = [h.strip() for h in rows[0]]

    def idx(name: str, nth: int = 0) -> int | None:
        hits = [i for i, h in enumerate(header) if h == name]
        return hits[nth] if len(hits) > nth else None

    c_type, c_coin, c_side = idx("Transaktionstyp"), idx("Kryptowährung"), idx("Seite")
    c_price, c_status, c_fee = idx("Ausführungspreis"), idx("Status"), idx("Transaktionsentgelt")
    c_created, c_final, c_amount = idx("Erstellt"), idx("Finalisiert am"), idx("Betrag")
    c_completed = idx("Completed At")
    value_cols = [i for i in (idx("Gefüllt"), idx("Ausgeführter Gesamtbetrag"), idx("Ausgeführte Menge")) if i is not None]

    def get(row: list[str], i: int | None) -> str:
        return row[i].strip() if i is not None and i < len(row) else ""

    result: list[BsdexRow] = []
    seen: dict[tuple, int] = {}
    for n, row in enumerate(rows[1:], start=2):
        if not any(c.strip() for c in row):
            continue
        r = BsdexRow(line=n)
        try:
            ttype = get(row, c_type).lower()
            when = get(row, c_final) or get(row, c_completed) or get(row, c_created)
            r.date = parse_date(when.split(",")[0]) if when else None
            if ttype.startswith("einzahlung") or ttype.startswith("auszahlung"):
                amount = _euro(get(row, c_amount))
                if amount is None:
                    r.skipped = "Krypto-Ein- oder -Auszahlung – bitte von Hand erfassen"
                else:
                    r.kind = "deposit" if ttype.startswith("einzahlung") else "withdrawal"
                    r.amount = abs(amount)
            elif get(row, c_side):
                side = get(row, c_side).lower()
                status = get(row, c_status).lower()
                if status != "ausgeführt":
                    r.skipped = f"Order {(get(row, c_status) or 'ohne Status').lower()}"
                else:
                    r.kind = "buy" if side.startswith("kauf") else "sell" if side.startswith("verkauf") else ""
                    if not r.kind:
                        raise ImportError_(f"Unbekannte Seite „{get(row, c_side)}“")
                    coin = get(row, c_coin)
                    r.coin = coin
                    r.symbol = COINS.get(coin.lower(), (coin.upper()[:6], None))[0]
                    eur_values, qty_values = [], []
                    for i in value_cols:
                        parts = _split(get(row, i))
                        if parts and parts[0]:
                            (eur_values if parts[1] in ("€", "EUR") else qty_values).append(abs(parts[0]))
                    if not qty_values or not eur_values:
                        raise ImportError_("Menge oder Betrag der Order fehlt")
                    r.quantity = qty_values[0]
                    r.amount = eur_values[0]
                    r.price = _euro(get(row, c_price)) or (r.amount / r.quantity)
                    r.fee = abs(_euro(get(row, c_fee)) or Decimal("0"))
            else:
                r.skipped = f"„{get(row, c_type)}“ wird nicht übernommen"
            if not r.skipped and r.date is None:
                raise ImportError_("Datum fehlt")
        except ImportError_ as exc:
            r.error = str(exc)
        key = (r.date, r.kind, r.coin, r.quantity, r.amount, r.fee)
        seen[key] = seen.get(key, 0) + 1
        r.external_id = "bsdex:" + hashlib.sha1(f"{account_id}|{key}|{seen[key]}".encode()).hexdigest()[:24]
        result.append(r)
    return result
