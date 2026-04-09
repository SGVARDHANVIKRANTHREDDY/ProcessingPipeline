"""
Phase 3 Pipeline Engine
Deterministic, composable pipelines strictly using in-memory pandas DataFrames.
Files > 50MB will throw a fast failure in Phase 3.
"""
import logging
import json
import hashlib
from typing import Any, Dict
import pandas as pd
from uuid import UUID

from collections import OrderedDict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import PipelineExecution, Pipeline, Dataset, Job
from app.core.exceptions import DependencyError
from app.services.storage import download_to_df, upload_csv_from_df_sync
from app.core.config import get_settings

settings = get_settings()

logger = logging.getLogger(__name__)

# Config: 50MB max file size for the in-memory engine (Phase 3 limit)
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024

class DatasetTooLargeError(Exception):
    pass

class ActionRegistry:
    @staticmethod
    def _get_numeric_cols(df: pd.DataFrame, columns: list[str] | None) -> list[str]:
        all_numeric = df.select_dtypes(include=['number']).columns.tolist()
        if columns:
            return [c for c in columns if c in all_numeric]
        return all_numeric

    @staticmethod
    def apply_drop_nulls(df: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
        cols = params.get("columns")
        if cols:
            existing_cols = [c for c in cols if c in df.columns]
            return df.dropna(subset=existing_cols)
        return df.dropna()

    @staticmethod
    def apply_fill_nulls(df: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
        method = params.get("method", "zero")
        cols = ActionRegistry._get_numeric_cols(df, params.get("columns"))
        if not cols:
            return df
            
        df_out = df.copy()
        if method == "mean":
            for col in cols:
                df_out[col] = df_out[col].fillna(df_out[col].mean())
        elif method == "median":
            for col in cols:
                df_out[col] = df_out[col].fillna(df_out[col].median())
        else:
            for col in cols:
                df_out[col] = df_out[col].fillna(0)
        return df_out

    @staticmethod
    def apply_remove_outliers(df: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
        cols = ActionRegistry._get_numeric_cols(df, params.get("columns"))
        if not cols:
            return df
            
        df_out = df.copy()
        for col in cols:
            q1 = df_out[col].quantile(0.25)
            q3 = df_out[col].quantile(0.75)
            iqr = q3 - q1
            lo = q1 - 1.5 * iqr
            hi = q3 + 1.5 * iqr
            df_out = df_out[(df_out[col] >= lo) & (df_out[col] <= hi)]
        return df_out

    @staticmethod
    def apply_normalize(df: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
        cols = ActionRegistry._get_numeric_cols(df, params.get("columns"))
        if not cols:
            return df
            
        df_out = df.copy()
        for col in cols:
            mn = df_out[col].min()
            mx = df_out[col].max()
            rng = mx - mn
            if rng == 0:
                df_out[col] = 0.0
            else:
                df_out[col] = (df_out[col] - mn) / rng
        return df_out

    @staticmethod
    def apply_standardize(df: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
        cols = ActionRegistry._get_numeric_cols(df, params.get("columns"))
        if not cols:
            return df
            
        df_out = df.copy()
        for col in cols:
            mu = df_out[col].mean()
            sigma = df_out[col].std()
            if sigma == 0:
                df_out[col] = 0.0
            else:
                df_out[col] = (df_out[col] - mu) / sigma
        return df_out

    @staticmethod
    def apply_filter_rows(df: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
        # params JSON should contain condition strings if extended, but for phase 3:
        # we simplified the registry. For now returns unmodified to avoid eval.
        return df
        
    @staticmethod
    def apply_select_columns(df: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
        cols = params.get("columns")
        if not cols:
            return df
        existing_cols = [c for c in cols if c in df.columns]
        return df[existing_cols].copy()

    @staticmethod
    def apply_rename_columns(df: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
        mapping = params.get("mapping", {})
        if not mapping:
            return df
        return df.rename(columns=mapping)

    @staticmethod
    def apply_drop_columns(df: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
        cols = params.get("columns")
        if not cols:
            return df
        existing_cols = [c for c in cols if c in df.columns]
        return df.drop(columns=existing_cols)


# Action mapping
REGISTRY = {
    "drop_nulls": ActionRegistry.apply_drop_nulls,
    "fill_nulls": ActionRegistry.apply_fill_nulls,
    "remove_outliers": ActionRegistry.apply_remove_outliers,
    "normalize": ActionRegistry.apply_normalize,
    "standardize": ActionRegistry.apply_standardize,
    "filter_rows": ActionRegistry.apply_filter_rows,
    "select_columns": ActionRegistry.apply_select_columns,
    "rename_columns": ActionRegistry.apply_rename_columns,
    "drop_columns": ActionRegistry.apply_drop_columns,
}


async def execute_pipeline_in_session(db: AsyncSession, execution_id: int):
    # 1. Load execution, pipeline, steps, and dataset
    stmt = (
        select(PipelineExecution)
        .options(
            selectinload(PipelineExecution.pipeline).selectinload(Pipeline.pipeline_steps),
            selectinload(PipelineExecution.input_dataset)
        )
        .where(PipelineExecution.id == execution_id)
    )
    result = await db.execute(stmt)
    execution = result.scalar_one_or_none()
    
    if not execution:
        logger.error(f"Execution {execution_id} not found")
        return

    execution.status = "running"
    await db.commit()

    try:
        pipeline = execution.pipeline
        dataset = execution.input_dataset

        if dataset.file_size_bytes > MAX_FILE_SIZE_BYTES:
            raise DatasetTooLargeError(f"Dataset exceeds 50MB limit (size: {dataset.file_size_bytes} bytes).")

        # Load DataFrame from S3 into memory
        try:
            import asyncio
            df = await asyncio.to_thread(download_to_df, dataset.storage_key, settings.S3_BUCKET_RAW)
        except Exception as e:
            raise DependencyError(f"Failed to fetch dataset from storage: {e}")

        # Build in-memory list of steps ordered by order_index
        steps = sorted(pipeline.pipeline_steps, key=lambda s: s.order_index)
        steps_dict = [{"action": s.action_name, "params": s.params_json} for s in steps]
        
        # Compute deterministic steps_hash
        steps_hash = hashlib.sha256(json.dumps(steps_dict, sort_keys=True).encode()).hexdigest()
        execution.steps_hash = steps_hash

        # Apply steps
        for step in steps_dict:
            action_name = step["action"]
            params = step["params"]
            if action_name not in REGISTRY:
                raise ValueError(f"Action '{action_name}' is not supported.")
            
            func = REGISTRY[action_name]
            df = func(df, params)

        # Final df outputs
        out_rows, out_cols = df.shape
        execution.output_row_count = out_rows
        
        # Write Output CSV deterministically
        from app.core.security.idempotency import deterministic_output_key
        output_storage_key = deterministic_output_key(dataset.user_id, execution_id)
        
        # Sort columns to enforce stability
        df = df[sorted(df.columns)]
        
        import asyncio
        await asyncio.to_thread(upload_csv_from_df_sync, df, output_storage_key, settings.S3_BUCKET_OUTPUT)
        
        execution.output_s3_key = output_storage_key
        execution.status = "completed"
        
        # Update job if available
        if execution.job_id:
            job_stmt = select(Job).where(Job.celery_task_id == execution.job_id)
            j_res = await db.execute(job_stmt)
            job = j_res.scalar_one_or_none()
            if job:
                job.status = "completed"
                job.progress = 100
        
        await db.commit()

    except Exception as e:
        execution.status = "failed"
        execution.error_detail = str(e)
        logger.exception(f"Pipeline execution {execution_id} failed: {str(e)}")
        
        if execution.job_id:
            job_stmt = select(Job).where(Job.celery_task_id == execution.job_id)
            j_res = await db.execute(job_stmt)
            job = j_res.scalar_one_or_none()
            if job:
                job.status = "failed"
                job.error = str(e)

        await db.commit()
