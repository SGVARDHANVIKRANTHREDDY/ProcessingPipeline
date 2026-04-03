from app.services.ai_service import AIService
from app.api.v1.deps import get_ai_service
"""
API v1 ai endpoints.
Constraint: Must depend only on Services and schemas.
No raw SQLAlchemy models or sessions operations permitted.
"""
from fastapi import APIRouter, Depends, Request
from app.models import User
from app.core.security.auth import get_current_user
from pydantic import BaseModel
from typing import List, Dict, Any, Optional

router = APIRouter(prefix="/ai", tags=["ai"])

class ExplainRequest(BaseModel):
    steps: List[Dict[str, Any]]

class ExplainResponse(BaseModel):
    explanation: Optional[str] = None
    error: Optional[str] = None

@router.post("/explain", response_model=ExplainResponse)
async def explain_pipeline(
    body: ExplainRequest,
    user: User = Depends(get_current_user),
    request: Request = None
):
    """
    Reverse-translates a JSON array of deterministic dataset pipeline steps
    back into a human-readable explanation of what the pipeline accomplishes.
    """
    res = await service.explain_pipeline(user.id, body.steps, request)
    return ExplainResponse(**res)
