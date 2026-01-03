"""Celery application configuration."""

from celery import Celery

from origin_worker.settings import get_settings

settings = get_settings()

celery_app = Celery(
    "origin_worker",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes
    task_soft_time_limit=25 * 60,  # 25 minutes
)

# Import tasks to register them with Celery
# This must be done after celery_app is created
from origin_worker import tasks  # noqa: F401, E402

