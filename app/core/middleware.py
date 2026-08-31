"""Custom middleware for tracking metrics and other cross-cutting concerns."""

import json
import time
import tracemalloc
from typing import (
    TYPE_CHECKING,
    Callable,
    override,
)

from asgi_correlation_id import correlation_id
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.core.config import settings
from app.core.logging import (
    bind_context,
    clear_context,
    logger,
)
from app.core.metrics import (
    http_request_duration_seconds,
    http_requests_total,
)
from app.utils.auth import (
    TokenType,
    decode_token,
)

if TYPE_CHECKING:
    from pyinstrument import Profiler  # pyright: ignore[reportMissingImports]
    from pyinstrument.renderers import JSONRenderer  # pyright: ignore[reportMissingImports]

    PYINSTRUMENT_AVAILABLE = True
else:
    try:
        from pyinstrument import Profiler
        from pyinstrument.renderers import JSONRenderer

        PYINSTRUMENT_AVAILABLE = True
    except ImportError:
        Profiler = None
        JSONRenderer = None
        PYINSTRUMENT_AVAILABLE = False


class MetricsMiddleware(BaseHTTPMiddleware):
    """Middleware for tracking HTTP request metrics."""

    @override
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Track metrics for each request.

        Args:
            request: The incoming request
            call_next: The next middleware or route handler

        Returns:
            Response: The response from the application
        """
        start_time = time.time()
        status_code = 500

        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            raise
        finally:
            duration = time.time() - start_time

            # Record metrics
            http_requests_total.labels(method=request.method, endpoint=request.url.path, status=status_code).inc()

            http_request_duration_seconds.labels(method=request.method, endpoint=request.url.path).observe(duration)

        return response


class LoggingContextMiddleware(BaseHTTPMiddleware):
    """Adds the calling admin's id to every log line for a request.

    Reads the token without enforcing it — an invalid token is the auth
    dependency's problem, not this middleware's. The point is only that logs
    from a request can be attributed once the request has been identified.
    """

    @override
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Bind the admin id from the bearer token, if there is a valid one.

        Args:
            request: The incoming request
            call_next: The next middleware or route handler

        Returns:
            Response: The response from the application
        """
        try:
            # Clear any context left over from a previous request on this task.
            clear_context()

            auth_header = request.headers.get("authorization")
            if auth_header and auth_header.lower().startswith("bearer "):
                token = auth_header.split(" ", 1)[1]
                # Full verification, including audience, issuer and token type.
                # A challenge token deliberately does not identify a session
                # here — it has not finished authenticating.
                claims = decode_token(token, TokenType.ACCESS)
                if claims is not None:
                    bind_context(admin_id=claims.subject)

            return await call_next(request)

        finally:
            # Always clear, so context cannot leak into the next request.
            clear_context()


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Applies the response headers a browser needs to defend the console.

    This is a JSON API with no HTML surface of its own, so the headers are the
    restrictive set: a CSP that permits nothing, because nothing should ever be
    rendered from an API response, and `nosniff` so a JSON body cannot be
    coaxed into executing as script.

    `Cache-Control: no-store` is the one that matters most here. Analysis
    responses carry policy contents, and a proxy or browser cache holding them
    would be a copy of data this service promises not to keep.
    """

    @override
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Attach security headers to every response.

        Args:
            request: The incoming request
            call_next: The next middleware or route handler

        Returns:
            Response: The response, with headers added.
        """
        response = await call_next(request)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
        )
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
        response.headers["Pragma"] = "no-cache"

        if settings.COOKIE_SECURE:
            # Two years, so the domain stays on the HSTS preload list's minimum.
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"

        return response


class ProfilingMiddleware(BaseHTTPMiddleware):
    """Automatic per-request profiling middleware using pyinstrument.

    Only active when DEBUG=true. Profiles every request and saves an HTML
    flamegraph to PROFILING_DIR when the request exceeds
    PROFILING_THRESHOLD_SECONDS. Files are named {request_id}.html so they
    can be correlated with logs. /tmp is cleaned up automatically by the OS.
    """

    @override
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Profile every request; save enriched JSON if duration exceeds threshold."""
        if not PYINSTRUMENT_AVAILABLE:
            return await call_next(request)

        # Start all three profilers
        tracemalloc.start()
        cpu_start = time.process_time()

        profiler = Profiler(async_mode="enabled")
        with profiler:
            response = await call_next(request)

        # Capture metrics immediately after the request
        cpu_ms = round((time.process_time() - cpu_start) * 1000, 2)
        mem_current_kb, mem_peak_kb = (v // 1024 for v in tracemalloc.get_traced_memory())
        snapshot = tracemalloc.take_snapshot()
        tracemalloc.stop()

        wall_ms = round((profiler.last_session.duration if profiler.last_session else 0.0) * 1000, 2)

        if wall_ms / 1000 >= settings.PROFILING_THRESHOLD_SECONDS:
            raw_id = correlation_id.get() or "unknown"
            if len(raw_id) == 32 and "-" not in raw_id:
                raw_id = f"{raw_id[:8]}-{raw_id[8:12]}-{raw_id[12:16]}-{raw_id[16:20]}-{raw_id[20:]}"

            settings.PROFILING_DIR.mkdir(parents=True, exist_ok=True)
            filepath = settings.PROFILING_DIR / f"{raw_id}.json"

            # Top 20 memory allocators — exclude profiler and stdlib noise
            _excluded = ("tracemalloc", "pyinstrument", "<frozen", "logging/__init__")
            top_allocs = [
                {
                    "file": str(stat.traceback[0].filename).replace(str(__file__).rsplit("/", 3)[0] + "/", ""),
                    "line": stat.traceback[0].lineno,
                    "size_kb": round(stat.size / 1024, 2),
                    "count": stat.count,
                }
                for stat in snapshot.statistics("lineno")
                if not any(ex in str(stat.traceback[0].filename) for ex in _excluded)
            ]

            call_tree = json.loads(profiler.output(renderer=JSONRenderer()))
            report = {
                "request_id": raw_id,
                "endpoint": f"{request.method} {request.url.path}",
                "wall_time_ms": wall_ms,
                "cpu_time_ms": cpu_ms,
                "io_wait_ms": round(wall_ms - cpu_ms, 2),
                "memory_peak_kb": mem_peak_kb,
                "memory_allocated_kb": mem_current_kb,
                "top_memory_allocators": top_allocs,
                "call_tree": call_tree,
            }
            filepath.write_text(json.dumps(report, indent=2))
            logger.debug(
                "slow_request_profile_saved",
                path=request.url.path,
                method=request.method,
                wall_time_ms=wall_ms,
                cpu_time_ms=cpu_ms,
                memory_peak_kb=mem_peak_kb,
                io_wait_ms=round(wall_ms - cpu_ms, 2),
                profile_file=str(filepath),
            )

        return response
