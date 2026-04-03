from app.services.pipeline_service import PipelineService
from app.api.v1.deps import get_pipeline_service
"""
API v1 pipelines endpoints.
Constraint: Must depend only on Services and schemas.
No raw SQLAlchemy models or sessions operations permitted.
"""
from fastapi import APIRouter, Depends, Request
from typing import List, Dict, Any

from app.core.database.routing import read_db, write_db
from app.models import User
from app.core.security.auth import get_current_user
from app.schemas import (PipelineCreate, PipelineUpdate, PipelineOut, PipelineList,
                       ExecuteRequest, ExecutionOut, TranslateRequest, TranslateResponse)
from app.core.security.idempotency import require_idempotency_key

router = APIRouter(prefix="/pipelines", tags=["pipelines"])

@router.post("", response_model=PipelineOut, status_code=201)
async def create_pipeline(body: PipelineCreate,
                           user: User = Depends(get_current_user), request: Request = None):
    return await service.create_pipeline(user.id, body, request)

@router.get("", response_model=PipelineList)
async def list_pipelines(page: int = 1, page_size: int = 20,
                          user: User = Depends(get_current_user)):
    return await service.list_pipelines(user.id, page, page_size)

@router.get("/{pid}", response_model=PipelineOut)
async def get_pipeline(pid: int,
                        user: User = Depends(get_current_user)):
    return await service.get_pipeline(pid, user.id)

@router.patch("/{pid}", response_model=PipelineOut)
async def update_pipeline(pid: int, body: PipelineUpdate,
                           user: User = Depends(get_current_user), request: Request = None):
    return await service.update_pipeline(pid, user.id, body, request)

@router.delete("/{pid}", status_code=204)
async def delete_pipeline(pid: int,
                           user: User = Depends(get_current_user), request: Request = None):
    await service.delete_pipeline(pid, user.id, request)

@router.post("/translate", response_model=TranslateResponse)
async def translate(body: TranslateRequest, 
                    user: User = Depends(get_current_user), request: Request = None):
    return await service.translate_prompt(body.prompt, body.dataset_id, user.id, request)

@router.post("/{pid}/execute", response_model=dict, status_code=202)
async def execute(
    pid: int,
    body: ExecuteRequest,
    request: Request,
    idem_key: str = Depends(require_idempotency_key),
    user: User = Depends(get_current_user),
):
    body_bytes = await request.body()
    return await service.execute_pipeline(pid, user.id, body, idem_key, body_bytes, request)

@router.get("/metrics/activity")
async def get_activity_metrics(user: User = Depends(get_current_user), service: PipelineService = Depends(get_pipeline_service)):
    return await service.get_activity_metrics(user.id)

@router.get("/{pid}/executions", response_model=List[ExecutionOut])
async def list_executions(pid: int,
                           user: User = Depends(get_current_user)):
    return await service.list_executions(pid, user.id)

@router.get("/{pid}/executions/{eid}", response_model=ExecutionOut)
async def get_execution(pid: int, eid: int,
                         user: User = Depends(get_current_user)):
    return await service.get_execution(pid, eid, user.id)

@router.post("/{pid}/fork", response_model=PipelineOut, status_code=201)
async def fork_pipeline(pid: int,
                        user: User = Depends(get_current_user), request: Request = None):
    return await service.fork_pipeline(pid, user.id, request)
