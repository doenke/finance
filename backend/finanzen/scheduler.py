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
    scheduler.start()
    return scheduler
