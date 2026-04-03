"""
Idempotency Service v10.

FIX (v9 gap): Dedup key granularity.
  v9: dedup_key = f"exec:{user_id}:{pipeline_id}:{dataset_id}"
  Problem: same pipeline_id, same dataset_id, but DIFFERENT steps config
  (pipeline was updated between calls) → false dedup.

  v10 fix: dedup_key includes hash of the actual steps that will be executed.
  dedup_key = f"exec:{user_id}:{pipeline_id}:{dataset_id}:{steps_hash}"

  steps_hash = SHA-256 of sorted(json.dumps(steps))
  Different steps → different dedup key → separate executions allowed.
  Same steps → same key → duplicate prevented.

FIX: S3 output side-effect idempotency.
  v9: S3 output key was f"{prefix}/{uuid.uuid4().hex}.csv" — random on every call.
  If task retried after S3 upload but before DB commit → two S3 objects.

  v10 fix: deterministic S3 output key based on execution_id.
  S3 key = f"users/{user_id}/outputs/exec-{execution_id}.csv"
  Deterministic → idempotent → if S3 upload retried, same key is overwritten.
  S3 PUT is idempotent (same key, same content → no duplicate object).

All 3 layers intact from v9.
"""
import hashlib
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Annotated

from fastapi import Request, HTTPException, Depends, Header
from sqlalchemy import text, select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import IdempotencyKey

settings = get_settings()
logger = logging.getLogger(__name__)
UTC = timezone.utc


def hash_request_body(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def hash_steps(steps: list[dict]) -> str:
    """
    Deterministic hash of pipeline steps.
    Sorting keys ensures {"a":1,"b":2} == {"b":2,"a":1}.
    """
    normalized = json.dumps(steps, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def deterministic_output_key(user_id: int, execution_id: int) -> str:
    """
    Idempotent S3 output key — same execution_id → same key → S3 PUT is idempotent.
    Retrying S3 upload overwrites the same object, not creates a second one.
    """
    return f"users/{user_id}/outputs/exec-{execution_id}.csv"


# ── Layer 1: API-level enforcement ───────────────────────────

async def require_idempotency_key(
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> str:
    """
    FastAPI dependency — REQUIRES Idempotency-Key header on mutating endpoints.
    Returns the validated key string.
    """
    if idempotency_key is None:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "type": "IDEMPOTENCY_KEY_REQUIRED",
                    "message": (
                        "This endpoint requires an Idempotency-Key header. "
                        "Send a unique UUID per logical operation: "
                        "Idempotency-Key: <uuid4>"
                    ),
                }
            },
        )
    return _validate_key(idempotency_key)


