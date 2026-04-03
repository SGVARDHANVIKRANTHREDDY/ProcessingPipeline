"""
Config v10 — final production configuration.

Changes from v9:
- S3_USE_AIOBOTO3 is an explicit env var (not import-time detection)
- SUPER_ADMIN_EMAIL: bootstrap super-admin without DB access
- EXECUTION_DEDUP_INCLUDE_STEPS: dedup key now includes pipeline steps hash
- All v9 settings retained
"""
from __future__ import annotations
from pydantic import model_validator
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    APP_NAME: str = "Data Pipeline Studio"
    APP_VERSION: str = "10.0.0"
    DEBUG: bool = False
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "production"

    SECRET_KEY: str = ""
    SECRET_KEY_PREVIOUS: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    REFRESH_TOKEN_ROTATION_ENABLED: bool = True
    REFRESH_TOKEN_FAMILY_MAX_REVOKE: int = 100

    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "dps"
    POSTGRES_USER: str = "dps"
    POSTGRES_PASSWORD: str = ""
    POSTGRES_READ_HOST: str = ""
    POSTGRES_READ_PORT: int = 5432

    @property
    def DATABASE_URL(self) -> str:
        return (f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
                f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}")

    @property
    def DATABASE_URL_READ(self) -> str | None:
        if not self.POSTGRES_READ_HOST:
            return None
        return (f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
                f"@{self.POSTGRES_READ_HOST}:{self.POSTGRES_READ_PORT}/{self.POSTGRES_DB}")

    @property
    def DATABASE_URL_SYNC(self) -> str:
        return (f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
                f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}")

    DB_POOL_SIZE: int = 20
    DB_READ_POOL_SIZE: int = 30
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800

    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str = ""

    @property
    def REDIS_URL(self) -> str:
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @property
    def CELERY_BROKER_URL(self) -> str: return self.REDIS_URL

    @property
    def CELERY_RESULT_BACKEND(self) -> str: return self.REDIS_URL

    S3_ENDPOINT_URL: str = ""
    S3_ACCESS_KEY_ID: str = ""
    S3_SECRET_ACCESS_KEY: str = ""
    S3_BUCKET_RAW: str = "dps-raw"
    S3_BUCKET_OUTPUT: str = "dps-output"
    S3_BUCKET_QUARANTINE: str = "dps-quarantine"
    S3_REGION: str = "us-east-1"
    S3_SIGNED_URL_EXPIRY: int = 3600
    # FIX v10: explicit flag, not import-time detection
    # Set to true only if aioboto3 is actually installed
    S3_USE_AIOBOTO3: bool = False
    S3_THREAD_POOL_SIZE: int = 20
    S3_CIRCUIT_BREAKER_THRESHOLD: int = 3
    S3_CIRCUIT_BREAKER_TIMEOUT: int = 30

    MAX_UPLOAD_SIZE_MB: int = 50
    MAX_UPLOAD_SIZE_BYTES: int = 52_428_800
    MAX_ROWS_FOR_SYNC: int = 50_000
    ALLOWED_EXTENSIONS: frozenset = frozenset({"csv"})
    CSV_MAX_COLUMNS: int = 500
    CSV_MAX_CELL_LENGTH: int = 10_000
    CSV_MAX_ROWS: int = 5_000_000
    CSV_MAX_COLUMN_NAME_LENGTH: int = 255
    CSV_FORCE_UTF8_OUTPUT: bool = True
    UPLOAD_MAX_CONCURRENT: int = 20

    IDEMPOTENCY_TTL_SECONDS: int = 86400
    IDEMPOTENCY_HEADER: str = "Idempotency-Key"
    IDEMPOTENCY_KEY_HEADER: str = "Idempotency-Key"
    IDEMPOTENCY_REDIS_KEY_PREFIX: str = "idem:"
    EXECUTION_DEDUP_TTL_SECONDS: int = 86400
    # FIX v10: dedup key now includes pipeline steps hash
    EXECUTION_DEDUP_INCLUDE_STEPS: bool = True

    DLQ_MAX_REPLAYS: int = 3
    DLQ_REPLAY_BACKOFF_SECONDS: int = 300
    DLQ_POISON_THRESHOLD: int = 3
    DLQ_ALERT_THRESHOLD: int = 5
    DLQ_REDIS_KEY: str = "dps:dlq"
    DLQ_MAX_SIZE: int = 10_000

    LOGIN_MAX_ATTEMPTS: int = 10
    LOGIN_LOCKOUT_SECONDS: int = 900
    PASSWORD_MIN_LENGTH: int = 8
    # v10: bootstrap super-admin via env (for initial deployment)
    SUPER_ADMIN_EMAIL: str = ""

    RATE_LIMIT_DEFAULT: str = "120/minute"
    RATE_LIMIT_AUTH: str = "20/minute"
    RATE_LIMIT_UPLOAD: str = "10/minute"
    RATE_LIMIT_AI: str = "30/minute"
    RATE_LIMIT_EXECUTE: str = "30/minute"
    RATE_LIMIT_ADMIN: str = "30/minute"
    RATE_LIMIT_ADMIN_CRITICAL: str = "5/minute"

    CORS_ORIGINS: str = "http://localhost,http://localhost:5173"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    ANTHROPIC_API_KEY: str = ""
    AI_TIMEOUT_SECONDS: int = 30

    JOB_SOFT_TIME_LIMIT: int = 300
    JOB_HARD_TIME_LIMIT: int = 600
    JOB_MAX_RETRIES: int = 3
    JOB_RETRY_BACKOFF: int = 60

    OTEL_ENABLED: bool = False
    OTEL_ENDPOINT: str = "http://jaeger:4317"
    OTEL_SERVICE_NAME: str = "dps-backend"
    OTEL_TRACE_SAMPLE_RATE: float = 1.0
    SLO_P99_LATENCY_MS: int = 2000
    SLO_AVAILABILITY_PCT: float = 99.9

    AUDIT_LOG_RETENTION_DAYS: int = 365
    AUDIT_HASH_CHAIN_ENABLED: bool = True
    # v10: global event sequence for cross-user ordering (no lock needed — DB sequence)
    AUDIT_GLOBAL_SEQUENCE_ENABLED: bool = True

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False

    @model_validator(mode="after")
    def validate_required_secrets(self) -> "Settings":
        if self.ENVIRONMENT == "test":
            return self
        errors: list[str] = []
        if not self.SECRET_KEY:
            errors.append("SECRET_KEY is empty. Generate: python -c \"import secrets; print(secrets.token_urlsafe(48))\"")
        elif len(self.SECRET_KEY) < 32:
            errors.append("SECRET_KEY must be at least 32 characters")
        elif self.SECRET_KEY in ("CHANGE_ME", "CHANGE_ME_64_CHAR_RANDOM_STRING", "secret"):
            errors.append("SECRET_KEY is a placeholder — set a real value")
        if not self.POSTGRES_PASSWORD:
            errors.append("POSTGRES_PASSWORD is empty")
        if errors:
            msg = "\n".join(f"  - {e}" for e in errors)
            raise ValueError(f"\n\n{'='*60}\nSTARTUP ABORTED:\n{msg}\n{'='*60}\n")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
