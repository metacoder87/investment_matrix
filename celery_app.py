from celery import Celery
from celery.schedules import crontab
from datetime import timedelta

# It's a common pattern to import the settings from the main app package
# This requires the project root to be in the PYTHONPATH.
# When running celery, you'll do it from the project root.
from app.config import settings

celery_app = Celery(
    "tasks",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["celery_worker.tasks"],
)

# Optional configuration, see the Celery documentation for more options.
celery_app.conf.update(
    task_track_started=True,
    # Example of routing tasks to different queues based on name
    # task_routes = {'celery_worker.tasks.fetch_*': {'queue': 'data_ingestion'}},
)

beat_schedule = {}

if settings.AUTO_IMPORT_ENABLED and settings.AUTO_IMPORT_BINANCE_SYMBOLS:
    symbols = [s.strip() for s in settings.AUTO_IMPORT_BINANCE_SYMBOLS.split(",") if s.strip()]
    beat_schedule.update(
        {
            f"binance-vision-daily-{sym}": {
                "task": "celery_worker.tasks.import_binance_vision_yesterday",
                "schedule": crontab(hour=2, minute=5),
                "args": [sym, settings.AUTO_IMPORT_EXCHANGE, settings.AUTO_IMPORT_BINANCE_KIND],
            }
            for sym in symbols
        }
    )

beat_schedule.update({
    "backfill-core-hourly": {
        "task": "celery_worker.tasks.backfill_core_universe",
        "schedule": crontab(minute=0),  # Top of every hour
        "args": [], 
    },
    "update-coin-list-daily": {
        "task": "celery_worker.tasks.fetch_and_store_coin_list",
        "schedule": crontab(hour=0, minute=0), # Midnight
        "args": [], 
    }
})

if settings.PAPER_SCHEDULER_ENABLED:
    interval = max(5, settings.PAPER_SCHEDULER_INTERVAL_SECONDS)
    beat_schedule["paper-trading-tick"] = {
        "task": "celery_worker.tasks.tick_paper_schedules",
        "schedule": timedelta(seconds=interval),
    }

if beat_schedule:
    celery_app.conf.beat_schedule = beat_schedule

celery_app.autodiscover_tasks()
