"""
Storage Service v10.

FIX: S3_USE_AIOBOTO3 is now an explicit env var (not import-time detection).
  Set S3_USE_AIOBOTO3=true in .env only after confirming aioboto3 is installed.
  Import-time detection was fragile — silently fell back without warning.

NEW: upload_csv_from_df_sync — used by tasks.py for deterministic key upload.
  Takes an explicit key (not generating a random one) for idempotent S3 writes.
"""
import io
import time
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import BinaryIO
import pandas as pd
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

_BOTO_CONFIG = BotoConfig(
    retries={"max_attempts": 3, "mode": "adaptive"},
    max_pool_connections=50, connect_timeout=10, read_timeout=60,
)

_executor = ThreadPoolExecutor(
    max_workers=settings.S3_THREAD_POOL_SIZE, thread_name_prefix="s3-worker"
)


class _CircuitBreaker:
    def __init__(self, threshold: int, timeout: int):
        self.threshold = threshold; self.timeout = timeout
        self._failures = 0; self._opened_at: float | None = None

    def is_open(self) -> bool:
        if self._opened_at is None: return False
        if time.monotonic() - self._opened_at > self.timeout:
            self._opened_at = None; self._failures = 0; return False
        return True

    def record_success(self): self._failures = 0; self._opened_at = None
    def record_failure(self):
        self._failures += 1
        if self._failures >= self.threshold:
            self._opened_at = time.monotonic()
            logger.error("S3 circuit OPEN")


_s3_circuit = _CircuitBreaker(settings.S3_CIRCUIT_BREAKER_THRESHOLD, settings.S3_CIRCUIT_BREAKER_TIMEOUT)


def _check_circuit():
    if _s3_circuit.is_open():
        raise RuntimeError("S3 circuit breaker is OPEN — storage temporarily unavailable")


def _s3_kwargs() -> dict:
    kw = dict(
        region_name=settings.S3_REGION,
        aws_access_key_id=settings.S3_ACCESS_KEY_ID,
        aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
        config=_BOTO_CONFIG,
    )
    if settings.S3_ENDPOINT_URL:
        kw["endpoint_url"] = settings.S3_ENDPOINT_URL
    return kw


def _get_aioboto3():
    """Explicit: only use aioboto3 if S3_USE_AIOBOTO3=true AND package is installed."""
    if not settings.S3_USE_AIOBOTO3:
        return None
    try:
        import aioboto3
        return aioboto3
    except ImportError:
        logger.error("S3_USE_AIOBOTO3=true but aioboto3 not installed. "
                     "Run: pip install aioboto3. Falling back to thread pool.")
        return None


async def upload_file_async(data: bytes | BinaryIO, key: str, bucket: str,
                             content_type: str = "text/csv") -> str:
    _check_circuit()
    raw = data if isinstance(data, bytes) else data.read()
    aioboto3 = _get_aioboto3()
    if aioboto3:
        async with aioboto3.Session().client("s3", **_s3_kwargs()) as s3:
            try:
                await s3.put_object(Bucket=bucket, Key=key, Body=raw,
                                    ContentType=content_type, ServerSideEncryption="AES256")
                _s3_circuit.record_success(); return key
            except Exception: _s3_circuit.record_failure(); raise
    else:
        def _sync():
            import boto3
            boto3.client("s3", **_s3_kwargs()).upload_fileobj(
                io.BytesIO(raw), bucket, key,
                ExtraArgs={"ContentType": content_type, "ServerSideEncryption": "AES256"})
            return key
        try:
            result = await asyncio.get_event_loop().run_in_executor(_executor, _sync)
            _s3_circuit.record_success(); return result
        except Exception: _s3_circuit.record_failure(); raise


async def download_to_df_async(key: str, bucket: str) -> pd.DataFrame:
    _check_circuit()
    aioboto3 = _get_aioboto3()
    if aioboto3:
        async with aioboto3.Session().client("s3", **_s3_kwargs()) as s3:
            try:
                resp = await s3.get_object(Bucket=bucket, Key=key)
                body = await resp["Body"].read()
                _s3_circuit.record_success()
                return pd.read_csv(io.BytesIO(body), low_memory=False)
            except Exception: _s3_circuit.record_failure(); raise
    else:
        def _sync():
            import boto3
            resp = boto3.client("s3", **_s3_kwargs()).get_object(Bucket=bucket, Key=key)
            return pd.read_csv(resp["Body"], low_memory=False)
        try:
            result = await asyncio.get_event_loop().run_in_executor(_executor, _sync)
            _s3_circuit.record_success(); return result
        except Exception: _s3_circuit.record_failure(); raise


