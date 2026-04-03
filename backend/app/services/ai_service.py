"""
AI Service
Constraint: Domain objects, No HTTP details.
"""
from typing import Dict, Any, List, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.ai_translator import explain_steps
from app.core.security.audit import audit, AuditAction

class AIService:
    def __init__(self, db):
        self.db = db

    async def explain_pipeline(self, user_id: int, steps: List[Dict[str, Any]], request_for_audit: Any = None) -> Dict[str, Any]:
        explanation, error = await explain_steps(steps)
        await audit(
            db,
            AuditAction.PIPELINE_TRANSLATE,
            user_id=user_id,
            detail={"steps_count": len(steps), "type": "explain"},
            request=request_for_audit
        )
        return {"explanation": explanation, "error": error}

