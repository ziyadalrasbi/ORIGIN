"""Shared Celery client for API to enqueue tasks.

This module provides a singleton Celery instance configured to match
the worker's expectations (serializer, timezone, etc.).
"""

import logging
from typing import Optional

from celery import Celery

from origin_api.settings import get_settings

logger = logging.getLogger(__name__)

_celery_app: Optional[Celery] = None


def get_celery_app() -> Celery:
    """
    Get or create singleton Celery app instance.
    
    Configured to match worker expectations:
    - JSON serializer
    - UTC timezone
    - Redis broker + backend
    
    Returns:
        Celery app instance
    """
    global _celery_app
    
    if _celery_app is None:
        settings = get_settings()
        
        _celery_app = Celery("origin_api")
        _celery_app.conf.update(
            broker_url=settings.redis_url,
            result_backend=settings.redis_url,
            task_serializer="json",
            accept_content=["json"],
            result_serializer="json",
            timezone="UTC",
            enable_utc=True,
            task_track_started=True,
            task_time_limit=30 * 60,  # 30 minutes
            task_soft_time_limit=25 * 60,  # 25 minutes
        )
        
        logger.info("Initialized Celery client for origin_api")
    
    return _celery_app

