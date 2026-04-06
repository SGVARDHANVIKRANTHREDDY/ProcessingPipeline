"""SQLAlchemy ORM models v10.

New:
  - User.super_admin: only super_admins can grant/revoke admin
  - GlobalAuditEvent: lightweight global sequence for cross-user ordering
    Uses PostgreSQL SEQUENCE (no lock, just INSERT) — global tamper detection
    without per-user chain isolation trade-off.
"""
from sqlalchemy import (
    String, Integer, Float, Boolean, Text, DateTime, BigInteger,
    ForeignKey, JSON, func, Index, UniqueConstraint, Sequence
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime
from app.core.database.engine import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[int]      = mapped_column(Integer, primary_key=True)
    email: Mapped[str]   = mapped_column(String(255), unique=True, nullable=False, index=True)
    auth_provider: Mapped[str] = mapped_column(String(50), default="local")
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool]      = mapped_column(Boolean, default=True)
    is_locked: Mapped[bool]      = mapped_column(Boolean, default=False)
    is_admin: Mapped[bool]       = mapped_column(Boolean, default=False)
    is_super_admin: Mapped[bool] = mapped_column(Boolean, default=False)   # v10: role hierarchy
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    datasets:       Mapped[list["Dataset"]]      = relationship(back_populates="owner", cascade="all, delete-orphan")
    pipelines:      Mapped[list["Pipeline"]]     = relationship(back_populates="owner", cascade="all, delete-orphan")
    jobs:           Mapped[list["Job"]]          = relationship(back_populates="owner", cascade="all, delete-orphan")
    audit_logs:     Mapped[list["AuditLog"]]     = relationship(back_populates="user", cascade="all, delete-orphan")
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (Index("ix_refresh_user_created", "user_id", "created_at"),)
    id: Mapped[int]      = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    family_id: Mapped[str]  = mapped_column(String(64), nullable=False, index=True)
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user: Mapped["User"] = relationship(back_populates="refresh_tokens")


class Dataset(Base):
    __tablename__ = "datasets"
    __table_args__ = (Index("ix_datasets_user_created", "user_id", "created_at"),)
    id: Mapped[int]   = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str]  = mapped_column(String(500), nullable=False)
    storage_key: Mapped[str]        = mapped_column(String(1000), nullable=False)
    file_size_bytes: Mapped[int]    = mapped_column(BigInteger, default=0)
    n_rows: Mapped[int]             = mapped_column(Integer, default=0)
    n_cols: Mapped[int]             = mapped_column(Integer, default=0)
    schema_json: Mapped[dict | None]= mapped_column(JSON, nullable=True)
    processing_status: Mapped[str]  = mapped_column(String(20), default="uploaded")
    profiling_log: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    file_hash: Mapped[str | None]   = mapped_column(String(64), nullable=True)
    is_quarantined: Mapped[bool]    = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime]    = mapped_column(DateTime(timezone=True), server_default=func.now())
    owner:      Mapped["User"]      = relationship(back_populates="datasets")
    pipelines:  Mapped[list["Pipeline"]] = relationship(back_populates="dataset")
    profile:    Mapped["DatasetProfile"] = relationship(back_populates="dataset", uselist=False, cascade="all, delete-orphan")
    executions: Mapped[list["PipelineExecution"]] = relationship(
        foreign_keys="PipelineExecution.input_dataset_id", back_populates="input_dataset")


class DatasetProfile(Base):
    __tablename__ = "dataset_profiles"
    __table_args__ = (Index("ix_profiles_dataset_computed", "dataset_id", "computed_at"),)
    id: Mapped[int]      = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[int] = mapped_column(Integer, ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True, unique=True)
    profile_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    dataset: Mapped["Dataset"] = relationship(back_populates="profile")


