from typing import Sequence, Optional
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta

from app.models import Pipeline, PipelineExecution
from app.repositories.base import BaseRepository

class PipelineRepository(BaseRepository[Pipeline]):
    def __init__(self):
        super().__init__(Pipeline)

    async def get_by_user(self, db: AsyncSession, id: int, user_id: int) -> Optional[Pipeline]:
        result = await db.execute(select(self.model).filter(self.model.id == id, self.model.user_id == user_id))
        return result.scalar_one_or_none()

    async def list_by_user(self, db: AsyncSession, user_id: int, offset: int = 0, limit: int = 20) -> Sequence[Pipeline]:
        result = await db.execute(select(self.model).filter(self.model.user_id == user_id).order_by(self.model.updated_at.desc()).offset(offset).limit(limit))
        return result.scalars().all()

    async def count_by_user(self, db: AsyncSession, user_id: int) -> int:
        result = await db.execute(select(func.count(self.model.id)).filter(self.model.user_id == user_id))
        return result.scalar_one()


class PipelineExecutionRepository(BaseRepository[PipelineExecution]):
    def __init__(self):
        super().__init__(PipelineExecution)

    async def get_by_pipeline(self, db: AsyncSession, pipeline_id: int, execution_id: int) -> Optional[PipelineExecution]:
        result = await db.execute(select(self.model).filter(self.model.id == execution_id, self.model.pipeline_id == pipeline_id))
        return result.scalar_one_or_none()

    async def list_by_pipeline(self, db: AsyncSession, pipeline_id: int, limit: int = 20) -> Sequence[PipelineExecution]:
        result = await db.execute(select(self.model).filter(self.model.pipeline_id == pipeline_id).order_by(self.model.created_at.desc()).limit(limit))
        return result.scalars().all()

    async def get_activity_metrics(self, db: AsyncSession, user_id: int, success_status: str = 'success', days: int = 14):
        cutoff = datetime.utcnow() - timedelta(days=days)
        query = (
            select(
                func.date(self.model.created_at).label('d'),
                func.count(self.model.id).label('total'),
                func.sum(case((self.model.status == success_status, 1), else_=0)).label('success')
            )
            .join(Pipeline, self.model.pipeline_id == Pipeline.id)
            .where(
                Pipeline.user_id == user_id,
                self.model.created_at >= cutoff
            )
            .group_by('d')
            .order_by('d')
        )
        result = await db.execute(query)
        return result.all()


pipeline_repo = PipelineRepository()
execution_repo = PipelineExecutionRepository()
