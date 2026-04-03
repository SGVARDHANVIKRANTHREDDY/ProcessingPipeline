"""FastAPI v8 — startup validation, no broken middleware, clean error handling."""
from contextlib import asynccontextmanager
import logging
import redis.asyncio as aioredis
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.core.config import get_settings
from app.core.database.engine import engine
from app.core.middleware.logging import StructuredLoggingMiddleware, setup_logging
from app.core.middleware.tracing import TracingMiddleware, setup_otel
from .services.storage import ensure_buckets_async
from app.api.v1.endpoints import auth, datasets, pipelines, jobs, admin, ai

# Config validates at import — if SECRET_KEY is missing, app crashes here
# with a clear error before binding any port.
settings = get_settings()
setup_logging(settings.DEBUG)
logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address, default_limits=[settings.RATE_LIMIT_DEFAULT])


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=== DPS v%s starting (env=%s) ===", settings.APP_VERSION, settings.ENVIRONMENT)

    # DB check
    try:
        from sqlalchemy import text
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Database OK")
    except Exception as e:
        logger.critical("Database unavailable: %s", e)

    # Redis check
    try:
        r = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=3)
        await r.ping(); await r.aclose()
        logger.info("Redis OK")
    except Exception as e:
        logger.warning("Redis unavailable: %s", e)

    # S3 buckets
    try:
        await ensure_buckets_async()
        logger.info("S3 buckets OK")
    except Exception as e:
        logger.warning("S3 bucket setup: %s", e)

    logger.info("=== DPS ready ===")
    yield
    logger.info("=== DPS shutdown ===")
    await engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# Setup OpenTelemetry (gracefully skipped if not installed/configured)
setup_otel(app)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-Trace-ID"],
)

# Tracing (correlation IDs + optional OTEL)
app.add_middleware(TracingMiddleware)

# Structured logging
app.add_middleware(StructuredLoggingMiddleware)



from app.core.exceptions import (
    NotFoundError, ValidationError, ConflictError, 
    UnauthorizedError, ForbiddenError, DependencyError, DomainError
)

@app.exception_handler(NotFoundError)
async def not_found_handler(request: Request, exc: NotFoundError):
    logger.warning('NotFoundError: %s', exc.message)
    return JSONResponse(status_code=404, content={'error': exc.message})

@app.exception_handler(ValidationError)
async def validation_handler(request: Request, exc: ValidationError):
    logger.warning('ValidationError: %s', exc.message)
    return JSONResponse(status_code=400, content={'error': exc.message})

@app.exception_handler(ConflictError)
async def conflict_handler(request: Request, exc: ConflictError):
    logger.warning('ConflictError: %s', exc.message)
    return JSONResponse(status_code=409, content={'error': exc.message})

@app.exception_handler(UnauthorizedError)
async def unauthorized_handler(request: Request, exc: UnauthorizedError):
    logger.warning('UnauthorizedError: %s', exc.message)
    return JSONResponse(status_code=401, content={'error': exc.message})

@app.exception_handler(ForbiddenError)
async def forbidden_handler(request: Request, exc: ForbiddenError):
    logger.warning('ForbiddenError: %s', exc.message)
    return JSONResponse(status_code=403, content={'error': exc.message})

@app.exception_handler(DependencyError)
async def dependency_handler(request: Request, exc: DependencyError):
    logger.error('DependencyError: %s - %s', exc.message, str(exc.context))
    return JSONResponse(status_code=503, content={'error': 'Service temporarily unavailable'})

@app.exception_handler(DomainError)
async def domain_handler(request: Request, exc: DomainError):
    logger.error('DomainError: %s', exc.message)
    return JSONResponse(status_code=500, content={'error': 'Internal server error'})

@app.exception_handler(HTTPException)
async def http_exc_handler(request: Request, exc: HTTPException):
    # FIX: never leak stack traces or infrastructure details in error responses
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"type": "HTTP_ERROR", "message": exc.detail,
                           "status_code": exc.status_code,
                           "request_id": getattr(request.state, "request_id", None)}},
    )


@app.exception_handler(Exception)
async def unhandled_exc_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": {"type": "INTERNAL_ERROR",
                           "message": "An unexpected error occurred.",
                           "request_id": getattr(request.state, "request_id", None)}},
    )


PREFIX = settings.API_V1_STR
app.include_router(auth.router,      prefix=PREFIX)
app.include_router(datasets.router,  prefix=PREFIX)
app.include_router(pipelines.router, prefix=PREFIX)
app.include_router(jobs.router,      prefix=PREFIX)
app.include_router(admin.router,     prefix=PREFIX)
app.include_router(ai.router,        prefix=PREFIX)


@app.get("/health", tags=["ops"])
async def health():
    checks = {"db": "ok", "redis": "ok", "storage": "ok"}
    try:
        from sqlalchemy import text
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as e:
        checks["db"] = "error"   # FIX: never expose error details in health endpoint

    try:
        r = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        await r.ping(); await r.aclose()
    except Exception:
        checks["redis"] = "error"

    try:
        from .services.storage import object_exists_async
        await object_exists_async("__healthcheck__", settings.S3_BUCKET_RAW)
    except RuntimeError:  # circuit breaker open — expected
        checks["storage"] = "degraded"
    except Exception:
        checks["storage"] = "error"

    all_ok = all(v == "ok" for v in checks.values())
    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={"status": "ok" if all_ok else "degraded",
                 "version": settings.APP_VERSION, **checks},
    )


@app.get("/metrics", tags=["ops"], include_in_schema=False)
async def metrics():
    from app.core.middleware.logging import metrics_endpoint
    return await metrics_endpoint()
