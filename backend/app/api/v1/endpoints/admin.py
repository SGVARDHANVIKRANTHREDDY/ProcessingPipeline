"""
API v1 admin endpoints.
Constraint: Must depend only on Services and schemas.
No raw SQLAlchemy models or sessions operations permitted.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.core.database.engine import get_db
from app.models import User
from app.core.security.auth import get_current_user
from app.services.admin_service import admin_service
from app.core.config import get_settings

settings = get_settings()
router  = APIRouter(prefix="/admin", tags=["admin"])
limiter = Limiter(key_func=get_remote_address)

async def require_admin(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> User:
    if not user.is_admin and not user.is_super_admin:
        raise HTTPException(403, "Admin access required")
    return user

async def require_super_admin(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> User:
    if not user.is_super_admin:
        raise HTTPException(403, "Super-admin access required for this operation")
    return user

@router.get("/dlq")
@limiter.limit(settings.RATE_LIMIT_ADMIN)
async def list_dlq(request: Request, page: int = 1, replayed: bool = False, suppressed: bool = False,
                    db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    return await admin_service.list_dlq(db, admin.id, page, replayed, suppressed, request)

@router.post("/dlq/{entry_id}/replay")
@limiter.limit(settings.RATE_LIMIT_ADMIN_CRITICAL)
async def replay_dlq(request: Request, entry_id: int,
                      db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    return await admin_service.replay_dlq(db, admin.id, entry_id, request)

@router.get("/audit")
@limiter.limit(settings.RATE_LIMIT_ADMIN)
async def query_audit(request: Request, page: int = 1, action: Optional[str] = None,
                       user_id: Optional[int] = None, resource_type: Optional[str] = None,
                       db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    return await admin_service.query_audit(db, admin.id, page, action, user_id, resource_type, request)

@router.get("/audit/verify")
@limiter.limit(settings.RATE_LIMIT_ADMIN)
async def verify_audit(request: Request, user_id: Optional[int] = None, limit: int = 1000,
                        db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    return await admin_service.verify_audit(db, admin.id, user_id, limit, request)

@router.get("/audit/verify-global")
@limiter.limit(settings.RATE_LIMIT_ADMIN)
async def verify_global_audit(request: Request, limit: int = 10000,
                               db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    return await admin_service.verify_global_audit(db, admin.id, limit, request)

@router.post("/users/{target_id}/grant-admin")
@limiter.limit(settings.RATE_LIMIT_ADMIN_CRITICAL)
async def grant_admin(request: Request, target_id: int,
                       db: AsyncSession = Depends(get_db),
                       admin: User = Depends(require_super_admin)):
    return await admin_service.grant_admin(db, admin.id, target_id, request)

@router.post("/users/{target_id}/revoke-admin")
@limiter.limit(settings.RATE_LIMIT_ADMIN_CRITICAL)
async def revoke_admin(request: Request, target_id: int,
                        db: AsyncSession = Depends(get_db),
                        admin: User = Depends(require_super_admin)):
    return await admin_service.revoke_admin(db, admin.id, target_id, request)

@router.post("/users/{target_id}/grant-super-admin")
@limiter.limit(settings.RATE_LIMIT_ADMIN_CRITICAL)
async def grant_super_admin(request: Request, target_id: int,
                             db: AsyncSession = Depends(get_db),
                             admin: User = Depends(require_super_admin)):
    return await admin_service.grant_super_admin(db, admin.id, target_id, request)

@router.get("/jobs/failed")
@limiter.limit(settings.RATE_LIMIT_ADMIN)
async def list_failed_jobs(request: Request, page: int = 1,
                            db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)):
    return await admin_service.list_failed_jobs(db, page)
