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
    try:
        trigger = CronTrigger.from_crontab(settings.fints_sync_schedule, timezone="Europe/Berlin")
        scheduler.add_job(run_fints_job, trigger, args=[settings, make_session], id="fints_sync", max_instances=1, coalesce=True)
    except ValueError:
        log.error("invalid FINTS_SYNC_SCHEDULE %r – automatic bank sync is off", settings.fints_sync_schedule)
    for name, schedule, func in (
        ("NOTIFY_SCHEDULE", settings.notify_schedule, run_notify_job),
        ("REPORT_SCHEDULE", settings.report_schedule, run_report_job),
    ):
        try:
            trigger = CronTrigger.from_crontab(schedule, timezone="Europe/Berlin")
            scheduler.add_job(func, trigger, args=[settings, make_session], id=name.lower(), max_instances=1, coalesce=True)
        except ValueError:
            log.error("invalid %s %r – the job is off", name, schedule)
    scheduler.start()
    return scheduler


def run_fints_job(settings: Settings, make_session: sessionmaker) -> None:
    """Automatic sync for bank logins with a stored PIN. Stops (and flags the login) if a TAN is required."""
    from sqlalchemy import select

    from .models import BankLogin
    from .services.fints_sync import jobs

    if not settings.fints_product_id:
        return
    with make_session() as db:
        ids = db.scalars(select(BankLogin.id).where(BankLogin.auto_sync.is_(True), BankLogin.pin_encrypted.is_not(None))).all()
    for login_id in ids:
        try:
            job = jobs.start("sync", login_id, None, settings, make_session, interactive=False, background=False)
        except Exception:  # noqa: BLE001
            log.exception("automatic bank sync failed")
            continue
        if job.status == "error":
            notify_bank_error(settings, make_session, login_id, job.error or "")


def notify_bank_error(settings: Settings, make_session: sessionmaker, login_id: int, error: str) -> None:
    from .models import BankLogin
    from .services.notify import bank_job_failed

    try:
        with make_session() as db:
            login = db.get(BankLogin, login_id)
            if login is not None:
                bank_job_failed(db, settings, login, error)
    except Exception:  # noqa: BLE001
        log.exception("bank error notification failed")


def run_notify_job(settings: Settings, make_session: sessionmaker) -> None:
    from .services.notify import run_daily

    run_daily(settings, make_session)


def run_report_job(settings: Settings, make_session: sessionmaker) -> None:
    from .services.notify import run_report

    try:
        run_report(settings, make_session)
    except Exception:  # noqa: BLE001
        log.exception("monthly report failed")


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
