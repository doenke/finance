"""Price search and synchronisation."""

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.session import current_user
from ..db import get_db
from ..models import Instrument
from ..services.prices import SOURCES, PriceSourceError
from ..services.sync import get_state, start_sync_in_background, switch_to_onvista, sync_instrument

router = APIRouter(prefix="/api/prices", dependencies=[Depends(current_user)])


class SearchOut(BaseModel):
    symbol: str
    name: str
    exchange: str
    type: str


@router.get("/sources")
def sources() -> list[dict[str, str]]:
    return [{"key": "manual", "label": "manuell"}] + [{"key": k, "label": s.label} for k, s in SOURCES.items()]


@router.get("/search", response_model=list[SearchOut])
def search(q: str, source: str = "onvista") -> list[SearchOut]:
    adapter = SOURCES.get(source)
    if adapter is None:
        raise HTTPException(404, "Unbekannte Kursquelle")
    if len(q.strip()) < 2:
        return []
    try:
        return [SearchOut(**r.__dict__) for r in adapter.search(q.strip())]
    except PriceSourceError as exc:
        raise HTTPException(502, str(exc)) from None


@router.get("/status")
def status(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    state = get_state(db, "price_sync")
    settings = request.app.state.settings
    return {**state, "schedule": settings.price_sync_schedule, "stale_days": settings.price_stale_days}


@router.post("/sync", status_code=202)
def sync_now(request: Request) -> dict[str, str]:
    start_sync_in_background(request.app.state.sessionmaker)
    return {"status": "started"}


@router.post("/switch-to-onvista")
def switch(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    result = switch_to_onvista(db)
    if result["switched"]:
        start_sync_in_background(request.app.state.sessionmaker)
    return {"switched": len(result["switched"]), "missing": result["missing"]}


@router.post("/instruments/{instrument_id}")
def sync_one(instrument_id: int, full: bool = False, db: Session = Depends(get_db)) -> dict[str, Any]:
    instrument = db.get(Instrument, instrument_id)
    if instrument is None:
        raise HTTPException(404, "Wertpapier nicht gefunden")
    if instrument.price_source == "manual":
        raise HTTPException(422, "Für dieses Wertpapier werden Kurse von Hand gepflegt.")
    try:
        count = sync_instrument(db, instrument, full=full)
    except PriceSourceError as exc:
        db.rollback()
        raise HTTPException(502, str(exc)) from None
    return {"updated": count}


def is_stale(last: date | None, stale_days: int, today: date | None = None) -> bool:
    """True if the last price is older than `stale_days` trading days (Mon–Fri)."""
    if last is None:
        return True
    today = today or date.today()
    days, d = 0, last
    while d < today:
        d += timedelta(days=1)
        if d.weekday() < 5:
            days += 1
    return days > stale_days


class CandidateIn(BaseModel):
    query: str  # ISIN or name


_ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
_KIND = {"STOCK": "stock", "FUND": "fund", "ETF": "etf", "BOND": "bond", "CRYPTO": "crypto", "PRECIOUS_METAL": "metal", "CERTIFICATE": "certificate", "DERIVATIVE": "certificate"}


@router.post("/candidates")
def add_candidate(data: CandidateIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    """A security you are thinking about buying: found by ISIN or name, prices loaded, ready to compare."""
    q = data.query.strip()
    if len(q) < 2:
        raise HTTPException(422, "Bitte ISIN oder Name eingeben.")
    isin = q.upper() if _ISIN.match(q.upper()) else None
    instrument = db.scalar(select(Instrument).where(Instrument.isin == isin)) if isin else None
    if instrument is None:
        try:
            results = SOURCES["onvista"].search(q)
        except PriceSourceError as exc:
            raise HTTPException(502, str(exc)) from None
        hit = next((r for r in results if isin and r.exchange == isin), None) or (results[0] if results else None)
        if hit is None:
            raise HTTPException(404, "Dazu hat onvista nichts gefunden.")
        found_isin = hit.exchange if _ISIN.match(hit.exchange or "") else isin
        instrument = db.scalar(select(Instrument).where(Instrument.isin == found_isin)) if found_isin else None
        if instrument is None:
            entity = hit.symbol.split(":", 1)[0]
            kind = "etf" if "ETF" in (hit.type or "").upper() else _KIND.get(entity, "other")
            instrument = Instrument(
                kind=kind,
                name=hit.name[:200] or q,
                isin=found_isin,
                currency="EUR",
                price_source="onvista",
                price_symbol=hit.symbol[:40],
                details={"candidate": True},
            )
            db.add(instrument)
            db.commit()
    if instrument.price_source != "manual":
        try:
            sync_instrument(db, instrument, full=True)  # at least five years of history for the comparison
        except PriceSourceError as exc:
            db.rollback()
            raise HTTPException(502, f"Kurse konnten nicht geladen werden: {exc}") from None
    return {"instrument_id": instrument.id, "name": instrument.name, "isin": instrument.isin}
