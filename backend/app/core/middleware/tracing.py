import uuid
import logging
from types import ModuleType
from typing import Callable, Awaitable
from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

logger = logging.getLogger(__name__)

class TracingMiddleware(BaseHTTPMiddleware):
    """
    Injects deterministic X-Request-ID and X-Trace-ID into every request/response cycle.
    Essential for ELK/Loki scalable log aggregation and distributed tracing.
    """
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        trace_id = request.headers.get("X-Trace-ID") or req_id
        
        request.state.request_id = req_id
        request.state.trace_id = trace_id
        
        # OTel injection point
        try:
            from opentelemetry import trace
            tracer = trace.get_tracer(__name__)
            with tracer.start_as_current_span(f"{request.method} {request.url.path}") as span:
                span.set_attribute("http.request_id", req_id)
                response = await call_next(request)
                span.set_attribute("http.status_code", response.status_code)
        except ImportError:
            # Fallback if opentelemetry is not installed (e.g. fast dev environments)
            response = await call_next(request)
            
        response.headers["X-Request-ID"] = req_id
        response.headers["X-Trace-ID"] = trace_id
        return response


def setup_otel(app: FastAPI) -> None:
    """
    Configures OpenTelemetry gracefully. Does not crash if dependencies are missing, 
    but warns the operator that tracing spans are disabled.
    """
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app)
        logger.info("OpenTelemetry instrumentation enabled.")
    except ImportError:
        logger.warning("OpenTelemetry missing — distribute tracing spans are disabled.")


def extract_trace_from_celery_kwargs(kwargs):
    return kwargs.get('trace_id', 'unknown'), None, None


def inject_trace_into_celery_kwargs(kwargs):
    pass
