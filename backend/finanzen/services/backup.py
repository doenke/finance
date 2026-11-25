"""Full logical backup of all tables as JSON (also the data export), and restore into an empty database."""

import base64
import gzip
import json
import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .. import models  # noqa: F401 - registers all tables
from ..db import Base

log = logging.getLogger("finanzen.backup")
FORMAT = "finanzen-backup"
FORMAT_VERSION = 1
SKIP_TABLES = {"alembic_version"}
# Left out of the data export for household members (the admin backup keeps everything):
# login sessions, assistant tokens and push keys, and the secrets of bank logins.
PRIVATE_TABLES = {"sessions", "oauth_clients", "oauth_codes", "oauth_tokens", "push_subscriptions"}
BANK_SECRETS = ("pin_encrypted", "client_state")
BANK_OWNER_ONLY = ("username", "customer_id", "tan_medium")


def _encode(value: Any) -> Any:
    if isinstance(value, Decimal):
        return {"$dec": str(value)}
    if isinstance(value, datetime):
        return {"$dt": value.isoformat()}
    if isinstance(value, date):
        return {"$d": value.isoformat()}
    if isinstance(value, bytes | memoryview):
        return {"$b": base64.b64encode(bytes(value)).decode()}
    return value


def _decode(value: Any) -> Any:
    if isinstance(value, dict) and len(value) == 1:
        (key, v), = value.items()
        if key == "$dec":
            return Decimal(v)
        if key == "$dt":
            return datetime.fromisoformat(v)
        if key == "$d":
            return date.fromisoformat(v)
        if key == "$b":
            return base64.b64decode(v)
    return value


def _redact_bank_login(row: dict, user_id: int) -> dict:
    row = {**row, **{k: None for k in BANK_SECRETS}}
    if row.get("user_id") != user_id:
        row.update({k: ("" if k != "tan_medium" else None) for k in BANK_OWNER_ONLY})
    return row


def export_data(db: Session, version: str = "dev", for_user_id: int | None = None) -> dict:
    """All tables as JSON. With `for_user_id` (the data export in the app) private tables are left out and bank
    logins lose their secrets; access data of other people's logins is blanked. Without it: the full backup."""
    tables: dict[str, list[dict]] = {}
    for table in Base.metadata.sorted_tables:
        if table.name in SKIP_TABLES or (for_user_id is not None and table.name in PRIVATE_TABLES):
            continue
        rows = [dict(row) for row in db.execute(select(table)).mappings().all()]
        if for_user_id is not None and table.name == "bank_logins":
            rows = [_redact_bank_login(row, for_user_id) for row in rows]
        tables[table.name] = [{k: _encode(v) for k, v in row.items()} for row in rows]
    revision = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    return {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "app_version": version,
        "schema_revision": revision,
        "created_at": datetime.now(UTC).isoformat(),
        "scope": "export" if for_user_id is not None else "backup",
        "tables": tables,
    }


def restore_data(db: Session, data: dict) -> dict[str, int]:
    if data.get("format") != FORMAT:
        raise ValueError("Das ist keine Finanzen-Sicherung.")
    revision = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    if data.get("schema_revision") != revision:
        raise ValueError(f"Die Sicherung hat den Datenbankstand {data.get('schema_revision')}, die App {revision}. Bitte die passende Version verwenden.")
    for table in Base.metadata.sorted_tables:
        if table.name in SKIP_TABLES:
            continue
        if db.execute(select(func.count()).select_from(table)).scalar():
            raise ValueError("Die Datenbank ist nicht leer – Wiederherstellen geht nur in eine frische Datenbank.")
    counts: dict[str, int] = {}
    for table in Base.metadata.sorted_tables:
        rows = data["tables"].get(table.name, [])
        if not rows:
            continue
        # Self references (accounts.settlement_account_id) are filled in a second step.
        self_refs = [c.name for c in table.columns for fk in c.foreign_keys if fk.column.table is table]
        decoded = [{k: _decode(v) for k, v in row.items()} for row in rows]
        deferred = []
        for row in decoded:
            refs = {c: row.pop(c, None) for c in self_refs}
            if any(v is not None for v in refs.values()):
                deferred.append((row, refs))
        db.execute(table.insert(), decoded)
        for row, refs in deferred:
            db.execute(table.update().where(table.c.id == row["id"]).values(**refs))
        if "id" in table.c and table.c.id.autoincrement:
            db.execute(text(f"SELECT setval(pg_get_serial_sequence('{table.name}', 'id'), COALESCE((SELECT MAX(id) FROM {table.name}), 1))"))
        counts[table.name] = len(rows)
    db.commit()
    return counts


def write_backup(db: Session, directory: Path, version: str, keep_days: int) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    path = directory / f"finanzen-{stamp}.json.gz"
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump(export_data(db, version), fh, ensure_ascii=False)
    tmp.replace(path)
    cutoff = datetime.now() - timedelta(days=keep_days)
    for old in directory.glob("finanzen-*.json.gz"):
        if datetime.fromtimestamp(old.stat().st_mtime) < cutoff and old != path:
            old.unlink(missing_ok=True)
    log.info("backup written: %s", path.name)
    return path


def list_backups(directory: Path) -> list[dict]:
    if not directory.is_dir():
        return []
    files = sorted(directory.glob("finanzen-*.json.gz"), reverse=True)
    return [{"name": f.name, "size": f.stat().st_size, "created_at": datetime.fromtimestamp(f.stat().st_mtime, UTC).isoformat()} for f in files]
