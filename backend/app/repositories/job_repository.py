from typing import Sequence, Optional
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Job
from app.repositories.base import BaseRepository

class JobRepository(BaseRepository[Job]):
    def __init__(self):
        super().__init__(Job)

    async def get_by_user(self, db: AsyncSession, id: int, user_id: int) -> Optional[Job]:
        result = await db.execute(select(self.model).filter(self.model.id == id, self.model.user_id == user_id))
        return result.scalar_one_or_none()

    async def list_by_user(self, db: AsyncSession, user_id: int, job_type: Optional[str] = None, offset: int = 0, limit: int = 20) -> Sequence[Job]:
        q = select(self.model).filter(self.model.user_id == user_id)
        if job_type:
            q = q.filter(self.model.job_type == job_type)
        result = await db.execute(q.order_by(self.model.created_at.desc()).offset(offset).limit(limit))
        return result.scalars().all()

job_repo = JobRepository()
