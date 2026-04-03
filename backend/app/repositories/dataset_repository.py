from typing import Optional, List
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from .base import BaseRepository
from app.models import Dataset

class DatasetRepository(BaseRepository[Dataset]):
    def __init__(self):
        super().__init__(Dataset)

    async def get_by_user(self, db: AsyncSession, dataset_id: int, user_id: int) -> Optional[Dataset]:
        result = await db.execute(select(self.model).where(
            self.model.id == dataset_id,
            self.model.user_id == user_id
        ))
        return result.scalars().first()

    async def count_by_user(self, db: AsyncSession, user_id: int) -> int:
        result = await db.execute(select(func.count(self.model.id)).where(
            self.model.user_id == user_id
        ))
        return result.scalar_one()

    async def list_by_user(self, db: AsyncSession, user_id: int, skip: int, limit: int) -> List[Dataset]:
        result = await db.execute(
            select(self.model)
            .where(self.model.user_id == user_id)
            .order_by(self.model.created_at.desc())
            .offset(skip).limit(limit)
        )
        return list(result.scalars().all())

dataset_repo = DatasetRepository()
