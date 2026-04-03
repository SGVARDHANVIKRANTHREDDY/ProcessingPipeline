from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database.engine import get_db

from app.services.auth_service import AuthService
from app.services.admin_service import AdminService
from app.services.dataset_service import DatasetService
from app.services.pipeline_service import PipelineService
from app.services.job_service import JobService
from app.services.ai_service import AIService

def get_auth_service(db: AsyncSession = Depends(get_db)) -> AuthService:
    return AuthService(db)

def get_admin_service(db: AsyncSession = Depends(get_db)) -> AdminService:
    return AdminService(db)

def get_dataset_service(db: AsyncSession = Depends(get_db)) -> DatasetService:
    return DatasetService(db)

def get_dataset_read_service(db: AsyncSession = Depends(get_db)) -> DatasetService:
    return DatasetService(db)

def get_pipeline_service(db: AsyncSession = Depends(get_db)) -> PipelineService:
    return PipelineService(db)

def get_pipeline_read_service(db: AsyncSession = Depends(get_db)) -> PipelineService:
    return PipelineService(db)

def get_job_service(db: AsyncSession = Depends(get_db)) -> JobService:
    return JobService(db)

def get_ai_service(db: AsyncSession = Depends(get_db)) -> AIService:
    return AIService(db)
