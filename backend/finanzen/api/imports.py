"""CSV imports with preview and undo, data export and backups."""

import csv
import io
import json
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .. import kinds
from ..auth.session import admin_user, current_user
from ..db import get_db
from ..models import Account, AccountOwner, ImportBatch, Instrument, Trade, Transaction, User
from ..services.backup import export_data, list_backups, write_backup
from ..services.bsdex import COINS, parse_bsdex
from ..services.csvimport import ImportError_, guess_mapping, header_index, parse_bookings, parse_portfolio_performance, sniff
from ..services.sync import get_state, set_state

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])
MAX_TEXT = 10 * 1024 * 1024


class BookingImportIn(BaseModel):
    account_id: int
    text: str = Field(max_length=MAX_TEXT)
    filename: str = ""
    mapping: dict[str, int | None] | None = None
    date_format: str | None = None
    invert: bool = False  # e.g. credit card exports with positive spending
    profile: str | None = None  # save the mapping under this name


class TradeImportIn(BaseModel):
    account_id: int
    text: str = Field(max_length=MAX_TEXT)
    filename: str = ""


def _account(db: Session, account_id: int, mode: str) -> Account:
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(404, "Konto nicht gefunden")
    if kinds.KINDS[account.kind].mode != mode and not (mode == kinds.CASH and kinds.KINDS[account.kind].mode in (kinds.VALUATION, kinds.LOAN)):
        raise HTTPException(422, "Das passt nicht zu dieser Kontoart.")
    return account


def _existing_ids(db: Session, model, account_id: int, ids: list[str]) -> set[str]:
    if not ids:
        return set()
    rows = db.scalars(select(model.external_id).where(model.account_id == account_id, model.external_id.in_(ids))).all()
    return set(rows)


def _bookings(db: Session, data: BookingImportIn) -> dict[str, Any]:
    _account(db, data.account_id, kinds.CASH)
    _, rows = sniff(data.text)
    if not rows:
        raise HTTPException(422, "Die Datei ist leer.")
    header = rows[header_index(rows)]
    mapping = data.mapping or guess_mapping(header)
    if mapping.get("booking_date") is None or mapping.get("amount") is None:
        return {"header": header, "mapping": mapping, "rows": [], "summary": {"new": 0, "duplicate": 0, "error": 0}}
    _, parsed = parse_bookings(data.text, mapping, data.account_id, data.date_format)
    existing = _existing_ids(db, Transaction, data.account_id, [p.external_id for p in parsed if p.external_id])
    out = []
    summary = {"new": 0, "duplicate": 0, "error": 0}
    for p in parsed:
        amount = -p.amount if (data.invert and p.amount is not None) else p.amount
        status = "error" if p.error else "duplicate" if p.external_id in existing else "new"
        summary[status] += 1
        out.append({"line": p.line, "status": status, "error": p.error, "booking_date": p.booking_date, "value_date": p.value_date, "amount": amount, "counterparty": p.counterparty, "purpose": p.purpose, "external_id": p.external_id, "raw": p.raw})
    return {"header": header, "mapping": mapping, "rows": out, "summary": summary}


