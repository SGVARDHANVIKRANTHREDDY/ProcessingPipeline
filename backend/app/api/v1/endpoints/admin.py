from app.services.admin_service import AdminService
from app.api.v1.deps import get_admin_service
"""
API v1 admin endpoints.
Constraint: Must depend only on Services and schemas.
No raw SQLAlchemy models or sessions operations permitted.
"""
from fastapi import APIRouter, Depends, Request
from app.core.exceptions import ForbiddenError
from slowapi import Limiter
from slowapi.util import get_remote_address
from typing import Optional

from app.models import User
from app.core.security.auth import get_current_user
from app.core.config import get_settings

settings = get_settings()
router  = APIRouter(prefix="/admin", tags=["admin"])
limiter = Limiter(key_func=get_remote_address)

async def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin and not user.is_super_admin:
        raise ForbiddenError("Admin access required")
    return user

async def require_super_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_super_admin:
        raise ForbiddenError("Super-admin access required for this operation")
    return user

@router.get("/dlq")
@limiter.limit(settings.RATE_LIMIT_ADMIN)
async def list_dlq(request: Request, page: int = 1, replayed: bool = False, suppressed: bool = False, admin: User = Depends(require_admin), service: AdminService = Depends(get_admin_service)):
    limit = 20
    offset = (page - 1) * limit
    items, total = await service.list_dlq(admin.id, offset, limit, replayed, suppressed, request)
    return {
        "items": [{"id": e.id, "task_name": e.task_name, "queue": e.queue, "error": e.error[:200],
                   "retry_count": e.retry_count, "replay_count": e.replay_count, "suppressed": e.suppressed,
                   "created_at": e.created_at.isoformat()} for e in items],
        "total": total
    }

@router.post("/dlq/{entry_id}/replay")
@limiter.limit(settings.RATE_LIMIT_ADMIN_CRITICAL)
async def replay_dlq(request: Request, entry_id: int, admin: User = Depends(require_admin), service: AdminService = Depends(get_admin_service)):
    return await service.replay_dlq(admin.id, entry_id, request)

@router.get("/audit")
@limiter.limit(settings.RATE_LIMIT_ADMIN)
async def query_audit(request: Request, page: int = 1, action: Optional[str] = None,
                       user_id: Optional[int] = None, resource_type: Optional[str] = None, admin: User = Depends(require_admin), service: AdminService = Depends(get_admin_service)):
    limit = 20
    offset = (page - 1) * limit
    items, total = await service.query_audit(admin.id, offset, limit, action, user_id, resource_type, request)
    return {"items": items, "total": total, "page": page, "page_size": limit}

@router.get("/audit/verify")
@limiter.limit(settings.RATE_LIMIT_ADMIN)
async def verify_audit(request: Request, user_id: Optional[int] = None, limit: int = 1000, admin: User = Depends(require_admin), service: AdminService = Depends(get_admin_service)):
    return await service.verify_audit(admin.id, user_id, limit, request)

@router.get("/audit/verify-global")
@limiter.limit(settings.RATE_LIMIT_ADMIN)
async def verify_global_audit(request: Request, limit: int = 10000, admin: User = Depends(require_admin), service: AdminService = Depends(get_admin_service)):
    return await service.verify_global_audit(admin.id, limit, request)

@router.post("/users/{target_id}/grant-admin")
@limiter.limit(settings.RATE_LIMIT_ADMIN_CRITICAL)
async def grant_admin(request: Request, target_id: int,
                       admin: User = Depends(require_super_admin)):
    return await service.grant_admin(admin.id, target_id, request)

@router.post("/users/{target_id}/revoke-admin")
@limiter.limit(settings.RATE_LIMIT_ADMIN_CRITICAL)
async def revoke_admin(request: Request, target_id: int,
                        admin: User = Depends(require_super_admin)):
    return await service.revoke_admin(admin.id, target_id, request)

@router.post("/users/{target_id}/grant-super-admin")
@limiter.limit(settings.RATE_LIMIT_ADMIN_CRITICAL)
async def grant_super_admin(request: Request, target_id: int,
                             admin: User = Depends(require_super_admin)):
    return await service.grant_super_admin(admin.id, target_id, request)

@router.get("/jobs/failed")
@limiter.limit(settings.RATE_LIMIT_ADMIN)
async def list_failed_jobs(request: Request, page: int = 1, _: User = Depends(require_admin), service: AdminService = Depends(get_admin_service)):
    limit = 20
    offset = (page - 1) * limit
    items, total = await service.list_failed_jobs(offset, limit)
    return {"items": items, "total": total, "page": page, "page_size": limit}
