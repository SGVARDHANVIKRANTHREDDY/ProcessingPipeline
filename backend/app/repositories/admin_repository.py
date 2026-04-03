from typing import Sequence, Optional
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import User, DeadLetterEntry, AuditLog, Job

class AdminRepository:
    async def count_dlq(self, db: AsyncSession, replayed: bool, suppressed: bool) -> int:
        return (await db.execute(select(func.count(DeadLetterEntry.id)).where(DeadLetterEntry.replayed == replayed, DeadLetterEntry.suppressed == suppressed))).scalar_one()

    async def list_dlq(self, db: AsyncSession, replayed: bool, suppressed: bool, offset: int, limit: int) -> Sequence[DeadLetterEntry]:
        return (await db.execute(select(DeadLetterEntry).where(DeadLetterEntry.replayed == replayed, DeadLetterEntry.suppressed == suppressed).order_by(desc(DeadLetterEntry.created_at)).offset(offset).limit(limit))).scalars().all()

    async def count_audit(self, db: AsyncSession, action: Optional[str], user_id: Optional[int], resource_type: Optional[str]) -> int:
        q = select(func.count(AuditLog.id))
        if action: q = q.where(AuditLog.action == action)
        if user_id: q = q.where(AuditLog.user_id == user_id)
        if resource_type: q = q.where(AuditLog.resource_type == resource_type)
        return (await db.execute(q)).scalar_one()

    async def list_audit(self, db: AsyncSession, action: Optional[str], user_id: Optional[int], resource_type: Optional[str], offset: int, limit: int) -> Sequence[AuditLog]:
        q = select(AuditLog).order_by(desc(AuditLog.created_at))
        if action: q = q.where(AuditLog.action == action)
        if user_id: q = q.where(AuditLog.user_id == user_id)
        if resource_type: q = q.where(AuditLog.resource_type == resource_type)
        return (await db.execute(q.offset(offset).limit(limit))).scalars().all()

    async def get_user(self, db: AsyncSession, user_id: int) -> Optional[User]:
        return (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()

    async def count_jobs_by_status(self, db: AsyncSession, status: str) -> int:
        return (await db.execute(select(func.count(Job.id)).where(Job.status == status))).scalar_one()

    async def list_jobs_by_status(self, db: AsyncSession, status: str, offset: int, limit: int) -> Sequence[Job]:
        return (await db.execute(select(Job).where(Job.status == status).order_by(desc(Job.created_at)).offset(offset).limit(limit))).scalars().all()

admin_repo = AdminRepository()