@router.post("/import/bookings/preview")
def bookings_preview(data: BookingImportIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    result = _bookings(db, data)
    result["rows"] = result["rows"][:500]
    for r in result["rows"]:
        r.pop("raw", None)
    return result


@router.post("/import/bookings/commit")
def bookings_commit(data: BookingImportIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    result = _bookings(db, data)
    new = [r for r in result["rows"] if r["status"] == "new"]
    if not new:
        raise HTTPException(422, "Keine neuen Buchungen gefunden.")
    batch = ImportBatch(kind="bookings", account_id=data.account_id, filename=data.filename[:255], count=len(new), created_by=user.id)
    db.add(batch)
    db.flush()
    for r in new:
        db.add(
            Transaction(
                account_id=data.account_id,
                booking_date=r["booking_date"],
                value_date=r["value_date"],
                amount=r["amount"],
                kind="other",
                counterparty=r["counterparty"],
                purpose=r["purpose"],
                external_id=r["external_id"],
                import_batch_id=batch.id,
                raw=r["raw"],
            )
        )
    if data.profile and data.mapping:
        profiles = get_state(db, "csv_profiles")
        profiles[data.profile[:60]] = {"mapping": data.mapping, "date_format": data.date_format, "invert": data.invert}
        set_state(db, "csv_profiles", profiles)
    db.commit()
    return {"batch_id": batch.id, "imported": len(new), "skipped": result["summary"]["duplicate"]}


@router.get("/import/profiles")
def profiles(db: Session = Depends(get_db)) -> dict[str, Any]:
    return get_state(db, "csv_profiles")


def _trades(db: Session, data: TradeImportIn) -> dict[str, Any]:
    _account(db, data.account_id, kinds.HOLDINGS)
    try:
        parsed = parse_portfolio_performance(data.text, data.account_id)
    except ImportError_ as exc:
        raise HTTPException(422, str(exc)) from None
    existing = _existing_ids(db, Trade, data.account_id, [p.external_id for p in parsed if p.external_id])
    out = []
    summary = {"new": 0, "duplicate": 0, "error": 0, "skipped": 0}
    for p in parsed:
        status = "error" if p.error else "skipped" if p.skipped else "duplicate" if p.external_id in existing else "new"
        summary[status] += 1
        out.append({**p.__dict__, "status": status, "message": p.error or p.skipped})
    return {"rows": out, "summary": summary}


@router.post("/import/portfolio-performance/preview")
def pp_preview(data: TradeImportIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    result = _trades(db, data)
    result["rows"] = result["rows"][:500]
    return result


def _instrument_for(db: Session, row: dict, cache: dict) -> Instrument | None:
    key = row["isin"] or row["name"]
    if not key:
        return None
    if key in cache:
        return cache[key]
    instrument = None
    if row["isin"]:
        instrument = db.scalar(select(Instrument).where(Instrument.isin == row["isin"]))
    if instrument is None and row["name"]:
        instrument = db.scalar(select(Instrument).where(Instrument.name == row["name"]))
    if instrument is None:
        instrument = Instrument(
            kind="stock",
            name=row["name"] or row["isin"],
            isin=row["isin"] or None,
            wkn=row["wkn"] or None,
            symbol=row["symbol"] or None,
            currency="EUR",
            price_source="yahoo" if row["symbol"] else "manual",
            price_symbol=row["symbol"] or None,
            details={},
        )
        db.add(instrument)
        db.flush()
    cache[key] = instrument
    return instrument


@router.post("/import/portfolio-performance/commit")
def pp_commit(data: TradeImportIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    result = _trades(db, data)
    new = [r for r in result["rows"] if r["status"] == "new"]
    if not new:
        raise HTTPException(422, "Keine neuen Transaktionen gefunden.")
    batch = ImportBatch(kind="portfolio-performance", account_id=data.account_id, filename=data.filename[:255], count=len(new), created_by=user.id)
    db.add(batch)
    db.flush()
    cache: dict = {}
    created = 0
    for r in new:
        instrument = _instrument_for(db, r, cache)
        price = (r["amount"] / r["quantity"]) if r["quantity"] and r["type"] in ("buy", "sell", "deliver_in", "deliver_out") else None
        db.add(
            Trade(
                account_id=data.account_id,
                instrument_id=instrument.id if instrument else None,
                date=r["date"],
                type=r["type"],
                quantity=r["quantity"],
                price=price,
                amount=r["amount"],
                fees=r["fees"],
                taxes=r["taxes"],
                note=r["note"],
                external_id=r["external_id"],
                import_batch_id=batch.id,
            )
        )
        created += 1
    db.commit()
    return {"batch_id": batch.id, "imported": created, "instruments": len(cache), "skipped": result["summary"]["duplicate"] + result["summary"]["skipped"]}


class BsdexImportIn(BaseModel):
    account_id: int
    text: str = Field(max_length=MAX_TEXT)
    filename: str = ""
    create_settlement: bool = True


def _bsdex(db: Session, data: BsdexImportIn) -> dict[str, Any]:
    account = _account(db, data.account_id, kinds.HOLDINGS)
    try:
        parsed = parse_bsdex(data.text, data.account_id)
    except ImportError_ as exc:
        raise HTTPException(422, str(exc)) from None
    existing_trades = _existing_ids(db, Trade, data.account_id, [p.external_id for p in parsed if p.kind in ("buy", "sell")])
    settlement = db.get(Account, account.settlement_account_id) if account.settlement_account_id else None
    existing_cash = _existing_ids(db, Transaction, settlement.id, [p.external_id + ":cash" for p in parsed]) if settlement else set()
    rows, summary = [], {"new": 0, "duplicate": 0, "error": 0, "skipped": 0}
    for p in parsed:
        if p.error:
            status = "error"
        elif p.skipped:
            status = "skipped"
        elif p.kind in ("buy", "sell"):
            status = "duplicate" if p.external_id in existing_trades else "new"
        else:
            status = "duplicate" if (p.external_id + ":cash") in existing_cash else "new"
        summary[status] += 1
        rows.append({**p.__dict__, "status": status, "message": p.error or p.skipped})
    return {
        "rows": rows,
        "summary": summary,
        "settlement": {"id": settlement.id, "name": settlement.name} if settlement else None,
    }


@router.post("/import/bsdex/preview")
def bsdex_preview(data: BsdexImportIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _bsdex(db, data)


def _crypto_instrument(db: Session, coin: str, symbol: str) -> Instrument:
    yahoo = COINS.get(coin.lower(), (symbol, None))[1]
    instrument = None
    if yahoo:
        instrument = db.scalar(select(Instrument).where(Instrument.price_symbol == yahoo))
    if instrument is None:
        instrument = db.scalar(select(Instrument).where(Instrument.kind == "crypto", Instrument.symbol == symbol))
    if instrument is None:
        instrument = Instrument(
            kind="crypto",
            name=coin,
            symbol=symbol,
            currency="EUR",
            price_source="yahoo" if yahoo else "manual",
            price_symbol=yahoo,
            details={},
        )
        db.add(instrument)
        db.flush()
    return instrument


@router.post("/import/bsdex/commit")
def bsdex_commit(data: BsdexImportIn, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    result = _bsdex(db, data)
    new = [r for r in result["rows"] if r["status"] == "new"]
    if not new:
        raise HTTPException(422, "Keine neuen Buchungen gefunden.")
    account = db.get(Account, data.account_id)
    settlement = db.get(Account, account.settlement_account_id) if account.settlement_account_id else None
    if settlement is None and data.create_settlement:
        settlement = Account(name=f"{account.name} – Euro", kind="verrechnung", asset_class="cash", institution=account.institution or "BSDEX", details={})
        settlement.owners = [AccountOwner(person_id=o.person_id, share=o.share) for o in account.owners]
        db.add(settlement)
        db.flush()
        account.settlement_account_id = settlement.id
    batch = ImportBatch(kind="bsdex", account_id=data.account_id, filename=data.filename[:255], count=len(new), created_by=user.id)
    db.add(batch)
    db.flush()
    trades = cash = 0
    new_instruments: list[Instrument] = []
    for r in new:
        if r["kind"] in ("buy", "sell"):
            before = db.scalar(select(Instrument.id).where(Instrument.kind == "crypto", Instrument.symbol == r["symbol"]))
            instrument = _crypto_instrument(db, r["coin"], r["symbol"])
            if before is None and instrument not in new_instruments:
                new_instruments.append(instrument)
            db.add(
                Trade(
                    account_id=account.id,
                    instrument_id=instrument.id,
                    date=r["date"],
                    type=r["kind"],
                    quantity=r["quantity"],
                    price=r["price"],
                    amount=r["amount"],
                    fees=r["fee"],
                    note="BSDEX",
                    external_id=r["external_id"],
                    import_batch_id=batch.id,
                )
            )
            trades += 1
        if settlement is None:
            continue
        if r["kind"] == "buy":
            amount, text = -(r["amount"] + r["fee"]), f"Kauf {r['coin']}"
        elif r["kind"] == "sell":
            amount, text = r["amount"] - r["fee"], f"Verkauf {r['coin']}"
        elif r["kind"] == "deposit":
            amount, text = r["amount"], "Einzahlung"
        else:
            amount, text = -r["amount"], "Auszahlung"
        db.add(
            Transaction(
                account_id=settlement.id,
                booking_date=r["date"],
                amount=amount,
                kind="transfer",
                counterparty="BSDEX",
                purpose=text,
                external_id=r["external_id"] + ":cash",
                import_batch_id=batch.id,
            )
        )
        cash += 1
    db.commit()
    if request.app.state.settings.scheduler:
        from ..services.sync import sync_instrument_in_background

        for instrument in new_instruments:
            if instrument.price_symbol:
                sync_instrument_in_background(request.app.state.sessionmaker, instrument.id)
    return {"batch_id": batch.id, "imported": trades + cash, "trades": trades, "cash": cash, "settlement_id": settlement.id if settlement else None, "skipped": result["summary"]["skipped"] + result["summary"]["duplicate"]}


@router.get("/import/batches")
def batches(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = db.execute(select(ImportBatch, Account.name).join(Account, Account.id == ImportBatch.account_id, isouter=True).order_by(ImportBatch.id.desc()).limit(50)).all()
    return [{"id": b.id, "kind": b.kind, "account_id": b.account_id, "account_name": name, "filename": b.filename, "count": b.count, "created_at": b.created_at} for b, name in rows]


@router.delete("/import/batches/{batch_id}", status_code=204)
def undo_batch(batch_id: int, db: Session = Depends(get_db)) -> Response:
    batch = db.get(ImportBatch, batch_id)
    if batch is None:
        raise HTTPException(404, "Import nicht gefunden")
    db.execute(delete(Transaction).where(Transaction.import_batch_id == batch_id))
    db.execute(delete(Trade).where(Trade.import_batch_id == batch_id))
    db.delete(batch)
    db.commit()
    return Response(status_code=204)


# --- Export --------------------------------------------------------------------------------------


def _csv_response(rows: list[list[Any]], filename: str) -> StreamingResponse:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    for row in rows:
        writer.writerow(["" if v is None else str(v).replace(".", ",") if isinstance(v, Decimal) else v for v in row])
    data = "﻿" + buf.getvalue()
    return StreamingResponse(iter([data]), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/export/json")
def export_json(request: Request, db: Session = Depends(get_db)) -> Response:
    data = export_data(db, request.app.state.settings.version)
    body = json.dumps(data, ensure_ascii=False)
    name = f"finanzen-export-{date.today().isoformat()}.json"
    return Response(body, media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/export/transactions.csv")
def export_transactions(account_id: int | None = None, db: Session = Depends(get_db)) -> StreamingResponse:
    stmt = select(Transaction, Account.name).join(Account, Account.id == Transaction.account_id).order_by(Transaction.booking_date, Transaction.id)
    if account_id:
        stmt = stmt.where(Transaction.account_id == account_id)
    rows = [["Konto", "Buchungstag", "Valuta", "Betrag", "Art", "Empfänger/Auftraggeber", "Verwendungszweck"]]
    for t, name in db.execute(stmt).all():
        rows.append([name, t.booking_date, t.value_date, t.amount, kinds.TRANSACTION_KINDS.get(t.kind, t.kind), t.counterparty, t.purpose])
    return _csv_response(rows, "buchungen.csv")


@router.get("/export/trades.csv")
def export_trades(account_id: int | None = None, db: Session = Depends(get_db)) -> StreamingResponse:
    stmt = (
        select(Trade, Account.name, Instrument)
        .join(Account, Account.id == Trade.account_id)
        .join(Instrument, Instrument.id == Trade.instrument_id, isouter=True)
        .order_by(Trade.date, Trade.id)
    )
    if account_id:
        stmt = stmt.where(Trade.account_id == account_id)
    rows = [["Depot", "Datum", "Typ", "Wertpapier", "ISIN", "Stück", "Kurs", "Betrag", "Gebühren", "Steuern", "Notiz"]]
    for t, name, inst in db.execute(stmt).all():
        rows.append([name, t.date, kinds.TRADE_TYPES.get(t.type, t.type), inst.name if inst else "", inst.isin if inst else "", t.quantity, t.price, t.amount, t.fees, t.taxes, t.note])
    return _csv_response(rows, "transaktionen.csv")


# --- Backups (admin) ----------------------------------------------------------------------------

admin = APIRouter(prefix="/api/admin", dependencies=[Depends(admin_user)])


@admin.get("/backups")
def get_backups(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    settings = request.app.state.settings
    return {"files": list_backups(settings.data_dir / "backup"), "schedule": settings.backup_schedule, "keep_days": settings.backup_keep_days, "last": get_state(db, "backup")}


@admin.post("/backups")
def run_backup(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    settings = request.app.state.settings
    path = write_backup(db, settings.data_dir / "backup", settings.version, settings.backup_keep_days)
    set_state(db, "backup", {"ok": True, "file": path.name})
    return {"file": path.name}


@admin.get("/backups/{name}")
def download_backup(name: str, request: Request) -> FileResponse:
    directory = (request.app.state.settings.data_dir / "backup").resolve()
    path = (directory / name).resolve()
    if not name.startswith("finanzen-") or not name.endswith(".json.gz") or path.parent != directory or not path.is_file():
        raise HTTPException(404, "Sicherung nicht gefunden")
    return FileResponse(path, media_type="application/gzip", filename=name)
