"""Auth v8 — refresh token rotation, bounded family revocation, dual-key rotation."""
import hashlib, uuid, logging
from datetime import datetime, timedelta, timezone
from typing import Any
import jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.config import get_settings
from app.core.database.engine import get_db
from app.models import User, RefreshToken

settings = get_settings()
_pwd  = CryptContext(schemes=["bcrypt"], deprecated="auto")
_http = HTTPBearer()
UTC   = timezone.utc
logger = logging.getLogger(__name__)


def hash_password(plain: str) -> str: return _pwd.hash(plain)
def verify_password(plain: str, hashed: str) -> bool: return _pwd.verify(plain, hashed)
def _hash_token(raw: str) -> str: return hashlib.sha256(raw.encode()).hexdigest()


def _create_jwt(data: dict[str, Any], expires: timedelta) -> str:
    if not settings.SECRET_KEY:
        raise RuntimeError("SECRET_KEY not configured — server misconfiguration")
    return jwt.encode({**data, "exp": datetime.now(UTC) + expires}, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_access_token(user_id: int) -> str:
    return _create_jwt({"sub": str(user_id), "type": "access"}, timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))


async def _store_refresh(db: AsyncSession, user_id: int, family_id: str | None = None) -> str:
    raw = uuid.uuid4().hex + uuid.uuid4().hex
    db.add(RefreshToken(
        user_id=user_id, token_hash=_hash_token(raw),
        family_id=family_id or uuid.uuid4().hex,
        expires_at=datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    ))
    await db.flush()
    return raw


async def create_token_pair(db: AsyncSession, user_id: int) -> dict:
    raw_refresh = await _store_refresh(db, user_id)
    return {"access_token": create_access_token(user_id), "refresh_token": raw_refresh, "token_type": "bearer"}


async def rotate_refresh_token(db: AsyncSession, raw_token: str) -> dict:
    """
    Rotate: revoke old, issue new in same family.
    FIX v8: family revocation is BOUNDED to REFRESH_TOKEN_FAMILY_MAX_REVOKE rows
    to prevent DoS via unbounded UPDATE.
    """
    result = await db.execute(select(RefreshToken).where(RefreshToken.token_hash == _hash_token(raw_token)))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(401, "Invalid refresh token")
    if record.expires_at < datetime.now(UTC):
        raise HTTPException(401, "Refresh token expired")
    if record.is_revoked:
        # Bounded family revocation — prevents DoS via unbounded SELECT/UPDATE
        family_result = await db.execute(
            select(RefreshToken).where(
                RefreshToken.family_id == record.family_id,
                RefreshToken.is_revoked == False
            ).limit(settings.REFRESH_TOKEN_FAMILY_MAX_REVOKE)   # FIX: bounded
        )
        for t in family_result.scalars().all():
            t.is_revoked = True; t.revoked_at = datetime.now(UTC)
        logger.warning("REFRESH_REUSE_DETECTED user=%d family=%s — family revoked (bounded)",
                       record.user_id, record.family_id[:8])
        raise HTTPException(401, "Security alert: refresh token reused. Please log in again.")
    user_result = await db.execute(select(User).where(User.id == record.user_id, User.is_active == True))
    user = user_result.scalar_one_or_none()
    if not user: raise HTTPException(401, "User not found")
    record.is_revoked = True; record.revoked_at = datetime.now(UTC)
    new_raw = await _store_refresh(db, record.user_id, family_id=record.family_id)
    return {"access_token": create_access_token(record.user_id), "refresh_token": new_raw, "token_type": "bearer"}


def decode_access_token(token: str) -> dict:
    """Try current key, then previous key (zero-downtime rotation)."""
    keys = [k for k in [settings.SECRET_KEY, settings.SECRET_KEY_PREVIOUS] if k]
    if not keys:
        raise HTTPException(500, "Server misconfiguration: SECRET_KEY not set")
    for key in keys:
        try:
            payload = jwt.decode(token, key, algorithms=[settings.ALGORITHM])
            if payload.get("type") != "access": raise HTTPException(401, "Wrong token type")
            return payload
        except jwt.ExpiredSignatureError: raise HTTPException(401, "Token expired")
        except jwt.InvalidTokenError: continue
    raise HTTPException(401, "Invalid token")


async def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(_http),
    db: AsyncSession = Depends(get_db),
) -> User:
    payload = decode_access_token(creds.credentials)
    result  = await db.execute(select(User).where(User.id == int(payload["sub"]), User.is_active == True))
    user    = result.scalar_one_or_none()
    if not user: raise HTTPException(401, "User not found or inactive")
    return user
