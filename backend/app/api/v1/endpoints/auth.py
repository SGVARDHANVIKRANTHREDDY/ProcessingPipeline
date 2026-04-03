"""
API v1 auth endpoints.
Constraint: Must depend only on Services and schemas.
No raw SQLAlchemy models or sessions operations permitted.
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database.engine import get_db
from app.models import User
from app.schemas import UserRegister, UserLogin, TokenPair, RefreshRequest, UserOut
from app.core.security.auth import get_current_user
from app.services.auth_service import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/register", response_model=TokenPair, status_code=201)
async def register(body: UserRegister, request: Request, db: AsyncSession = Depends(get_db)):
    return await auth_service.register(db, body, request)

@router.post("/login", response_model=TokenPair)
async def login(body: UserLogin, request: Request, db: AsyncSession = Depends(get_db)):
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0].strip()
    return await auth_service.login(db, body, ip, request)

@router.post("/refresh", response_model=TokenPair)
async def refresh(body: RefreshRequest, request: Request, db: AsyncSession = Depends(get_db)):
    return await auth_service.refresh(db, body.refresh_token, request)

@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user
