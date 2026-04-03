"""
Auth Service
Constraint: Domain objects, No HTTP details.
"""
from datetime import datetime, timezone, timedelta
from typing import Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, LoginAttempt
from app.repositories.user_repository import user_repo
from app.core.exceptions import NotFoundError, ValidationError, ConflictError, UnauthorizedError, ForbiddenError
from app.core.security.auth import hash_password, verify_password, create_token_pair, rotate_refresh_token
from app.core.security.audit import audit, AuditAction
from app.core.config import get_settings

settings = get_settings()
UTC = timezone.utc

class AuthService:
    def __init__(self, db):
        self.db = db

    async def register(self, body: Any, request_for_audit: Any = None) -> Dict[str, str]:
        existing = await user_repo.get_by_email(self.db, body.email)
        if existing:
            raise ConflictError("Email already registered")

        user = User(email=body.email, hashed_password=hash_password(body.password))
        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)

        tokens = await create_token_pair(self.db, user.id)
        await audit(self.db, AuditAction.AUTH_REGISTER, user_id=user.id,
                    resource_type="user", resource_id=user.id, detail={"email": user.email}, request=request_for_audit)
        return tokens

    async def login(self, body: Any, ip: str, request_for_audit: Any = None) -> Dict[str, str]:
        user = await user_repo.get_by_email(self.db, body.email)

        async def record(success: bool):
            self.db.add(LoginAttempt(email=body.email, ip_address=ip[:45], success=success))

        if not user:
            await record(False)
            await audit(self.db, AuditAction.AUTH_LOGIN_FAILED, detail={"email": body.email, "reason": "not_found"}, request=request_for_audit)
            raise UnauthorizedError("Invalid credentials")

        if user.is_locked:
            if user.locked_until and datetime.now(UTC) < user.locked_until:
                remaining = int((user.locked_until - datetime.now(UTC)).total_seconds())
                raise ForbiddenError(f"Account locked. Retry in {remaining}s")
            user.is_locked = False
            user.failed_login_count = 0

        if not user.is_active:
            raise ForbiddenError("Account disabled")

        if not verify_password(body.password, user.hashed_password):
            user.failed_login_count += 1
            if user.failed_login_count >= settings.LOGIN_MAX_ATTEMPTS:
                user.is_locked = True
                user.locked_until = datetime.now(UTC) + timedelta(seconds=settings.LOGIN_LOCKOUT_SECONDS)
                await record(False)
                await audit(self.db, AuditAction.AUTH_USER_LOCKED, user_id=user.id,
                            detail={"attempts": user.failed_login_count}, request=request_for_audit)
                raise ForbiddenError(f"Account locked after {settings.LOGIN_MAX_ATTEMPTS} failed attempts")
            await record(False)
            await audit(self.db, AuditAction.AUTH_LOGIN_FAILED, user_id=user.id,
                        detail={"attempts": user.failed_login_count}, request=request_for_audit)
            raise UnauthorizedError("Invalid credentials")

        user.failed_login_count = 0
        user.is_locked = False
        await record(True)

        tokens = await create_token_pair(self.db, user.id)
        await audit(self.db, AuditAction.AUTH_LOGIN, user_id=user.id, request=request_for_audit)
        return tokens

    async def refresh(self, refresh_token: str, request_for_audit: Any = None) -> Dict[str, str]:
        tokens = await rotate_refresh_token(self.db, refresh_token)
        await audit(self.db, AuditAction.AUTH_REFRESH_ROTATED, request=request_for_audit)
        return tokens

