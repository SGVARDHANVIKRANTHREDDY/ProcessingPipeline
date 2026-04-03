"""
Dataset Service v10.
Constraint: Must accept domain/Pydantic objects, return domain objects, and never touch HTTP details.
"""
import uuid
import asyncio
import io
from typing import Dict, Any, List

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, Dataset, Job
from app.repositories.dataset_repository import dataset_repo
from app.core.exceptions import NotFoundError, ValidationError, DependencyError, DomainError
from app.services.storage import (
    upload_file_async, delete_object_async, generate_upload_key, download_to_df_async
)
from app.services.profiler import generate_smart_suggestions, detect_anomalies
from app.services.tasks import profile_dataset_task
from app.core.security.csv_sanitizer import validate_and_sanitize_csv, SecurityError
from app.core.security.audit import audit, AuditAction
from app.core.security.idempotency import get_or_create_idempotency_key, complete_idempotency_key, fail_idempotency_key
from app.core.config import get_settings

settings = get_settings()

class DatasetService:
    def __init__(self, db):
        self.db = db

    async def upload_dataset(
        self,
        user: User,
        content: bytes,
        filename: str,
        idem_key: str | None,
        request_for_audit: Any = None
    ) -> Dict[str, Any]:
        
        if not content:
            raise ValidationError("File is empty")
            
        ext = filename.rsplit(".", 1)[-1].lower()
        if ext not in settings.ALLOWED_EXTENSIONS:
            if idem_key: await fail_idempotency_key(self.db, user.id, idem_key)
            await audit(self.db, AuditAction.SECURITY_FILE_REJECTED, user_id=user.id,
                        detail={"filename": filename, "reason": "bad_extension"}, request=request_for_audit)
            raise ValidationError(f"Only CSV files allowed. Got: .{ext}")

        try:
            sanitized = validate_and_sanitize_csv(
                content,
                max_columns=settings.CSV_MAX_COLUMNS,
                max_cell_length=settings.CSV_MAX_CELL_LENGTH,
                max_rows=settings.CSV_MAX_ROWS,
                max_column_name_length=settings.CSV_MAX_COLUMN_NAME_LENGTH,
            )
        except SecurityError as e:
            quarantine_key = f"quarantine/{user.id}/{uuid.uuid4().hex}.csv"
            try: 
                await upload_file_async(content, quarantine_key, settings.S3_BUCKET_QUARANTINE)
            except Exception: 
                pass
            await audit(self.db, AuditAction.DATASET_QUARANTINED, user_id=user.id,
                        detail={"filename": filename, "error": str(e)}, request=request_for_audit)
            if idem_key: await fail_idempotency_key(self.db, user.id, idem_key)
            raise ValidationError(str(e))

        s3_key = generate_upload_key(user.id, filename)
        buf = io.BytesIO(); sanitized.df.to_csv(buf, index=False); buf.seek(0)
        try:
            await upload_file_async(buf.getvalue(), s3_key, settings.S3_BUCKET_RAW)
        except RuntimeError as e:
            if idem_key: await fail_idempotency_key(self.db, user.id, idem_key)
            raise DependencyError("Storage temporarily unavailable")
        except Exception as e:
            if idem_key: await fail_idempotency_key(self.db, user.id, idem_key)
            raise DependencyError(f"Storage unavailable: {e}")

        dataset = Dataset(
            user_id=user.id, name=filename, original_filename=filename,
            s3_key=s3_key, row_count=len(sanitized.df), col_count=len(sanitized.df.columns),
            file_size_bytes=len(content), profiling_status="pending", file_hash=sanitized.file_hash,
        )
        self.self.db.add(dataset)
        await self.self.db.flush()
        await self.self.db.refresh(dataset)

        job = Job(user_id=user.id, job_type="profile", payload={"dataset_id": dataset.id}, status="pending")
        self.self.db.add(job)
        await self.self.db.flush()
        await self.self.db.refresh(job)

        task = profile_dataset_task.apply_async(
            args=[dataset.id, user.id, job.id],
            task_id=f"profile-{dataset.id}-{uuid.uuid4().hex[:8]}",
        )
        job.celery_task_id = task.id
        await self.self.db.commit()

        await audit(self.db, AuditAction.DATASET_UPLOAD, user_id=user.id,
                    resource_type="dataset", resource_id=dataset.id,
                    detail={"filename": filename, "rows": len(sanitized.df),
                            "hash": sanitized.file_hash[:12]}, request=request_for_audit)

        result = {"dataset_id": dataset.id, "job_id": job.id, "celery_task_id": task.id,
                  "warnings": sanitized.warnings}

        if idem_key:
            await complete_idempotency_key(self.db, user.id, idem_key, 202, result)
            await self.self.db.commit()

        return result

    async def list_datasets(self, user_id: int, page: int, page_size: int) -> Dict[str, Any]:
        page_size = min(page_size, 100)
        offset = (page - 1) * page_size
        total = await dataset_repo.count_by_user(self.db, user_id)
        items = await dataset_repo.list_by_user(self.db, user_id, offset, page_size)
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    async def get_dataset(self, dataset_id: int, user_id: int) -> Dataset:
        ds = await dataset_repo.get_by_user(self.db, dataset_id, user_id)
        if not ds:
            raise NotFoundError("Dataset not found")
        return ds

    async def get_suggestions(self, dataset_id: int, user_id: int) -> List[Dict[str, Any]]:
        ds = await self.get_dataset( dataset_id, user_id)
        return generate_smart_suggestions(ds.profile) if ds.profile else []

    async def compare_datasets(self, id1: int, id2: int, user_id: int) -> Dict[str, Any]:
        ds1 = await dataset_repo.get(self.db, id=id1)
        ds2 = await dataset_repo.get(self.db, id=id2)
        if not ds1 or not ds2 or ds1.user_id != user_id or ds2.user_id != user_id:
            raise NotFoundError("One or both datasets not found or unauthorized")
            
        def _extract_stats(ds: Dataset):
            if not ds.profile:
                return {"ready": False}
            p = ds.profile
            return {
                "ready": True, "name": ds.name, "health_score": p.health_score,
                "row_count": p.row_count, "col_count": p.col_count,
                "memory_usage": p.memory_usage_mb, "missing_cells": p.missing_cells,
                "duplicate_rows": p.duplicate_rows,
            }
        return {"dataset1": _extract_stats(ds1), "dataset2": _extract_stats(ds2)}

    async def get_anomalies(self, dataset_id: int, user_id: int) -> Dict[str, Any]:
        ds = await self.get_dataset( dataset_id, user_id)
        df = await download_to_df_async(ds.s3_key, settings.S3_BUCKET_RAW)
        anomalies = detect_anomalies(df)
        return {"anomalies": anomalies, "total_scanned": len(df)}

    async def delete_dataset(self, dataset_id: int, user_id: int, request_for_audit: Any = None) -> None:
        ds = await self.get_dataset( dataset_id, user_id)
        await delete_object_async(ds.s3_key, settings.S3_BUCKET_RAW)
        await dataset_repo.remove(self.db, id=ds.id)
        await audit(self.db, AuditAction.DATASET_DELETE, user_id=user_id,
                    resource_type="dataset", resource_id=ds.id, detail={"name": ds.name}, request=request_for_audit)

