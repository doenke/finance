"""Background jobs (cron expressions in Europe/Berlin)."""

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import sessionmaker

from .config import Settings
from .services.sync import run_sync_job

log = logging.getLogger("finanzen.scheduler")


def start_scheduler(settings: Settings, make_session: sessionmaker) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="Europe/Berlin")
    try:
        trigger = CronTrigger.from_crontab(settings.price_sync_schedule, timezone="Europe/Berlin")
        scheduler.add_job(run_sync_job, trigger, args=[make_session], id="price_sync", max_instances=1, coalesce=True)
    except ValueError:
        log.error("invalid PRICE_SYNC_SCHEDULE %r – automatic price updates are off", settings.price_sync_schedule)
    try:
        trigger = CronTrigger.from_crontab(settings.backup_schedule, timezone="Europe/Berlin")
        scheduler.add_job(run_backup_job, trigger, args=[settings, make_session], id="backup", max_instances=1, coalesce=True)
    except ValueError:
        log.error("invalid BACKUP_SCHEDULE %r – automatic backups are off", settings.backup_schedule)
    scheduler.start()
    return scheduler


def run_backup_job(settings: Settings, make_session: sessionmaker) -> None:
    from .services.backup import write_backup
    from .services.sync import set_state

    try:
        with make_session() as db:
            path = write_backup(db, settings.data_dir / "backup", settings.version, settings.backup_keep_days)
            set_state(db, "backup", {"ok": True, "file": path.name})
    except Exception as exc:  # noqa: BLE001
        log.exception("backup failed")
        try:
            with make_session() as db:
                set_state(db, "backup", {"ok": False, "error": str(exc)[:200]})
        except Exception:  # noqa: BLE001
            pass
