import re
import sys

with open('app/worker/tasks.py', 'r') as f:
    content = f.read()

new_func = """@celery_app.task(bind=True, base=DBTask, name="app.worker.tasks.execute_pipeline_task",
                 queue="execution", max_retries=settings.JOB_MAX_RETRIES,
                 default_retry_delay=settings.JOB_RETRY_BACKOFF, acks_late=True)
def execute_pipeline_task(self, execution_id: int, pipeline_id: int, dataset_id: int,
                           user_id: int, job_id: int, steps: list[dict], **kwargs):
    trace_id, _, _ = extract_trace_from_celery_kwargs(kwargs)

    async def _run():
        from app.core.database.engine import AsyncSessionLocal
        from app.services.pipeline_engine import execute_pipeline_in_session

        async with AsyncSessionLocal() as db:
            await execute_pipeline_in_session(db, execution_id)
            
            audit_sync(AuditAction.PIPELINE_EXECUTE, user_id=user_id,
                       detail={"execution_id": execution_id, "trace_id": trace_id})
            
            return {"execution_id": execution_id, "status": "processed"}

    try:
        return self.run_in_loop(_run())
    except SoftTimeLimitExceeded: raise
    except Exception as exc:
        logger.exception("[TASK:%s] Execution failed: %s", self.request.id, exc)
        raise self.retry(exc=exc, countdown=settings.JOB_RETRY_BACKOFF)
"""

parts = content.split('@celery_app.task(bind=True, base=DBTask, name="app.worker.tasks.execute_pipeline_task"')
if len(parts) > 1:
    old_prefix = parts[0]
    rest = parts[1]
    
    # Try to find the next @ decorator which would indicate another task
    next_task_idx = rest.find('\n@')
    
    if next_task_idx != -1:
        new_content = old_prefix + new_func + rest[next_task_idx:]
    else:
        new_content = old_prefix + new_func
        
    with open('app/worker/tasks.py', 'w') as f:
        f.write(new_content)
    print("Tasks file updated successfully!")
else:
    print("Could not find the target task to replace.")
