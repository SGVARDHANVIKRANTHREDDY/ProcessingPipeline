from app.services.dataset_service import DatasetService
from app.api.v1.deps import get_dataset_service
"""
API v1 datasets endpoints.
Constraint: Must depend only on Services and schemas.
No raw SQLAlchemy models or sessions operations permitted.
"""
import asyncio
from fastapi import APIRouter, Depends, Request
from app.core.exceptions import ValidationError, DomainError
from app.core.database.routing import read_db, write_db
from app.models import User
from app.core.security.auth import get_current_user
from app.schemas import DatasetOut, DatasetList
from app.core.security.idempotency import get_or_create_idempotency_key, hash_request_body
from app.core.config import get_settings

settings = get_settings()
router = APIRouter(prefix="/datasets", tags=["datasets"])
_upload_semaphore = asyncio.Semaphore(settings.UPLOAD_MAX_CONCURRENT)

@router.post("", response_model=dict, status_code=202)
async def upload_dataset(
    request: Request,
    user: User = Depends(get_current_user),
    service: DatasetService = Depends(get_dataset_service),
    db = Depends(write_db)
):
    content_length = request.headers.get("content-length")
    if content_length:
        cl = int(content_length)
        if cl > settings.MAX_UPLOAD_SIZE_BYTES:
            raise ValidationError(f"File too large ({cl} bytes). Max {settings.MAX_UPLOAD_SIZE_BYTES} limit")

    if _upload_semaphore.locked() and _upload_semaphore._value == 0:
        raise ValidationError("Upload queue full - please retry in a few seconds")

    async with _upload_semaphore:
        form = await request.form()
        file = form.get("file")
        if not file:
            raise ValidationError("No file provided")

        chunks = []
        total = 0
        async for chunk in file.file:
            total += len(chunk)
            if total > settings.MAX_UPLOAD_SIZE_BYTES:
                raise ValidationError(f"File exceeds {settings.MAX_UPLOAD_SIZE_BYTES} limit")
            chunks.append(chunk)
        content = b"".join(chunks)

        idem_key = get_or_create_idempotency_key(request)
        if idem_key:
            idem_result = await get_or_create_idempotency_key(
                db, user.id, idem_key, "/datasets", hash_request_body(content)
            )
            if idem_result["action"] == "replay":
                return idem_result["body"]

        filename = file.filename or "upload.csv"
        return await service.upload_dataset(user, content, filename, idem_key, request)

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

@router.get("/{dataset_id}/suggestions")
async def get_suggestions(dataset_id: int, user: User = Depends(get_current_user), service: DatasetService = Depends(get_dataset_service)):
    suggestions = await service.get_suggestions(dataset_id, user.id)
    return {"suggestions": suggestions}

@router.get("/compare")
async def compare_datasets(
    id1: int, id2: int,
    user: User = Depends(get_current_user),
    service: DatasetService = Depends(get_dataset_service)
):
    return await service.compare_datasets(id1, id2, user.id)

@router.get("/{dataset_id}/anomalies")
async def get_dataset_anomalies(
    dataset_id: int,
    user: User = Depends(get_current_user),
    service: DatasetService = Depends(get_dataset_service)
):
    return await service.get_anomalies(dataset_id, user.id)

@router.delete("/{dataset_id}", status_code=204)
async def delete_dataset(dataset_id: int, request: Request, user: User = Depends(get_current_user), service: DatasetService = Depends(get_dataset_service)):
    await service.delete_dataset(dataset_id, user.id, request)
