"""
Admin Service
Constraint: Domain objects, No HTTP details.
"""
from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import User
from app.repositories.admin_repository import admin_repo
from app.core.exceptions import NotFoundError, ValidationError, ForbiddenError, DependencyError
from app.services.dead_letter import replay_dlq_entry
from app.core.security.audit import verify_audit_chain, verify_global_sequence_integrity, AuditAction, audit

class AdminService:
    def __init__(self, db):
        self.db = db

    async def list_dlq(self, admin_id: int, page: int, replayed: bool, suppressed: bool, request_for_audit: Any = None) -> Dict[str, Any]:
        await audit(self.db, AuditAction.ADMIN_DLQ_VIEW, user_id=admin_id,
                    detail={"page": page}, request=request_for_audit)
        offset = (page - 1) * 20
        total = await admin_repo.count_dlq(self.db, replayed, suppressed)
        items = await admin_repo.list_dlq(self.db, replayed, suppressed, offset, 20)
        return {
            "items": [{"id": e.id, "task_name": e.task_name, "queue": e.queue, "error": e.error[:200],
                       "retry_count": e.retry_count, "replay_count": e.replay_count, "suppressed": e.suppressed,
                       "created_at": e.created_at.isoformat()} for e in items],
            "total": total
        }

    async def replay_dlq(self, admin_id: int, entry_id: int, request_for_audit: Any = None) -> Dict[str, Any]:
        await audit(self.db, AuditAction.DLQ_REPLAY, user_id=admin_id,
                    detail={"entry_id": entry_id, "phase": "attempt"}, request=request_for_audit)
        try:
            result = await replay_dlq_entry(entry_id, admin_user_id=admin_id)
            await audit(self.db, AuditAction.DLQ_REPLAY, user_id=admin_id,
                        detail={"entry_id": entry_id, "phase": "success", "new_task": result.get("new_celery_task_id")}, request=request_for_audit)
            return result
        except ValueError as e:
            await audit(self.db, AuditAction.DLQ_REPLAY, user_id=admin_id,
                        detail={"entry_id": entry_id, "phase": "rejected", "reason": str(e)}, request=request_for_audit)
            raise ValidationError(str(e))

    async def query_audit(self, admin_id: int, page: int, action: Optional[str], user_id: Optional[int], resource_type: Optional[str], request_for_audit: Any = None) -> Dict[str, Any]:
        await audit(self.db, AuditAction.ADMIN_VIEW_AUDIT, user_id=admin_id,
                    detail={"filters": {"action": action, "user_id": user_id}}, request=request_for_audit)
        offset = (page - 1) * 50
        total = await admin_repo.count_audit(self.db, action, user_id, resource_type)
        items = await admin_repo.list_audit(self.db, action, user_id, resource_type, offset, 50)
        return {
            "items": [{"id": e.id, "global_seq": e.global_seq, "user_id": e.user_id, "action": e.action,
                       "resource_type": e.resource_type, "resource_id": e.resource_id, "ip_address": e.ip_address,
                       "detail": e.detail, "created_at": e.created_at.isoformat()} for e in items],
            "total": total
        }

    async def verify_audit(self, admin_id: int, user_id: Optional[int], limit: int, request_for_audit: Any = None) -> Dict[str, Any]:
        result = await verify_audit_chain(self.db, user_id=user_id, limit=limit)
        await audit(self.db, AuditAction.AUDIT_CHAIN_VERIFY, user_id=admin_id,
                    detail={"verified_user_id": user_id, "valid": result.get("valid")}, request=request_for_audit)
        return result

    async def verify_global_audit(self, admin_id: int, limit: int, request_for_audit: Any = None) -> Dict[str, Any]:
        result = await verify_global_sequence_integrity(self.db, limit=limit)
        await audit(self.db, AuditAction.AUDIT_GLOBAL_VERIFY, user_id=admin_id,
                    detail={"valid": result.get("valid"), "gaps": result.get("gaps_found")}, request=request_for_audit)
        return result

    async def grant_admin(self, admin_id: int, target_id: int, request_for_audit: Any = None) -> Dict[str, Any]:
        target = await admin_repo.get_user(self.db, target_id)
        if not target:
            raise NotFoundError("User not found")
        if target.is_admin:
            return {"user_id": target_id, "is_admin": True, "message": "Already admin"}
        
        target.is_admin = True
        await self.self.db.flush()
        await audit(self.db, AuditAction.ADMIN_GRANT_ADMIN, user_id=admin_id,
                    resource_type="user", resource_id=target_id,
                    detail={"granted_by": admin_id, "email": target.email}, request=request_for_audit)
        return {"user_id": target_id, "is_admin": True}

    async def revoke_admin(self, admin_id: int, target_id: int, request_for_audit: Any = None) -> Dict[str, Any]:
        if target_id == admin_id:
            raise ValidationError("Cannot revoke your own admin access")
        
        target = await admin_repo.get_user(self.db, target_id)
        if not target:
            raise NotFoundError("User not found")
        
        target.is_admin = False
        await self.self.db.flush()
        await audit(self.db, AuditAction.ADMIN_REVOKE_ADMIN, user_id=admin_id,
                    resource_type="user", resource_id=target_id,
                    detail={"revoked_by": admin_id}, request=request_for_audit)
        return {"user_id": target_id, "is_admin": False}

    async def grant_super_admin(self, admin_id: int, target_id: int, request_for_audit: Any = None) -> Dict[str, Any]:
        if target_id == admin_id:
            raise ValidationError("Cannot self-grant super-admin")
        
        target = await admin_repo.get_user(self.db, target_id)
        if not target:
            raise NotFoundError("User not found")
        
        target.is_super_admin = True
        target.is_admin = True
        await self.self.db.flush()
        await audit(self.db, AuditAction.ADMIN_GRANT_SUPER, user_id=admin_id,
                    resource_type="user", resource_id=target_id,
                    detail={"granted_by": admin_id, "email": target.email}, request=request_for_audit)
        return {"user_id": target_id, "is_super_admin": True}

    async def list_failed_jobs(self, page: int) -> Dict[str, Any]:
        offset = (page - 1) * 20
        total = await admin_repo.count_failed_jobs(self.db)
        items = await admin_repo.list_failed_jobs(self.db, offset, 20)
        return {
            "items": [{"id": j.id, "job_type": j.job_type, "error": j.error, "created_at": j.created_at.isoformat()} for j in items],
            "total": total
        }

