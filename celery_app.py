from celery import Celery

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

celery_app.autodiscover_tasks()