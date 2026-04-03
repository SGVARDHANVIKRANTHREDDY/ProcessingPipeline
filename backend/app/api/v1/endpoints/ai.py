"""
API v1 ai endpoints.
Constraint: Must depend only on Services and schemas.
No raw SQLAlchemy models or sessions operations permitted.
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database.engine import get_db
from app.models import User
from app.core.security.auth import get_current_user
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from app.services.ai_service import ai_service

router = APIRouter(prefix="/ai", tags=["ai"])

class ExplainRequest(BaseModel):
    steps: List[Dict[str, Any]]

class ExplainResponse(BaseModel):
    explanation: Optional[str] = None
    error: Optional[str] = None

@router.post("/explain", response_model=ExplainResponse)
async def explain_pipeline(
    body: ExplainRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    request: Request = None
):
    """
    Reverse-translates a JSON array of deterministic dataset pipeline steps
    back into a human-readable explanation of what the pipeline accomplishes.
    """
    res = await ai_service.explain_pipeline(db, user.id, body.steps, request)
    return ExplainResponse(**res)
