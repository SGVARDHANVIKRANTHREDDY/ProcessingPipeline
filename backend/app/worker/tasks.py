"""
Celery Tasks v10.

FIX: S3 output side-effect idempotency.
  v9: output_key = f"{prefix}/{uuid.uuid4().hex}.csv" — random UUID each call.
  If Celery retries after S3 upload but before DB commit → orphan S3 objects.

  v10: output_key = deterministic_output_key(user_id, execution_id)
  = f"users/{user_id}/outputs/exec-{execution_id}.csv"

  S3 PUT is idempotent: uploading to the same key overwrites the same object.
  Retry → same key → same content written → no duplicate S3 objects.
  Execution check: if status='completed' → skip all side effects (S3 + DB).
"""
import logging
import asyncio
import socket
from datetime import datetime, timezone, timedelta
from celery import Task
from celery.exceptions import SoftTimeLimitExceeded

from app.core.celery import celery_app
from app.core.config import get_settings
from app.services.storage import download_to_df, upload_csv_from_df_sync
from app.services.profiler import profile_dataframe, generate_smart_suggestions
from app.services.executor import execute_pipeline
from app.services.validator import validate_pipeline_steps, detect_schema_mismatch
from app.core.security.audit import audit_sync, AuditAction
from app.core.security.idempotency import deterministic_output_key
from app.core.middleware.tracing import extract_trace_from_celery_kwargs

settings = get_settings()
logger = logging.getLogger(__name__)
UTC = timezone.utc
WORKER_ID = f"{socket.gethostname()}-{__import__('os').getpid()}"


