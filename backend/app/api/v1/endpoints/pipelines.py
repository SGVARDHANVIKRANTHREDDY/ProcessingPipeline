"""
API v1 pipelines endpoints.
Constraint: Must depend only on Services and schemas.
No raw SQLAlchemy models or sessions operations permitted.
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Dict, Any

from app.core.database.routing import read_db, write_db
from app.models import User
from app.core.security.auth import get_current_user
from app.schemas import (PipelineCreate, PipelineUpdate, PipelineOut, PipelineList,
                       ExecuteRequest, ExecutionOut, TranslateRequest, TranslateResponse)
from app.core.security.idempotency import require_idempotency_key
from app.services.pipeline_service import pipeline_service

router = APIRouter(prefix="/pipelines", tags=["pipelines"])

@router.post("", response_model=PipelineOut, status_code=201)
async def create_pipeline(body: PipelineCreate, db: AsyncSession = Depends(write_db),
                           user: User = Depends(get_current_user), request: Request = None):
    return await pipeline_service.create_pipeline(db, user.id, body, request)

@router.get("", response_model=PipelineList)
async def list_pipelines(page: int = 1, page_size: int = 20,
                          db: AsyncSession = Depends(read_db),
                          user: User = Depends(get_current_user)):
    return await pipeline_service.list_pipelines(db, user.id, page, page_size)

@router.get("/{pid}", response_model=PipelineOut)
async def get_pipeline(pid: int, db: AsyncSession = Depends(read_db),
                        user: User = Depends(get_current_user)):
    return await pipeline_service.get_pipeline(db, pid, user.id)

@router.patch("/{pid}", response_model=PipelineOut)
async def update_pipeline(pid: int, body: PipelineUpdate, db: AsyncSession = Depends(write_db),
                           user: User = Depends(get_current_user), request: Request = None):
    return await pipeline_service.update_pipeline(db, pid, user.id, body, request)

@router.delete("/{pid}", status_code=204)
async def delete_pipeline(pid: int, db: AsyncSession = Depends(write_db),
                           user: User = Depends(get_current_user), request: Request = None):
    await pipeline_service.delete_pipeline(db, pid, user.id, request)

@router.post("/translate", response_model=TranslateResponse)
async def translate(body: TranslateRequest, db: AsyncSession = Depends(read_db), 
                    user: User = Depends(get_current_user), request: Request = None):
    return await pipeline_service.translate_prompt(db, body.prompt, body.dataset_id, user.id, request)

@router.post("/{pid}/execute", response_model=dict, status_code=202)
async def execute(
    pid: int,
    body: ExecuteRequest,
    request: Request,
    idem_key: str = Depends(require_idempotency_key),
    db: AsyncSession = Depends(write_db),
    user: User = Depends(get_current_user),
):
    body_bytes = await request.body()
    return await pipeline_service.execute_pipeline(db, pid, user.id, body, idem_key, body_bytes, request)

@router.get("/metrics/activity")
async def get_activity_metrics(db: AsyncSession = Depends(read_db), user: User = Depends(get_current_user)):
    return await pipeline_service.get_activity_metrics(db, user.id)

@router.get("/{pid}/executions", response_model=List[ExecutionOut])
async def list_executions(pid: int, db: AsyncSession = Depends(read_db),
                           user: User = Depends(get_current_user)):
    return await pipeline_service.list_executions(db, pid, user.id)

@router.get("/{pid}/executions/{eid}", response_model=ExecutionOut)
async def get_execution(pid: int, eid: int, db: AsyncSession = Depends(read_db),
                         user: User = Depends(get_current_user)):
    return await pipeline_service.get_execution(db, pid, eid, user.id)

@router.post("/{pid}/fork", response_model=PipelineOut, status_code=201)
async def fork_pipeline(pid: int, db: AsyncSession = Depends(write_db),
                        user: User = Depends(get_current_user), request: Request = None):
    return await pipeline_service.fork_pipeline(db, pid, user.id, request)
