from app.services.job_service import JobService
from app.api.v1.deps import get_job_service
"""
API v1 jobs endpoints.
Constraint: Must depend only on Services and schemas.
No raw SQLAlchemy models or sessions operations permitted.
"""
from fastapi import APIRouter, Depends
from typing import List, Optional

from app.models import User
from app.core.security.auth import get_current_user
from app.schemas import JobOut

router = APIRouter(prefix="/jobs", tags=["jobs"])

@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: int, user: User = Depends(get_current_user), service: JobService = Depends(get_job_service)):
    return await service.get_job(job_id, user.id)

@router.get("", response_model=List[JobOut])
async def list_jobs(
    page: int = 1, page_size: int = 20, job_type: Optional[str] = None, user: User = Depends(get_current_user), 
):
    return await service.list_jobs(user.id, page, page_size, job_type)