async def get_signed_url_async(key: str, bucket: str, expiry: int | None = None) -> str:
    _check_circuit()
    aioboto3 = _get_aioboto3()
    if aioboto3:
        async with aioboto3.Session().client("s3", **_s3_kwargs()) as s3:
            try:
                url = await s3.generate_presigned_url("get_object",
                    Params={"Bucket": bucket, "Key": key},
                    ExpiresIn=expiry or settings.S3_SIGNED_URL_EXPIRY)
                _s3_circuit.record_success(); return url
            except Exception: _s3_circuit.record_failure(); raise
    else:
        def _sync():
            import boto3
            return boto3.client("s3", **_s3_kwargs()).generate_presigned_url(
                "get_object", Params={"Bucket": bucket, "Key": key},
                ExpiresIn=expiry or settings.S3_SIGNED_URL_EXPIRY)
        try:
            result = await asyncio.get_event_loop().run_in_executor(_executor, _sync)
            _s3_circuit.record_success(); return result
        except Exception: _s3_circuit.record_failure(); raise


async def delete_object_async(key: str, bucket: str) -> None:
    _check_circuit()
    aioboto3 = _get_aioboto3()
    if aioboto3:
        async with aioboto3.Session().client("s3", **_s3_kwargs()) as s3:
            try: await s3.delete_object(Bucket=bucket, Key=key)
            except Exception: pass
    else:
        def _sync():
            import boto3
            try: boto3.client("s3", **_s3_kwargs()).delete_object(Bucket=bucket, Key=key)
            except Exception: pass
        await asyncio.get_event_loop().run_in_executor(_executor, _sync)


async def object_exists_async(key: str, bucket: str) -> bool:
    _check_circuit()
    def _sync():
        import boto3
        try: boto3.client("s3", **_s3_kwargs()).head_object(Bucket=bucket, Key=key); return True
        except ClientError: return False
    return await asyncio.get_event_loop().run_in_executor(_executor, _sync)


async def ensure_buckets_async() -> None:
    for bucket in (settings.S3_BUCKET_RAW, settings.S3_BUCKET_OUTPUT, settings.S3_BUCKET_QUARANTINE):
        def _sync(b=bucket):
            import boto3
            s3 = boto3.client("s3", **_s3_kwargs())
            try: s3.head_bucket(Bucket=b)
            except ClientError as e:
                if e.response["Error"]["Code"] in ("404", "NoSuchBucket"):
                    try: s3.create_bucket(Bucket=b); logger.info("Created bucket: %s", b)
                    except Exception as ex: logger.error("Bucket %s failed: %s", b, ex)
        await asyncio.get_event_loop().run_in_executor(_executor, _sync)


# Sync helpers for Celery tasks
def download_to_df(key: str, bucket: str) -> pd.DataFrame:
    _check_circuit()
    import boto3
    s3 = boto3.client("s3", **_s3_kwargs())
    try:
        resp = s3.get_object(Bucket=bucket, Key=key)
        result = pd.read_csv(resp["Body"], low_memory=False)
        _s3_circuit.record_success(); return result
    except Exception: _s3_circuit.record_failure(); raise


def upload_csv_from_df_sync(df: pd.DataFrame, key: str, bucket: str) -> str:
    """
    FIX v10: accepts explicit key (not generating random UUID).
    Used by tasks.py with deterministic_output_key() for idempotent S3 writes.
    """
    _check_circuit()
    import boto3
    buf = io.BytesIO(); df.to_csv(buf, index=False); buf.seek(0)
    s3 = boto3.client("s3", **_s3_kwargs())
    try:
        s3.upload_fileobj(buf, bucket, key,
                         ExtraArgs={"ContentType": "text/csv", "ServerSideEncryption": "AES256"})
        _s3_circuit.record_success(); return key
    except Exception: _s3_circuit.record_failure(); raise


def upload_csv_from_df(df: pd.DataFrame, prefix: str, bucket: str) -> str:
    """Legacy random-key version — kept for compatibility. Use upload_csv_from_df_sync for idempotency."""
    import uuid
    key = f"{prefix}/{uuid.uuid4().hex}.csv"
    return upload_csv_from_df_sync(df, key, bucket)


def generate_upload_key(user_id: int, filename: str) -> str:
    import uuid
    safe = filename.replace(" ", "_")[:100]
    return f"users/{user_id}/raw/{uuid.uuid4().hex}_{safe}"
