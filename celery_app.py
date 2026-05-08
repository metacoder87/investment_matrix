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
    "sync-kraken-markets-daily": {
        "task": "celery_worker.tasks.sync_exchange_markets_task",
        "schedule": crontab(hour=1, minute=10),
        "args": ["kraken"],
    },
    "sync-all-free-markets-daily": {
        "task": "celery_worker.tasks.sync_all_exchange_markets_task",
        "schedule": crontab(hour=1, minute=30),
        "args": [],
    },
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

if settings.STREAM_DYNAMIC_ENABLED:
    beat_schedule["ingestion-capacity-monitor"] = {
        "task": "celery_worker.tasks.collect_ingestion_telemetry_task",
        "schedule": timedelta(seconds=max(15, settings.INGEST_CAPACITY_MONITOR_SECONDS)),
        "args": [],
    }
    beat_schedule["stream-target-allocator"] = {
        "task": "celery_worker.tasks.allocate_stream_targets_task",
        "schedule": timedelta(seconds=max(15, settings.STREAM_REBALANCE_SECONDS)),
        "args": [],
    }

if settings.MARKET_ACTIVATION_ENABLED:
    beat_schedule["market-coverage-activation"] = {
        "task": "celery_worker.tasks.activate_market_coverage_task",
        "schedule": timedelta(seconds=max(300, settings.MARKET_ACTIVATION_INTERVAL_SECONDS)),
        "args": [],
    }

if settings.TIER2_REST_GAP_FILL_ENABLED:
    beat_schedule["tier2-rest-gap-fill"] = {
        "task": "celery_worker.tasks.schedule_tiered_rest_gap_fills_task",
        "schedule": timedelta(seconds=max(60, settings.TIER2_REST_GAP_FILL_SECONDS)),
        "args": [],
    }

if settings.DEX_INGEST_ENABLED:
    beat_schedule["dex-context-refresh"] = {
        "task": "celery_worker.tasks.ingest_dex_context_task",
        "schedule": timedelta(seconds=max(300, settings.DEX_CONTEXT_REFRESH_SECONDS)),
        "args": [],
    }

if settings.PAPER_SCHEDULER_ENABLED:
    interval = max(5, settings.PAPER_SCHEDULER_INTERVAL_SECONDS)
    beat_schedule["paper-trading-tick"] = {
        "task": "celery_worker.tasks.tick_paper_schedules",
        "schedule": timedelta(seconds=interval),
    }

if settings.CREW_RESEARCH_ENABLED:
    beat_schedule["crew-autonomous-research"] = {
        "task": "celery_worker.tasks.run_crew_research_cycles",
        "schedule": timedelta(seconds=max(60, settings.CREW_RESEARCH_INTERVAL_SECONDS)),
    }
    beat_schedule["crew-formula-learning"] = {
        "task": "celery_worker.tasks.run_formula_learning_cycles",
        "schedule": timedelta(seconds=max(300, settings.CREW_FORMULA_LEARNING_INTERVAL_SECONDS)),
    }

if settings.CREW_TRIGGER_MONITOR_ENABLED:
    beat_schedule["crew-trigger-monitor"] = {
        "task": "celery_worker.tasks.monitor_crew_triggers",
        "schedule": timedelta(seconds=max(5, settings.CREW_TRIGGER_POLL_SECONDS)),
    }

if beat_schedule:
    celery_app.conf.beat_schedule = beat_schedule

celery_app.autodiscover_tasks()
