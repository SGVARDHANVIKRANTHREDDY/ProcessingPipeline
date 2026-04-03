"""
Dead Letter Queue v8 — single implementation (dlq.py removed).

FIX: In v7 there were two competing DLQ systems:
  - dlq.py: Redis-based singleton, never wired, referenced missing config
  - dead_letter.py: PostgreSQL-based, connected to task_failure signal,
    but connect_dlq_signal() was never called at worker startup

v8: Only dead_letter.py exists. dlq.py is deleted.
    connect_dlq_signal() is called from celery_app.py worker_init signal.
    replay_dlq_entry() signature fixed: admin.py was calling it with 1 arg,
    function required 2. Now admin_user_id is optional (defaults to None).
"""
import logging
import asyncio
import traceback as tb
from datetime import datetime, timezone, timedelta
from celery.signals import task_failure
from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)
UTC = timezone.utc

_dlq_signal_connected = False


async def record_dlq_entry(celery_task_id: str, task_name: str, queue: str,
                            args: list, kwargs: dict, error: str,
                            traceback_str: str, retry_count: int) -> None:
    """Persist a dead letter entry to PostgreSQL."""
    from app.core.database.engine import AsyncSessionLocal
    from app.models import DeadLetterEntry

    logger.error("DLQ_ENTRY task=%s id=%s queue=%s retries=%d error=%.200s",
                 task_name, celery_task_id, queue, retry_count, error)

    async with AsyncSessionLocal() as db:
        entry = DeadLetterEntry(
            celery_task_id=celery_task_id, task_name=task_name, queue=queue,
            args=args, kwargs=kwargs,
            error=error[:2000], traceback=traceback_str[:5000],
            retry_count=retry_count,
        )
        db.add(entry)
        await db.commit()

    _alert_dlq(task_name, celery_task_id, error)


def _alert_dlq(task_name: str, task_id: str, error: str) -> None:
    """Production: replace with PagerDuty/Slack webhook."""
    logger.critical("ALERT:DLQ task=%s id=%s error=%.100s", task_name, task_id, error)


async def replay_dlq_entry(entry_id: int, admin_user_id: int | None = None) -> dict:
    """
    Re-dispatch a dead letter task with safety guards.
    FIX: admin_user_id is now optional — admin.py called with 1 arg → TypeError in v7.
    """
    from app.core.database.engine import AsyncSessionLocal
    from app.models import DeadLetterEntry
    from sqlalchemy import select
    from ..celery_app import celery_app
    from app.core.security.audit import audit_sync, AuditAction

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(DeadLetterEntry).where(DeadLetterEntry.id == entry_id))
        entry = result.scalar_one_or_none()
        if not entry:
            raise ValueError(f"DLQ entry {entry_id} not found")
        if entry.suppressed:
            raise ValueError(f"Entry {entry_id} is suppressed: {entry.suppressed_reason}")
        if entry.replay_count >= settings.DLQ_MAX_REPLAYS:
            entry.suppressed = True
            entry.suppressed_reason = f"Max replays ({settings.DLQ_MAX_REPLAYS}) exceeded"
            await db.commit()
            raise ValueError(f"Entry {entry_id} suppressed after max replays")
        if entry.last_replayed_at:
            backoff = timedelta(seconds=settings.DLQ_REPLAY_BACKOFF_SECONDS)
            if datetime.now(UTC) < entry.last_replayed_at + backoff:
                wait = int((entry.last_replayed_at + backoff - datetime.now(UTC)).total_seconds())
                raise ValueError(f"Replay throttled — wait {wait}s")

        task = celery_app.send_task(
            entry.task_name, args=entry.args or [], kwargs=entry.kwargs or {}, queue=entry.queue
        )
        entry.replay_count += 1
        entry.last_replayed_at = datetime.now(UTC)
        entry.replayed = True
        entry.replayed_at = datetime.now(UTC)
        await db.commit()

        logger.info("DLQ_REPLAY entry=%d attempt=%d new_task=%s admin=%s",
                    entry_id, entry.replay_count, task.id, admin_user_id)
        audit_sync(AuditAction.DLQ_REPLAY, user_id=admin_user_id,
                   detail={"entry_id": entry_id, "attempt": entry.replay_count})
        return {"dispatched": True, "new_celery_task_id": task.id,
                "replay_count": entry.replay_count, "original_task_id": entry.celery_task_id}


def connect_dlq_signal():
    """
    Register the task_failure signal handler.
    Called once from celery_app.py worker_init signal.
    FIX v8: In v7 this function existed but was never called — DLQ was silently broken.
    """
    global _dlq_signal_connected
    if _dlq_signal_connected:
        return  # idempotent

    @task_failure.connect
    def on_task_failure(task_id, exception, traceback, einfo, args, kwargs, **kw):
        sender = kw.get("sender")
        task_name = getattr(sender, "name", "unknown")
        queue = getattr(sender, "queue", "default") or "default"
        retries = getattr(sender.request, "retries", 0) if hasattr(sender, "request") else 0
        max_retries = getattr(sender, "max_retries", settings.JOB_MAX_RETRIES)
        if retries < max_retries:
            return  # still has retries
        error_str = str(exception)
        tb_str = "".join(tb.format_tb(traceback)) if traceback else ""
        asyncio.run(record_dlq_entry(
            celery_task_id=task_id, task_name=task_name, queue=queue,
            args=list(args) if args else [], kwargs=dict(kwargs) if kwargs else {},
            error=error_str, traceback_str=tb_str, retry_count=retries,
        ))

    _dlq_signal_connected = True
    logger.info("DLQ signal handler connected")
