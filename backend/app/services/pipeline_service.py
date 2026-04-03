"""
Pipeline Service
Constraint: Must accept domain/Pydantic objects, return domain objects, and never touch HTTP details.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, Pipeline, PipelineExecution, Job
from app.repositories.pipeline_repository import pipeline_repo, execution_repo
from app.repositories.dataset_repository import dataset_repo
from app.core.exceptions import NotFoundError, ValidationError, DependencyError, DomainError
from app.core.security.audit import audit, AuditAction
from app.services.storage import get_signed_url_async
from app.core.security.idempotency import (
    get_or_create_idempotency_key, complete_idempotency_key, fail_idempotency_key, hash_request_body,
    claim_execution_dedup, complete_execution_dedup
)
from app.services.ai_translator import translate_to_steps
from app.services.validator import validate_ai_output, detect_schema_mismatch
from app.worker.tasks import execute_pipeline_task
from app.core.middleware.tracing import inject_trace_into_celery_kwargs
from app.core.config import get_settings

settings = get_settings()

class PipelineService:
    def __init__(self, db):
        self.db = db

    async def create_pipeline(self, user_id: int, body: Any, request_for_audit: Any = None) -> Pipeline:
        steps = [s.model_dump() for s in body.steps]
        pipe = Pipeline(user_id=user_id, dataset_id=body.dataset_id, name=body.name, steps=steps)
        self.db.add(pipe)
        await self.db.flush()
        await self.db.refresh(pipe)
        await audit(self.db, AuditAction.PIPELINE_CREATE, user_id=user_id,
                    resource_type="pipeline", resource_id=pipe.id,
                    detail={"name": pipe.name, "steps": len(steps)}, request=request_for_audit)
        return pipe

    async def list_pipelines(self, user_id: int, page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        page_size = min(page_size, 100)
        offset = (page - 1) * page_size
        total = await pipeline_repo.count_by_user(self.db, user_id)
        items = await pipeline_repo.list_by_user(self.db, user_id, offset, page_size)
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    async def get_pipeline(self, pipeline_id: int, user_id: int) -> Pipeline:
        pipe = await pipeline_repo.get_by_user(self.db, pipeline_id, user_id)
        if not pipe:
            raise NotFoundError("Pipeline not found")
        return pipe

    async def update_pipeline(self, pipeline_id: int, user_id: int, body: Any, request_for_audit: Any = None) -> Pipeline:
        pipe = await self.get_pipeline( pipeline_id, user_id)
        if body.name is not None: pipe.name = body.name
        if body.steps is not None: pipe.steps = [s.model_dump() for s in body.steps]
        await self.db.flush()
        await self.db.refresh(pipe)
        await audit(self.db, AuditAction.PIPELINE_UPDATE, user_id=user_id,
                    resource_type="pipeline", resource_id=pipe.id, request=request_for_audit)
        return pipe

    async def delete_pipeline(self, pipeline_id: int, user_id: int, request_for_audit: Any = None) -> None:
        pipe = await self.get_pipeline( pipeline_id, user_id)
        await audit(self.db, AuditAction.PIPELINE_DELETE, user_id=user_id,
                    resource_type="pipeline", resource_id=pipe.id, request=request_for_audit)
        await pipeline_repo.remove(self.db, id=pipe.id)

    async def translate_prompt(self, prompt: str, dataset_id: Optional[int], user_id: int, request_for_audit: Any = None) -> Dict[str, Any]:
        columns = None
        if dataset_id:
            ds = await dataset_repo.get_by_user(self.db, dataset_id, user_id)
            if ds and ds.headers:
                columns = ds.headers
        raw = await translate_to_steps(prompt, columns)
        validated = validate_ai_output(raw, columns)
        await audit(self.db, AuditAction.PIPELINE_TRANSLATE, user_id=user_id,
                    detail={"prompt": prompt[:100], "steps_accepted": len(validated["steps"])}, request=request_for_audit)
        return validated

    async def execute_pipeline(self, pipeline_id: int, user_id: int, body: Any, idem_key: str, body_bytes: bytes, request_for_audit: Any = None) -> Dict[str, Any]:
        pipe = await self.get_pipeline( pipeline_id, user_id)
        ds = await dataset_repo.get_by_user(self.db, body.dataset_id, user_id)
        if not ds:
            raise NotFoundError("Dataset not found")

        idem_result = await get_or_create_idempotency_key(
            db, user_id, idem_key, f"/pipelines/{pipeline_id}/execute", hash_request_body(body_bytes)
        )
        if idem_result["action"] == "replay":
            return idem_result["body"]

        try:
            dedup_result = await claim_execution_dedup(self.db, user_id, pipeline_id, body.dataset_id, pipe.steps)
            if dedup_result["action"] == "duplicate":
                result = {
                    "execution_id": dedup_result.get("existing_execution_id"),
                    "job_id": None,
                    "status": "deduplicated",
                    "message": dedup_result.get("message"),
                }
                await complete_idempotency_key(self.db, user_id, idem_key, 202, result)
                return result

            schema_warnings = detect_schema_mismatch(pipe.steps, ds.headers or [])

            execution = PipelineExecution(
                pipeline_id=pipeline_id, input_dataset_id=body.dataset_id,
                status="pending", schema_warnings=schema_warnings or None,
                idempotency_key=idem_key,
            )
            self.db.add(execution)
            await self.db.flush()
            await self.db.refresh(execution)

            job = Job(user_id=user_id, job_type="execute",
                      payload={"pipeline_id": pipeline_id, "dataset_id": body.dataset_id,
                               "execution_id": execution.id}, status="pending")
            self.db.add(job)
            await self.db.flush()
            await self.db.refresh(job)
            await self.db.commit()

            deterministic_task_id = f"exec-{execution.id}"
            task = execute_pipeline_task.apply_async(
                args=[execution.id, pipeline_id, body.dataset_id, user_id, job.id, pipe.steps],
                kwargs=inject_trace_into_celery_kwargs({}),
                task_id=deterministic_task_id,
            )
            execution.job_id = task.id
            job.celery_task_id = task.id
            await self.db.commit()

            result = {"execution_id": execution.id, "job_id": job.id, "celery_task_id": task.id, "status": "pending"}
            await complete_idempotency_key(self.db, user_id, idem_key, 202, result)
            await complete_execution_dedup(self.db, user_id, pipeline_id, body.dataset_id, pipe.steps, execution.id)
            await self.db.commit()

            await audit(self.db, AuditAction.PIPELINE_EXECUTE, user_id=user_id,
                        resource_type="pipeline", resource_id=pipeline_id,
                        detail={"execution_id": execution.id, "dataset_id": body.dataset_id, "idem_key": idem_key[:8]}, request=request_for_audit)
            return result

        except Exception as e:
            await fail_idempotency_key(self.db, user_id, idem_key)
            raise DependencyError(f"Failed to execute pipeline: {str(e)}")

    async def get_activity_metrics(self, user_id: int) -> List[Dict[str, Any]]:
        rows = await execution_repo.get_activity_metrics(self.db, user_id)
        row_map = {row.d.strftime("%Y-%m-%d"): {"executions": row.total, "success": int(row.success or 0)} for row in rows}

        out = []
        for i in range(13, -1, -1):
            d = (datetime.utcnow() - timedelta(days=i)).strftime("%Y-%m-%d")
            if d in row_map:
                out.append({"date": d, "executions": row_map[d]["executions"], "success": row_map[d]["success"]})
            else:
                out.append({"date": d, "executions": 0, "success": 0})
        return out

    async def list_executions(self, pipeline_id: int, user_id: int) -> List[Any]:
        await self.get_pipeline( pipeline_id, user_id)
        execs = await execution_repo.list_by_pipeline(self.db, pipeline_id)
        out = []
        from app.schemas import ExecutionOut
        for ex in execs:
            d = ExecutionOut.model_validate(ex)
            if ex.output_s3_key and ex.status in ("success", "partial"):
                try: d.download_url = await get_signed_url_async(ex.output_s3_key, settings.S3_BUCKET_OUTPUT)
                except: pass
            out.append(d)
        return out

    async def get_execution(self, pipeline_id: int, execution_id: int, user_id: int) -> Any:
        await self.get_pipeline( pipeline_id, user_id)
        ex = await execution_repo.get_by_pipeline(self.db, pipeline_id, execution_id)
        if not ex:
            raise NotFoundError("Execution not found")
        from app.schemas import ExecutionOut
        d = ExecutionOut.model_validate(ex)
        if ex.output_s3_key and ex.status in ("success", "partial"):
            try: d.download_url = await get_signed_url_async(ex.output_s3_key, settings.S3_BUCKET_OUTPUT)
            except: pass
        return d

    async def fork_pipeline(self, pipeline_id: int, user_id: int, request_for_audit: Any = None) -> Pipeline:
        old = await self.get_pipeline( pipeline_id, user_id)
        new_pipe = Pipeline(
            user_id=user_id,
            dataset_id=old.dataset_id,
            name=f"{old.name} (Fork)",
            steps=old.steps[:]
        )
        self.db.add(new_pipe)
        await self.db.flush()
        await self.db.refresh(new_pipe)
        await audit(self.db, AuditAction.PIPELINE_CREATE, user_id=user_id,
                    resource_type="pipeline", resource_id=new_pipe.id,
                    detail={"forked_from": pipeline_id}, request=request_for_audit)
        return new_pipe

