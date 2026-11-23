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


def sync_instrument(db: Session, instrument: Instrument, full: bool = False) -> int:
    source = SOURCES.get(instrument.price_source)
    if source is None or not instrument.price_symbol:
        return 0
    last = None if full else db.scalar(select(func.max(Price.date)).where(Price.instrument_id == instrument.id, Price.source == source.name))
    if last:
        start = last - timedelta(days=5)
    else:
        first_trade = db.scalar(select(func.min(Trade.date)).where(Trade.instrument_id == instrument.id))
        start = (first_trade - timedelta(days=10)) if first_trade else date.today() - timedelta(days=365 * 10)
    points = source.history(instrument.price_symbol, start, date.today())
    if not points:
        return 0
    has_prices = db.scalar(select(func.count()).select_from(Price).where(Price.instrument_id == instrument.id)) or 0
    quote_currency = points[-1].currency
    if quote_currency != instrument.currency:
        if has_prices and not full:
            raise PriceSourceError(f"Währung der Kurse ({quote_currency}) passt nicht zum Wertpapier ({instrument.currency}).")
        instrument.currency = quote_currency
    rows = [{"instrument_id": instrument.id, "date": p.date, "close": p.close, "source": source.name} for p in points]
    stmt = insert(Price).values(rows)
    db.execute(stmt.on_conflict_do_update(index_elements=["instrument_id", "date"], set_={"close": stmt.excluded.close, "source": stmt.excluded.source}))
    db.commit()
    cache.bump()
    return len(rows)


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
