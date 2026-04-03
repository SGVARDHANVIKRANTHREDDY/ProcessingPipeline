"""
API v1 jobs endpoints.
Constraint: Must depend only on Services and schemas.
No raw SQLAlchemy models or sessions operations permitted.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional

from app.core.database.engine import get_db
from app.models import User
from app.core.security.auth import get_current_user
from app.schemas import JobOut
from app.services.job_service import job_service

router = APIRouter(prefix="/jobs", tags=["jobs"])

@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await job_service.get_job(db, job_id, user.id)

@router.get("", response_model=List[JobOut])
async def list_jobs(
    page: int = 1, page_size: int = 20, job_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user), 
):
    return await job_service.list_jobs(db, user.id, page, page_size, job_type)
