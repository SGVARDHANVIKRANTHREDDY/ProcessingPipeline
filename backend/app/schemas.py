"""
Pydantic v2 schemas — request/response contracts.
Structured errors ensure consistent API surface for all clients.
"""
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from datetime import datetime
from typing import Any, Literal


# ── Structured error envelope ────────────────────────────────
class ErrorDetail(BaseModel):
    type: str
    message: str
    step: int | None = None
    field: str | None = None
    extra: dict | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


# ── Auth ─────────────────────────────────────────────────────
class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    is_active: bool
    created_at: datetime
    model_config = {"from_attributes": True}


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


# ── Dataset ──────────────────────────────────────────────────
class DatasetOut(BaseModel):
    id: int
    name: str
    original_filename: str
    n_rows: int
    n_cols: int
    file_size_bytes: int
    schema_json: dict | None = None
    processing_status: str
    profiling_log: dict | None = None
    created_at: datetime
    model_config = {"from_attributes": True}


class DatasetList(BaseModel):
    items: list[DatasetOut]
    total: int
    page: int
    page_size: int


# ── Pipeline step & params ────────────────────────────────────
ALLOWED_ACTIONS = frozenset({
    "drop_nulls", "fill_nulls", "remove_outliers", "normalize",
    "standardize", "encode_categorical", "filter_rows", "select_columns",
    "drop_columns", "sort_values", "groupby_aggregate",
    "remove_duplicates", "convert_types",
})


class StepParams(BaseModel):
    columns: list[str] = Field(default_factory=list)
    method: str = ""
    threshold: float | None = None
    order: str = ""

    @field_validator("order")
    @classmethod
    def validate_order(cls, v: str) -> str:
        v = v.strip().lower()
        if v and v not in ("asc", "desc"):
            return ""
        return v

    @field_validator("columns")
    @classmethod
    def strip_columns(cls, v: list[str]) -> list[str]:
        return [c.strip() for c in v if c.strip()]


class PipelineStep(BaseModel):
    action: str
    params: StepParams = Field(default_factory=StepParams)

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        if v not in ALLOWED_ACTIONS:
            raise ValueError(f"Unknown action '{v}'. Allowed: {sorted(ALLOWED_ACTIONS)}")
        return v


class PipelineCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    dataset_id: int | None = None
    steps: list[PipelineStep] = Field(default_factory=list)


class PipelineUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    steps: list[PipelineStep] | None = None


class PipelineOut(BaseModel):
    id: int
    name: str
    dataset_id: int | None = None
    steps: list[dict]
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class PipelineList(BaseModel):
    items: list[PipelineOut]
    total: int
    page: int
    page_size: int


# ── Job / Execution ───────────────────────────────────────────
class JobOut(BaseModel):
    id: int
    celery_task_id: str | None = None
    job_type: str
    status: str
    progress: int
    payload: dict
    result: dict | None = None
    error: str | None = None
    retry_count: int
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    model_config = {"from_attributes": True}


class ExecuteRequest(BaseModel):
    dataset_id: int


class StepLog(BaseModel):
    index: int
    action: str
    rows_before: int
    rows_after: int
    delta: int
    ms: float
    status: str
    error: str | None = None


class ExecutionReport(BaseModel):
    status: str
    steps_total: int
    steps_ok: int
    steps_failed: int
    input_count: int
    output_count: int
    total_ms: float
    log: list[StepLog]
    error: str | None = None


class ExecutionOut(BaseModel):
    id: int
    pipeline_id: int
    input_dataset_id: int
    job_id: str | None = None
    status: str
    report: dict | None = None
    output_row_count: int | None = None
    duration_ms: float | None = None
    schema_warnings: list | None = None
    error_detail: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    download_url: str | None = None    # pre-signed S3 URL (populated on GET)
    model_config = {"from_attributes": True}


# ── AI Translate ──────────────────────────────────────────────
class TranslateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=500)
    dataset_id: int | None = None


class TranslateResponse(BaseModel):
    steps: list[dict]
    rejected: list[dict]
    warnings: list[str]


# ── Smart suggestions ─────────────────────────────────────────
class SmartSuggestion(BaseModel):
    prompt: str
    reason: str
    icon: str


# ── Health / metrics ──────────────────────────────────────────
class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    db: str = "ok"
    redis: str = "ok"
    storage: str = "ok"
