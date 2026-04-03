"""
Celery App v8.

FIX: beat_schedule explicitly defined so recover_stale_executions and
cleanup_expired_keys actually run.
FIX: connect_dlq_signal() called in worker_init signal so DLQ recording
activates at every worker startup — not silently skipped.
"""
from celery import Celery
from celery.signals import worker_init, worker_ready
from app.core.config import get_settings
import logging

logger = logging.getLogger(__name__)
settings = get_settings()


def create_celery_app() -> Celery:
    app = Celery(
        "dps",
        broker=settings.CELERY_BROKER_URL,
        backend=settings.CELERY_RESULT_BACKEND,
    )
    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        task_soft_time_limit=settings.JOB_SOFT_TIME_LIMIT,
        task_time_limit=settings.JOB_HARD_TIME_LIMIT,
        result_expires=86400,
        task_max_retries=settings.JOB_MAX_RETRIES,
        task_routes={
            "app.services.tasks.profile_dataset_task":        {"queue": "profiling"},
            "app.services.tasks.execute_pipeline_task":       {"queue": "execution"},
            "app.services.tasks.recover_stale_executions":    {"queue": "default"},
            "app.services.tasks.cleanup_expired_idempotency": {"queue": "default"},
        },
        task_default_queue="default",
        broker_pool_limit=20,
        redis_max_connections=20,
        # ── v8 FIX: beat_schedule defined — was missing in v7 ──────────────
        beat_schedule={
            "recover-stale-executions": {
                "task": "app.services.tasks.recover_stale_executions",
                "schedule": settings.JOB_HARD_TIME_LIMIT,   # every JOB_HARD_TIME_LIMIT seconds
                "options": {"queue": "default"},
            },
            "cleanup-expired-idempotency-keys": {
                "task": "app.services.tasks.cleanup_expired_idempotency",
                "schedule": 3600,   # every hour
                "options": {"queue": "default"},
            },
            "cleanup-old-login-attempts": {
                "task": "app.services.tasks.cleanup_old_login_attempts",
                "schedule": 86400,  # daily
                "options": {"queue": "default"},
            },
        },
    )
    return app


celery_app = create_celery_app()


@worker_init.connect
def on_worker_init(sender, **kwargs):
    """
    FIX v8: wire DLQ signal at worker startup.
    In v7, connect_dlq_signal() was defined but never called.
    This signal fires on every worker process start.
    """
    from .services.dead_letter import connect_dlq_signal
    connect_dlq_signal()
    logger.info("DLQ signal handler registered on worker %s", sender)


@worker_ready.connect
def on_worker_ready(sender, **kwargs):
    logger.info("Celery worker ready: %s", sender)