class DBTask(Task):
    abstract = True
    def run_in_loop(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


@celery_app.task(bind=True, base=DBTask, name="app.worker.tasks.profile_dataset_task",
                 queue="profiling", max_retries=settings.JOB_MAX_RETRIES,
                 default_retry_delay=settings.JOB_RETRY_BACKOFF, acks_late=True)
def profile_dataset_task(self, dataset_id: int, user_id: int, job_id: int, **kwargs):
    trace_id, _, _ = extract_trace_from_celery_kwargs(kwargs)

    async def _run():
        from app.core.database.engine import AsyncSessionLocal
        from app.models import Dataset, Job
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            try:
                r = await self.db.execute(select(Job).where(Job.id == job_id))
                job = r.scalar_one_or_none()
                if job and job.status == "completed":
                    return job.result or {}
                if job:
                    job.status = "running"; job.celery_task_id = self.request.id
                    job.started_at = datetime.now(UTC)
                await self.db.flush()

                r = await self.db.execute(select(Dataset).where(Dataset.id == dataset_id, Dataset.user_id == user_id))
                ds = r.scalar_one_or_none()
                if not ds: raise ValueError(f"Dataset {dataset_id} not found")

                df = await asyncio.to_thread(download_to_df, ds.s3_key, settings.S3_BUCKET_RAW)
                profile = profile_dataframe(df)
                suggestions = generate_smart_suggestions(profile)

                ds.profile = profile; ds.headers = list(df.columns)
                ds.row_count = profile.get("row_count", ds.row_count)
                ds.col_count = profile.get("col_count", ds.col_count)
                ds.profiling_status = "completed"
                if job:
                    job.status = "completed"
                    job.result = {"profile": profile, "suggestions": suggestions}
                    job.progress = 100; job.completed_at = datetime.now(UTC)
                await self.db.commit()
                audit_sync(AuditAction.DATASET_PROFILED, user_id=user_id,
                           detail={"dataset_id": dataset_id, "trace_id": trace_id})
                return {"profile": profile, "suggestions": suggestions}
            except Exception:
                await self.db.rollback()
                async with AsyncSessionLocal() as db2:
                    from sqlalchemy import select as sel
                    r2 = await db2.execute(sel(Job).where(Job.id == job_id))
                    j2 = r2.scalar_one_or_none()
                    if j2 and j2.status != "completed":
                        j2.status = "failed"; j2.completed_at = datetime.now(UTC)
                    await db2.commit()
                raise

    try:
        return self.run_in_loop(_run())
    except SoftTimeLimitExceeded: raise
    except Exception as exc:
        logger.exception("[TASK:%s] Profiling failed: %s", self.request.id, exc)
        raise self.retry(exc=exc, countdown=settings.JOB_RETRY_BACKOFF)


@celery_app.task(bind=True, base=DBTask, name="app.worker.tasks.execute_pipeline_task",
                 queue="execution", max_retries=settings.JOB_MAX_RETRIES,
                 default_retry_delay=settings.JOB_RETRY_BACKOFF, acks_late=True)
def execute_pipeline_task(self, execution_id: int, pipeline_id: int, dataset_id: int,
                           user_id: int, job_id: int, steps: list[dict], **kwargs):
    trace_id, _, _ = extract_trace_from_celery_kwargs(kwargs)

    async def _run():
        from app.core.database.engine import AsyncSessionLocal
        from app.models import Dataset, Job, PipelineExecution
        from sqlalchemy import select, update

        async with AsyncSessionLocal() as db:
            try:
                r = await self.db.execute(select(PipelineExecution).where(PipelineExecution.id == execution_id))
                ex = r.scalar_one_or_none()
                # Exactly-once: completed execution → idempotent return
                if ex and ex.status == "completed":
                    logger.info("[TASK:%s] Execution %d already completed — skip", self.request.id, execution_id)
                    return {"status": ex.status, "output_row_count": ex.output_row_count, "cached": True}
                if ex and ex.status == "running" and ex.locked_by and ex.locked_by != WORKER_ID:
                    return {"skipped": True, "reason": "locked_by_other_worker"}

                lock_result = await self.db.execute(
                    update(PipelineExecution)
                    .where(PipelineExecution.id == execution_id, PipelineExecution.status == "pending")
                    .values(locked_by=WORKER_ID, locked_at=datetime.now(UTC), status="running")
                    .returning(PipelineExecution.id)
                )
                if lock_result.scalar_one_or_none() is None:
                    return {"skipped": True, "reason": "lock_failed"}

                r = await self.db.execute(select(Job).where(Job.id == job_id))
                job = r.scalar_one_or_none()
                if job:
                    job.status = "running"; job.celery_task_id = self.request.id
                    job.started_at = datetime.now(UTC)
                await self.db.flush()

                r = await self.db.execute(select(Dataset).where(Dataset.id == dataset_id, Dataset.user_id == user_id))
                ds = r.scalar_one_or_none()
                if not ds: raise ValueError(f"Dataset {dataset_id} not found")

                df = await asyncio.to_thread(download_to_df, ds.s3_key, settings.S3_BUCKET_RAW)
                cols = list(df.columns)
                validation = validate_pipeline_steps(steps, cols)
                if validation["has_hard_errors"]:
                    raise ValueError(f"Validation: {validation['errors']}")
                schema_warnings = detect_schema_mismatch(steps, cols)

                report, result_df = execute_pipeline(steps, df)

                # FIX v10: deterministic S3 key — idempotent side effect
                output_key = None
                if report["status"] in ("success", "partial") and len(result_df) > 0:
                    output_key = deterministic_output_key(user_id, execution_id)
                    await asyncio.to_thread(
                        upload_csv_from_df_sync, result_df, output_key, settings.S3_BUCKET_OUTPUT
                    )

                r = await self.db.execute(select(PipelineExecution).where(PipelineExecution.id == execution_id))
                ex = r.scalar_one_or_none()
                if ex:
                    ex.status = report["status"]; ex.report = report
                    ex.output_s3_key = output_key; ex.output_row_count = len(result_df)
                    ex.duration_ms = report.get("total_ms"); ex.schema_warnings = schema_warnings or None
                    ex.completed_at = datetime.now(UTC); ex.locked_by = None; ex.locked_at = None
                if job:
                    job.status = "completed"
                    job.result = {"status": report["status"], "output_row_count": len(result_df)}
                    job.progress = 100; job.completed_at = datetime.now(UTC)

                await self.db.commit()
                audit_sync(AuditAction.PIPELINE_EXECUTE, user_id=user_id,
                           detail={"execution_id": execution_id, "status": report["status"],
                                   "rows_in": report["input_count"], "rows_out": report["output_count"],
                                   "trace_id": trace_id})
                return {"status": report["status"], "output_row_count": len(result_df)}

            except Exception as exc:
                await self.db.rollback()
                async with AsyncSessionLocal() as db2:
                    from sqlalchemy import select as sel
                    r2 = await db2.execute(sel(PipelineExecution).where(PipelineExecution.id == execution_id))
                    ex2 = r2.scalar_one_or_none()
                    if ex2 and ex2.status not in ("completed", "failed"):
                        ex2.status = "failed"; ex2.error_detail = str(exc)[:1000]
                        ex2.completed_at = datetime.now(UTC); ex2.locked_by = None; ex2.locked_at = None
                    r3 = await db2.execute(sel(Job).where(Job.id == job_id))
                    j3 = r3.scalar_one_or_none()
                    if j3 and j3.status not in ("completed", "failed"):
                        j3.status = "failed"; j3.error = str(exc)[:1000]; j3.completed_at = datetime.now(UTC)
                    await db2.commit()
                raise

    try:
        return self.run_in_loop(_run())
    except SoftTimeLimitExceeded: raise
    except Exception as exc:
        logger.exception("[TASK:%s] Execution failed: %s", self.request.id, exc)
        raise self.retry(exc=exc, countdown=settings.JOB_RETRY_BACKOFF)


@celery_app.task(name="app.worker.tasks.recover_stale_executions", queue="default")
def recover_stale_executions():
    async def _run():
        from app.core.database.engine import AsyncSessionLocal
        from app.models import PipelineExecution
        from sqlalchemy import select
        threshold = datetime.now(UTC) - timedelta(seconds=settings.JOB_HARD_TIME_LIMIT)
        async with AsyncSessionLocal() as db:
            r = await self.db.execute(
                select(PipelineExecution).where(
                    PipelineExecution.status == "running",
                    PipelineExecution.locked_at < threshold,
                    PipelineExecution.locked_by != None,
                )
            )
            stale = r.scalars().all()
            for ex in stale:
                logger.warning("STALE exec=%d worker=%s", ex.id, ex.locked_by)
                ex.status = "failed"; ex.error_detail = f"Worker {ex.locked_by} crashed"
                ex.locked_by = None; ex.locked_at = None; ex.completed_at = datetime.now(UTC)
            if stale: await self.db.commit()
    asyncio.run(_run())


@celery_app.task(name="app.worker.tasks.cleanup_expired_idempotency", queue="default")
def cleanup_expired_idempotency():
    async def _run():
        from app.core.database.engine import AsyncSessionLocal
        from app.core.security.idempotency import cleanup_expired_keys
        async with AsyncSessionLocal() as db:
            count = await cleanup_expired_keys(self.db); await self.db.commit()
            if count: logger.info("Purged %d expired idempotency keys", count)
    asyncio.run(_run())


@celery_app.task(name="app.worker.tasks.cleanup_old_login_attempts", queue="default")
def cleanup_old_login_attempts():
    async def _run():
        from app.core.database.engine import AsyncSessionLocal
        from app.models import LoginAttempt
        from sqlalchemy import delete
        cutoff = datetime.now(UTC) - timedelta(days=30)
        async with AsyncSessionLocal() as db:
            r = await self.db.execute(delete(LoginAttempt).where(LoginAttempt.attempted_at < cutoff))
            if r.rowcount: logger.info("Purged %d old login attempts", r.rowcount)
            await self.db.commit()
    asyncio.run(_run())
