"""
Middleware package v8.
idempotency.py REMOVED — was Redis-based, caused double-execution on Redis failures.
Idempotency now handled at service layer (services/security/idempotency.py).
tracing.py — correlation IDs + OpenTelemetry.
"""
