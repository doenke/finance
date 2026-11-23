"""Fetch prices for instruments from their price source, plus ECB rates."""

import logging
import threading
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from .. import cache
from ..models import AppState, Instrument, Price, Trade
from .fx import sync_fx
from .prices import SOURCES, PriceSourceError

log = logging.getLogger("finanzen.sync")
_running = threading.Lock()


def set_state(db: Session, key: str, value: dict) -> None:
    row = db.get(AppState, key)
    if row is None:
        db.add(AppState(key=key, value=value))
    else:
        row.value = value
    db.commit()


def get_state(db: Session, key: str) -> dict:
    row = db.get(AppState, key)
    return row.value if row else {}


def onvista_symbol_for(instrument: Instrument) -> str | None:
    """onvista symbol for an instrument: remembered, from a Yahoo crypto symbol (BTC-EUR), or found by ISIN."""
    remembered = (instrument.details or {}).get("onvista_symbol")
    if remembered:
        return remembered
    if instrument.price_source == "onvista" and instrument.price_symbol:
        return instrument.price_symbol
    if instrument.price_symbol and instrument.kind == "crypto" and instrument.price_symbol.upper().endswith("-EUR"):
        return "CRYPTO:" + instrument.price_symbol.upper().replace("-", "")
    if instrument.isin:
        return SOURCES["onvista"].find_by_isin(instrument.isin)
    return None


def _start_date(db: Session, instrument: Instrument, full: bool) -> date:
    last = None if full else db.scalar(select(func.max(Price.date)).where(Price.instrument_id == instrument.id, Price.source != "manual"))
    if last:
        return last - timedelta(days=5)
    first_trade = db.scalar(select(func.min(Trade.date)).where(Trade.instrument_id == instrument.id))
    return (first_trade - timedelta(days=10)) if first_trade else date.today() - timedelta(days=365 * 10)


def sync_instrument(db: Session, instrument: Instrument, full: bool = False) -> int:
    source = SOURCES.get(instrument.price_source)
    if source is None or not instrument.price_symbol:
        return 0
    start = _start_date(db, instrument, full)
    source_name = source.name
    try:
        points = source.history(instrument.price_symbol, start, date.today())
    except PriceSourceError:
        # Fallback: onvista by ISIN (or crypto symbol), so one blocked source does not leave gaps.
        if source.name == "onvista":
            raise
        try:
            fallback = onvista_symbol_for(instrument)
        except PriceSourceError:
            fallback = None
        if not fallback:
            raise
        points = SOURCES["onvista"].history(fallback, start, date.today())
        source_name = "onvista"
        details = dict(instrument.details or {})
        details["onvista_symbol"] = fallback
        instrument.details = details
        log.info("used onvista as fallback for %s", instrument.price_symbol)
    if not points:
        return 0
    has_prices = db.scalar(select(func.count()).select_from(Price).where(Price.instrument_id == instrument.id, Price.source != "manual")) or 0
    quote_currency = points[-1].currency
    if quote_currency != instrument.currency:
        if has_prices and not full:
            raise PriceSourceError(f"Währung der Kurse ({quote_currency}) passt nicht zum Wertpapier ({instrument.currency}).")
        instrument.currency = quote_currency
    rows = [{"instrument_id": instrument.id, "date": p.date, "close": p.close, "source": source_name} for p in points]
    stmt = insert(Price).values(rows)
    db.execute(stmt.on_conflict_do_update(index_elements=["instrument_id", "date"], set_={"close": stmt.excluded.close, "source": stmt.excluded.source}))
    db.commit()
    cache.bump()
    return len(rows)


def switch_to_onvista(db: Session) -> dict:
    """Moves all Yahoo instruments that onvista knows (by ISIN or crypto symbol) to onvista."""
    switched, missing = [], []
    for instrument in db.scalars(select(Instrument).where(Instrument.price_source == "yahoo")).all():
        try:
            symbol = onvista_symbol_for(instrument)
        except PriceSourceError:
            symbol = None
        if symbol:
            instrument.price_source = "onvista"
            instrument.price_symbol = symbol
            switched.append(instrument.id)
        else:
            missing.append(instrument.name)
    db.commit()
    return {"switched": switched, "missing": missing}


def sync_all(db: Session) -> dict:
    """Update ECB rates and all instruments with an automatic price source. Returns the status."""
    errors: list[dict] = []
    updated = 0
    try:
        sync_fx(db)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        errors.append({"instrument": "EZB-Wechselkurse", "message": str(exc)[:200]})
    instruments = db.scalars(select(Instrument).where(Instrument.price_source != "manual", Instrument.price_symbol.is_not(None))).all()
    for instrument in instruments:
        try:
            if sync_instrument(db, instrument):
                updated += 1
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            log.warning("price sync failed for %s: %s", instrument.price_symbol, exc)
            errors.append({"instrument": instrument.name, "message": str(exc)[:200]})
    cache.bump()
    status = {"finished_at": datetime.now(UTC).isoformat(), "updated": updated, "total": len(instruments), "errors": errors}
    set_state(db, "price_sync", status)
    return status


def run_sync_job(make_session: sessionmaker) -> None:
    if not _running.acquire(blocking=False):
        log.info("price sync already running")
        return
    try:
        with make_session() as db:
            set_state(db, "price_sync", {**get_state(db, "price_sync"), "running": True})
            sync_all(db)
    except Exception:  # noqa: BLE001
        log.exception("price sync crashed")
    finally:
        _running.release()


def start_sync_in_background(make_session: sessionmaker) -> None:
    threading.Thread(target=run_sync_job, args=(make_session,), daemon=True, name="price-sync").start()


def sync_instrument_in_background(make_session: sessionmaker, instrument_id: int) -> None:
    def job() -> None:
        try:
            with make_session() as db:
                instrument = db.get(Instrument, instrument_id)
                if instrument:
                    sync_instrument(db, instrument)
        except Exception as exc:  # noqa: BLE001
            log.warning("initial price download failed: %s", exc)

    threading.Thread(target=job, daemon=True, name=f"price-{instrument_id}").start()
