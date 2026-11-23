"""ECB reference rates (EUR base) for converting foreign currency prices."""

import logging
import xml.etree.ElementTree as ET
from datetime import date
from decimal import Decimal

import httpx
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..models import FxRate

log = logging.getLogger("finanzen.fx")

ECB_90D = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml"
ECB_FULL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.xml"
NS = {"e": "http://www.ecb.int/vocabulary/2002-08-01/eurofxref"}


def parse_ecb(xml: str) -> list[tuple[date, str, Decimal]]:
    root = ET.fromstring(xml)
    rows = []
    for day in root.iterfind(".//e:Cube[@time]", NS):
        d = date.fromisoformat(day.attrib["time"])
        for cube in day.iterfind("e:Cube", NS):
            rows.append((d, cube.attrib["currency"], Decimal(cube.attrib["rate"])))
    return rows


def sync_fx(db: Session, transport: httpx.BaseTransport | None = None) -> int:
    has_data = db.scalar(select(func.count()).select_from(FxRate)) or 0
    url = ECB_90D if has_data else ECB_FULL
    with httpx.Client(timeout=60.0, transport=transport) as client:
        res = client.get(url)
        res.raise_for_status()
    rows = parse_ecb(res.text)
    for start in range(0, len(rows), 5000):
        chunk = rows[start : start + 5000]
        stmt = insert(FxRate).values([{"date": d, "currency": c, "rate": r} for d, c, r in chunk])
        db.execute(stmt.on_conflict_do_update(index_elements=["currency", "date"], set_={"rate": stmt.excluded.rate}))
    db.commit()
    return len(rows)


class FxConverter:
    """Converts amounts to EUR with the latest ECB rate on or before a day (cached per instance)."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self._cache: dict[tuple[str, date], Decimal | None] = {}

    def to_eur_factor(self, currency: str, on: date) -> Decimal | None:
        currency = currency.upper()
        if currency == "EUR":
            return Decimal("1")
        key = (currency, on)
        if key not in self._cache:
            rate = self.db.scalar(
                select(FxRate.rate).where(FxRate.currency == currency, FxRate.date <= on).order_by(FxRate.date.desc()).limit(1)
            )
            self._cache[key] = (Decimal("1") / rate) if rate else None
        return self._cache[key]
