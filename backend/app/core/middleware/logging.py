import logging
import time
from typing import Callable, Awaitable
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response, PlainTextResponse

logger = logging.getLogger("api")

class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    """
    Records request duration, correlated request/trace IDs, and standardizes
    the format for downstream aggregators like Datadog, ELK, or Loki.
    """
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        start_time = time.perf_counter()
        
        # Capture client IP correctly (especially behind proxies)
        client_host = request.client.host if request.client else "unknown"
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            client_host = forwarded.split(",")[0].strip()

        try:
            response = await call_next(request)
            process_time_ms = (time.perf_counter() - start_time) * 1000
            
            # Use request_id established by TracingMiddleware
            req_id = getattr(request.state, "request_id", "-")
            
            # Simple format: In a true FAANG environment this would be native JSON (e.g., structlog)
            logger.info(
                "method=%s path=%s status=%s duration_ms=%.2f ip=%s request_id=%s",
                request.method,
                request.url.path,
                response.status_code,
                process_time_ms,
                client_host,
                req_id
            )
            return response
            
        except Exception as e:
            process_time_ms = (time.perf_counter() - start_time) * 1000
            req_id = getattr(request.state, "request_id", "-")
            logger.exception(
                "UNHANDLED_EXCEPTION method=%s path=%s duration_ms=%.2f ip=%s request_id=%s error=%s",
                request.method,
                request.url.path,
                process_time_ms,
                client_host,
                req_id,
                str(e)
            )
            raise

def setup_logging(debug: bool) -> None:
    """Configures systemic log levels and format."""
    level = logging.DEBUG if debug else logging.INFO
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    logging.basicConfig(level=level, format=log_format)

async def metrics_endpoint() -> Response:
    """
    Exposes a Prometheus-compatible metrics payload.
    In real scale, you'd use prometheus_client here.
    """
    # Placeholder for actual prometheus metrics endpoint
    metric_text = (
        "# TYPE api_uptime_seconds gauge\n"
        "api_uptime_seconds 12345.0\n"
    )
    return PlainTextResponse(content=metric_text)
