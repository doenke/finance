"""Health checks for /healthz: database reachable and data directory writable."""

import os
import tempfile

import psycopg

from .config import Settings


def check_db(settings: Settings) -> str:
    if not settings.database_url:
        return "not configured"
    try:
        with psycopg.connect(settings.database_url, connect_timeout=3) as conn:
            conn.execute("SELECT 1")
        return "ok"
    except Exception:  # noqa: BLE001 - details must not leak into the response
        return "error"


def check_data_dir(settings: Settings) -> str:
    try:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        fd, path = tempfile.mkstemp(dir=settings.data_dir, prefix=".healthz-")
        os.close(fd)
        os.remove(path)
        return "ok"
    except OSError:
        return "error"


def run_checks(settings: Settings) -> tuple[bool, dict[str, str]]:
    checks = {"db": check_db(settings), "data": check_data_dir(settings)}
    return all(v == "ok" for v in checks.values()), checks
