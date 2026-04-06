"""
Dataset Service Phase 1
Constraint: strictly follows the processing contract, dtype canonicalization, and minimal observability.
"""
import uuid
import asyncio
import io
import logging
from typing import Dict, Any, List
import pandas as pd
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.models import User, Dataset, Job
from app.repositories.dataset_repository import dataset_repo
from app.core.exceptions import NotFoundError, ValidationError, DependencyError, DomainError
from app.services.storage import (
    upload_file_async, delete_object_async, generate_upload_key, download_to_df_async
)
from app.core.security.audit import audit, AuditAction
from app.core.security.idempotency import get_or_create_idempotency_key, complete_idempotency_key, fail_idempotency_key
from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

# Strict Dtype Canonicalization
DTYPE_MAPPING = {
    'int64': 'numeric',
    'float64': 'numeric',
    'Int64': 'numeric',
    'Float64': 'numeric',
    'bool': 'categorical',
    'object': 'text',
    'string': 'text',
    'category': 'categorical',
    'datetime64[ns]': 'datetime'
}

def map_pandas_dtype(pd_type) -> str:
    pd_type_str = str(pd_type)
    return DTYPE_MAPPING.get(pd_type_str, 'text')


from app.core.database.engine import engine

async def _process_dataset_schema_async(dataset_id: int):
    # Using local session for async background task
    from sqlalchemy.orm import sessionmaker
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as db:
        ds = await dataset_repo.get(db, id=dataset_id)
        if not ds:
            return
            
        ds.processing_status = 'processing'
        await db.commit()

        start_time = datetime.utcnow()
        success = False
        error_msg = None
        rows_scanned = 0
        schema_json = None
        n_cols = 0
        
        try:
            # Download file byte by byte using Boto3 / aiobotocore
            s3_key = ds.storage_key
            bucket = settings.S3_BUCKET_RAW
            endpoint_url = "http://localhost:9000" if "localhost" in settings.S3_ENDPOINT_URL else settings.S3_ENDPOINT_URL
            
            content = None
            import aioboto3
            session = aioboto3.Session()
            async with session.client('s3', 
                                     endpoint_url=endpoint_url,
                                     aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                                     aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY) as s3:
                response = await s3.get_object(Bucket=bucket, Key=s3_key)
                content = await response["Body"].read()

            if not content:
                raise Exception("Empty S3 content")
                
            encodings = ['utf-8', 'cp1252', 'latin1']
            df = None
            for enc in encodings:
                try:
                    df = pd.read_csv(io.BytesIO(content), nrows=10000, encoding=enc)
                    break
                except UnicodeDecodeError:
                    continue
            
            if df is None:
                raise ValueError("Failed to decode CSV with expected encodings")

            rows_scanned = len(df)
            n_cols = len(df.columns)
            columns_data = []
            
            for col in df.columns:
                series = df[col]
                logical_type = map_pandas_dtype(series.dtype)
                
                col_stats = {
                    "name": str(col),
                    "logical_type": logical_type,
                    "count": int(series.count()),
                    "unique_count": int(series.nunique())
                }
                
                if logical_type == 'numeric':
                    # Handle NaNs safely
                    min_val = series.min()
                    max_val = series.max()
                    col_stats["min"] = float(min_val) if not pd.isna(min_val) else None
                    col_stats["max"] = float(max_val) if not pd.isna(max_val) else None
                    
                columns_data.append(col_stats)
                
            schema_json = {"columns": columns_data}
            success = True

        except Exception as e:
            logger.exception("Failed to process dataset schema")
            error_msg = str(e)
            
        end_time = datetime.utcnow()
        duration_ms = (end_time - start_time).total_seconds() * 1000
        
        log_entry = {
            "success": success,
            "rows_scanned": rows_scanned,
            "duration_ms": duration_ms,
            "error_message": error_msg
        }

        # Update dataset
        ds.n_rows = rows_scanned if success else 0
        ds.n_cols = n_cols if success else 0
        ds.schema_json = schema_json
        ds.profiling_log = log_entry
        ds.processing_status = 'completed' if success else 'failed'
        
        await db.commit()


class DatasetService:
    def __init__(self, db):
        self.db = db

    async def upload_dataset(
        self,
        user: User,
        content: bytes,
        filename: str,
        idem_key: str | None = None,
        request_for_audit: Any = None
    ) -> Dict[str, Any]:
        
        if not content:
            raise ValidationError("File is empty")
            
        ext = filename.rsplit(".", 1)[-1].lower()
        if ext not in settings.ALLOWED_EXTENSIONS:
            if idem_key: await fail_idempotency_key(self.db, user.id, idem_key)
            raise ValidationError(f"Only CSV files allowed. Got: .{ext}")

        s3_key = generate_upload_key(user.id, filename)
        try:
            await upload_file_async(content, s3_key, settings.S3_BUCKET_RAW)
        except Exception as e:
            if idem_key: await fail_idempotency_key(self.db, user.id, idem_key)
            raise DependencyError(f"Storage unavailable: {e}")

        dataset = Dataset(
            user_id=user.id, name=filename, original_filename=filename,
            storage_key=s3_key, n_rows=0, n_cols=0,
            file_size_bytes=len(content), processing_status="uploaded",
        )
        self.db.add(dataset)
        await self.db.flush()
        await self.db.refresh(dataset)
        await self.db.commit()

        asyncio.create_task(_process_dataset_schema_async(dataset.id))

        await audit(self.db, AuditAction.DATASET_UPLOAD, user_id=user.id,
                    resource_type="dataset", resource_id=dataset.id,
                    detail={"filename": filename}, request=request_for_audit)

        result = {"id": dataset.id, "name": dataset.name, "original_filename": dataset.original_filename,
                  "n_rows": dataset.n_rows, "n_cols": dataset.n_cols, "file_size_bytes": dataset.file_size_bytes,
                  "processing_status": dataset.processing_status, "created_at": dataset.created_at}

        if idem_key:
            await complete_idempotency_key(self.db, user.id, idem_key, 202, result)
            await self.db.commit()

        return result

    async def list_datasets(self, user_id: int, offset: int, limit: int):
        total = await dataset_repo.count_by_user(self.db, user_id)
        items = await dataset_repo.list_by_user(self.db, user_id, offset, limit)
        return items, total

    async def get_dataset(self, dataset_id: int, user_id: int) -> Dataset:
        ds = await dataset_repo.get_by_user(self.db, dataset_id, user_id)
        if not ds:
            raise NotFoundError("Dataset not found")
        return ds

    async def delete_dataset(self, dataset_id: int, user_id: int, request_for_audit: Any = None) -> None:
        ds = await self.get_dataset( dataset_id, user_id)
        await delete_object_async(ds.storage_key, settings.S3_BUCKET_RAW)
        await dataset_repo.remove(self.db, id=ds.id)
        await audit(self.db, AuditAction.DATASET_DELETE, user_id=user_id,
                    resource_type="dataset", resource_id=ds.id, detail={"name": ds.name}, request=request_for_audit)

