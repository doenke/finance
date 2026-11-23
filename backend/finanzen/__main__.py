"""Run with `python -m finanzen` (server), `python -m finanzen backup`, `python -m finanzen restore FILE` or `python -m finanzen vapid`."""

import gzip
import json
import sys

import uvicorn

from .config import load_settings


def serve() -> None:
    settings = load_settings()
    uvicorn.run(
        "finanzen.main:create_app",
        factory=True,
        host="0.0.0.0",
        port=settings.port,
        proxy_headers=settings.trusted_proxy,
        forwarded_allow_ips="*" if settings.trusted_proxy else None,
        access_log=False,
        log_level=settings.log_level,
    )


def cli(args: list[str]) -> int:
    if args[0] == "vapid":
        from .services.webpush import generate_vapid_keys

        public, private = generate_vapid_keys()
        print("# In die .env eintragen (einmal erzeugen, danach nicht mehr ändern):")
        print(f"VAPID_PUBLIC_KEY={public}")
        print(f"VAPID_PRIVATE_KEY={private}")
        return 0
    from .db import make_engine, make_sessionmaker, run_migrations
    from .services.backup import restore_data, write_backup

    settings = load_settings()
    if not settings.database_url:
        print("DATABASE_URL fehlt.")
        return 2
    run_migrations(settings.database_url)
    make_session = make_sessionmaker(make_engine(settings.database_url))
    with make_session() as db:
        if args[0] == "backup":
            path = write_backup(db, settings.data_dir / "backup", settings.version, settings.backup_keep_days)
            print(f"Sicherung geschrieben: {path}")
            return 0
        if args[0] == "restore" and len(args) == 2:
            opener = gzip.open if args[1].endswith(".gz") else open
            with opener(args[1], "rt", encoding="utf-8") as fh:
                data = json.load(fh)
            try:
                counts = restore_data(db, data)
            except ValueError as exc:
                print(f"Fehler: {exc}")
                return 1
            print("Wiederhergestellt: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
            return 0
    print("Aufruf: python -m finanzen [backup | restore DATEI | vapid]")
    return 2


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] == "serve":
        serve()
    else:
        sys.exit(cli(args))


if __name__ == "__main__":
    main()