async def optional_idempotency_key(
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> str | None:
    if idempotency_key is None:
        return None
    return _validate_key(idempotency_key)


def _validate_key(key: str) -> str:
    key = key.strip()
    if not key or len(key) > 255:
        raise HTTPException(400, "Idempotency-Key must be 1-255 characters")
    if not all(32 <= ord(c) < 127 for c in key):
        raise HTTPException(400, "Idempotency-Key must be printable ASCII")
    return key


def get_idempotency_key_from_request(request: Request) -> str | None:
    key = (request.headers.get(settings.IDEMPOTENCY_HEADER)
           or request.headers.get(settings.IDEMPOTENCY_KEY_HEADER))
    if key is None:
        return None
    return _validate_key(key)


# ── Layer 2: Service-level atomic claim ──────────────────────

async def get_or_create_idempotency_key(
    db: AsyncSession, user_id: int, key: str, endpoint: str, request_hash: str,
) -> dict:
    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=settings.IDEMPOTENCY_TTL_SECONDS)
    lock_id = abs(hash(f"idem:{user_id}:{key}")) % (2 ** 31)
    await db.execute(text(f"SELECT pg_advisory_xact_lock({lock_id})"))
    result = await db.execute(
        select(IdempotencyKey).where(
            IdempotencyKey.user_id == user_id,
            IdempotencyKey.key == key,
            IdempotencyKey.expires_at > now,
        )
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        if existing.request_hash != request_hash:
            raise HTTPException(422, {"error": {"type": "IDEMPOTENCY_BODY_CONFLICT",
                                                 "message": "Key reused with different request body"}})
        if existing.processing:
            raise HTTPException(409, {"error": {"type": "CONCURRENT_REQUEST",
                                                 "message": "Request with this key is already processing"}})
        logger.info("Idempotency replay: user=%d key=%.8s", user_id, key)
        return {"action": "replay", "status": existing.response_status, "body": existing.response_body}
    db.add(IdempotencyKey(
        user_id=user_id, key=key, endpoint=endpoint,
        request_hash=request_hash, processing=True, expires_at=expires_at,
    ))
    await db.flush()
    return {"action": "proceed"}


async def complete_idempotency_key(db: AsyncSession, user_id: int, key: str,
                                    response_status: int, response_body: dict) -> None:
    result = await db.execute(select(IdempotencyKey).where(
        IdempotencyKey.user_id == user_id, IdempotencyKey.key == key))
    record = result.scalar_one_or_none()
    if record:
        record.processing = False
        record.response_status = response_status
        record.response_body = response_body
        await db.flush()


async def fail_idempotency_key(db: AsyncSession, user_id: int, key: str) -> None:
    result = await db.execute(select(IdempotencyKey).where(
        IdempotencyKey.user_id == user_id, IdempotencyKey.key == key))
    record = result.scalar_one_or_none()
    if record:
        record.processing = False
        await db.flush()


async def cleanup_expired_keys(db: AsyncSession) -> int:
    result = await db.execute(
        delete(IdempotencyKey).where(IdempotencyKey.expires_at <= datetime.now(UTC)))
    count = result.rowcount
    if count:
        logger.info("Purged %d expired idempotency keys", count)
    return count


# ── Layer 3: Execution deduplication (exactly-once) ──────────

async def claim_execution_dedup(
    db: AsyncSession,
    user_id: int,
    pipeline_id: int,
    dataset_id: int,
    steps: list[dict],
) -> dict:
    """
    FIX v10: dedup key includes steps hash.
    Same pipeline + same dataset + DIFFERENT steps → separate executions allowed.
    Same pipeline + same dataset + SAME steps → duplicate prevented.
    """
    steps_hash = hash_steps(steps) if settings.EXECUTION_DEDUP_INCLUDE_STEPS else ""
    dedup_key = f"exec:{user_id}:{pipeline_id}:{dataset_id}:{steps_hash}"
    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=settings.EXECUTION_DEDUP_TTL_SECONDS)

    lock_id = abs(hash(dedup_key)) % (2 ** 31)
    await db.execute(text(f"SELECT pg_advisory_xact_lock({lock_id})"))

    result = await db.execute(
        select(IdempotencyKey).where(
            IdempotencyKey.user_id == user_id,
            IdempotencyKey.key == dedup_key,
            IdempotencyKey.expires_at > now,
        )
    )
    existing = result.scalar_one_or_none()
    if existing is not None and not existing.processing and existing.response_body:
        return {
            "action": "duplicate",
            "existing_execution_id": existing.response_body.get("execution_id"),
            "message": "Duplicate execution prevented — same pipeline, dataset, and steps",
            "dedup_key": dedup_key,
        }

    if existing is None:
        db.add(IdempotencyKey(
            user_id=user_id, key=dedup_key,
            endpoint=f"execute:{pipeline_id}:{dataset_id}:{steps_hash[:8]}",
            request_hash=dedup_key, processing=True, expires_at=expires_at,
        ))
        await db.flush()

    return {"action": "proceed", "dedup_key": dedup_key}


async def complete_execution_dedup(
    db: AsyncSession, user_id: int, pipeline_id: int, dataset_id: int,
    steps: list[dict], execution_id: int,
) -> None:
    steps_hash = hash_steps(steps) if settings.EXECUTION_DEDUP_INCLUDE_STEPS else ""
    dedup_key = f"exec:{user_id}:{pipeline_id}:{dataset_id}:{steps_hash}"
    result = await db.execute(select(IdempotencyKey).where(
        IdempotencyKey.user_id == user_id, IdempotencyKey.key == dedup_key))
    record = result.scalar_one_or_none()
    if record:
        record.processing = False
        record.response_status = 202
        record.response_body = {"execution_id": execution_id}
        await db.flush()
