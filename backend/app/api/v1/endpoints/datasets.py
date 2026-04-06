from app.services.dataset_service import DatasetService
from app.api.v1.deps import get_dataset_service
"""
API v1 datasets endpoints.
Constraint: Must depend only on Services and schemas.
No raw SQLAlchemy models or sessions operations permitted.
"""
import asyncio
from fastapi import APIRouter, Depends, Request, UploadFile, File, HTTPException
from app.core.exceptions import ValidationError, DomainError
from app.core.database.routing import read_db, write_db
from app.models import User
from app.core.security.auth import get_current_user
from app.schemas import DatasetOut, DatasetList
from app.core.security.idempotency import get_or_create_idempotency_key, hash_request_body
from app.core.config import get_settings

settings = get_settings()
router = APIRouter(prefix="/datasets", tags=["datasets"])

@router.post("/upload", response_model=DatasetOut, status_code=202)
async def upload_dataset(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    service: DatasetService = Depends(get_dataset_service)
):
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="Only .csv files are supported")
    
    # Read keeping track of size
    max_bytes = getattr(settings, "MAX_UPLOAD_SIZE_MB", 50) * 1024 * 1024
    content = b""
    total_size = 0
    while chunk := await file.read(8192):
        total_size += len(chunk)
        if total_size > max_bytes:
            raise HTTPException(status_code=413, detail=f"File too large. Max {max_bytes//(1024*1024)}MB allowed.")
        content += chunk

    return await service.upload_dataset(user=user, content=content, filename=file.filename)

@router.get("", response_model=DatasetList)
async def list_datasets(
    page: int = 1, page_size: int = 20,
    user: User = Depends(get_current_user),
    service: DatasetService = Depends(get_dataset_service)
):
    page_size = min(page_size, 100)
    offset = (page - 1) * page_size
    items, total = await service.list_datasets(user.id, offset, page_size)
    return {"items": items, "total": total, "page": page, "page_size": page_size}

@router.get("/{dataset_id}", response_model=DatasetOut)
async def get_dataset(dataset_id: int, user: User = Depends(get_current_user), service: DatasetService = Depends(get_dataset_service)):
    return await service.get_dataset(dataset_id, user.id)

@router.delete("/{dataset_id}", status_code=204)
async def delete_dataset(dataset_id: int, request: Request, user: User = Depends(get_current_user), service: DatasetService = Depends(get_dataset_service)):
    await service.delete_dataset(dataset_id, user.id, request)