class Pipeline(Base):
    __tablename__ = "pipelines"
    __table_args__ = (Index("ix_pipelines_user_updated", "user_id", "updated_at"),)
    id: Mapped[int]     = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    dataset_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str]   = mapped_column(String(255), nullable=False)
    steps: Mapped[list] = mapped_column(JSON, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    owner:      Mapped["User"]    = relationship(back_populates="pipelines")
    dataset:    Mapped["Dataset"] = relationship(back_populates="pipelines")
    executions: Mapped[list["PipelineExecution"]] = relationship(back_populates="pipeline", cascade="all, delete-orphan")


class PipelineExecution(Base):
    __tablename__ = "pipeline_executions"
    __table_args__ = (Index("ix_executions_pipeline_created", "pipeline_id", "created_at"),)
    id: Mapped[int]     = mapped_column(Integer, primary_key=True)
    pipeline_id: Mapped[int] = mapped_column(Integer, ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False, index=True)
    input_dataset_id: Mapped[int] = mapped_column(Integer, ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[str | None]    = mapped_column(String(255), nullable=True, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    status: Mapped[str]           = mapped_column(String(20), default="pending")
    report: Mapped[dict | None]   = mapped_column(JSON, nullable=True)
    output_s3_key: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    output_row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[float | None]    = mapped_column(Float, nullable=True)
    schema_warnings: Mapped[list | None] = mapped_column(JSON, nullable=True)
    error_detail: Mapped[str | None]     = mapped_column(Text, nullable=True)
    retry_count: Mapped[int]             = mapped_column(Integer, default=0)
    trace_id: Mapped[str | None]         = mapped_column(String(64), nullable=True)
    locked_by: Mapped[str | None]        = mapped_column(String(100), nullable=True)
    locked_at: Mapped[datetime | None]   = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime]         = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pipeline:      Mapped["Pipeline"] = relationship(back_populates="executions")
    input_dataset: Mapped["Dataset"]  = relationship(foreign_keys=[input_dataset_id], back_populates="executions")


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_user_created", "user_id", "created_at"),)
    id: Mapped[int]      = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True, index=True)
    job_type: Mapped[str]   = mapped_column(String(50), nullable=False)
    status: Mapped[str]     = mapped_column(String(20), default="pending", index=True)
    payload: Mapped[dict]   = mapped_column(JSON, default=dict)
    result: Mapped[dict | None]  = mapped_column(JSON, nullable=True)
    error: Mapped[str | None]    = mapped_column(Text, nullable=True)
    progress: Mapped[int]        = mapped_column(Integer, default=0)
    retry_count: Mapped[int]     = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None]   = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    owner: Mapped["User"] = relationship(back_populates="jobs")


class AuditLog(Base):
    """
    Per-user hash chain (v9+).
    v10: also includes global_seq for cross-user ordering without lock.
    global_seq is populated by a PostgreSQL SEQUENCE — no advisory lock needed.
    """
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_user_created", "user_id", "created_at"),
        Index("ix_audit_action", "action"),
        Index("ix_audit_resource", "resource_type", "resource_id"),
        Index("ix_audit_global_seq", "global_seq"),
    )
    id: Mapped[int]      = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    action: Mapped[str]  = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    resource_id: Mapped[int | None]   = mapped_column(Integer, nullable=True)
    detail: Mapped[dict | None]       = mapped_column(JSON, nullable=True)
    ip_address: Mapped[str | None]    = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None]    = mapped_column(String(500), nullable=True)
    request_id: Mapped[str | None]    = mapped_column(String(64), nullable=True)
    trace_id: Mapped[str | None]      = mapped_column(String(64), nullable=True)
    entry_hash: Mapped[str | None]    = mapped_column(String(64), nullable=True)
    prev_hash: Mapped[str | None]     = mapped_column(String(64), nullable=True)
    # v10: global ordering via PostgreSQL SEQUENCE — lock-free
    global_seq: Mapped[int | None]    = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    user: Mapped["User | None"] = relationship(back_populates="audit_logs")


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("user_id", "key", name="uq_idempotency_user_key"),
        Index("ix_idempotency_expires", "expires_at"),
    )
    id: Mapped[int]       = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int]  = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    key: Mapped[str]      = mapped_column(String(255), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False)
    request_hash: Mapped[str]  = mapped_column(String(64), nullable=False)
    response_status: Mapped[int | None]  = mapped_column(Integer, nullable=True)
    response_body: Mapped[dict | None]   = mapped_column(JSON, nullable=True)
    processing: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    __table_args__ = (Index("ix_login_attempt_email_time", "email", "attempted_at"),)
    id: Mapped[int]        = mapped_column(Integer, primary_key=True)
    email: Mapped[str]     = mapped_column(String(255), nullable=False, index=True)
    ip_address: Mapped[str] = mapped_column(String(45), nullable=False)
    success: Mapped[bool]  = mapped_column(Boolean, nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DeadLetterEntry(Base):
    __tablename__ = "dead_letter_entries"
    id: Mapped[int]            = mapped_column(Integer, primary_key=True)
    celery_task_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    task_name: Mapped[str]     = mapped_column(String(255), nullable=False)
    queue: Mapped[str]         = mapped_column(String(100), nullable=False)
    args: Mapped[list | None]  = mapped_column(JSON, nullable=True)
    kwargs: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str]         = mapped_column(Text, nullable=False)
    traceback: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int]   = mapped_column(Integer, default=0)
    replay_count: Mapped[int]  = mapped_column(Integer, default=0)
    last_replayed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suppressed: Mapped[bool]   = mapped_column(Boolean, default=False)
    suppressed_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    replayed: Mapped[bool]     = mapped_column(Boolean, default=False)
    replayed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
