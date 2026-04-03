"""
Job Service
Constraint: Domain objects, No HTTP details.
"""
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Job
from app.repositories.job_repository import job_repo
from app.core.exceptions import NotFoundError

class JobService:
    def __init__(self, db):
        self.db = db

    async def get_job(self, job_id: int, user_id: int) -> Job:
        job = await job_repo.get_by_user(self.db, job_id, user_id)
        if not job:
            raise NotFoundError("Job not found")
        return job

    async def list_jobs(self, user_id: int, page: int = 1, page_size: int = 20, job_type: Optional[str] = None) -> List[Job]:
        page_size = min(page_size, 50)
        offset = (page - 1) * page_size
        return await job_repo.list_by_user(self.db, user_id, job_type, offset, page_size)

