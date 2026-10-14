"""Algo Lab FastAPI Application.

Entry point for the Algo Lab Quantitative Research Operating System API.
"""

import hashlib
import hmac
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Dict, List

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from apps.api.core.auth import has_configured_keys, resolve_key_role, validate_api_key_at_startup
from apps.api.core.config import is_invalid_secret, settings
from apps.api.core.project_state import (
    CURRENT_LIFECYCLE_STATE,
    LIVE_TRADING_ENABLED,
    REAL_BROKER_EXECUTION_ENABLED,
    SEMANTIC_VERSION,
    get_canonical_project_status,
)
from apps.api.core.logging import get_logger, redact_sensitive_secrets, setup_logging
from apps.api.routes.health import router as health_router
from apps.api.routes.system import router as system_router
from apps.api.routes.data import router as data_router
from apps.api.routes.experiments import router as experiments_router
from apps.api.routes.datasets import router as datasets_router
from apps.api.routes.replay import router as replay_router
from apps.api.routes.paper_trading import router as paper_trading_router
from apps.api.routes.brokers import router as brokers_router
from apps.api.routes.circuit_breaker import router as circuit_breaker_router
from apps.api.routes.research_ui import router as research_ui_router

# Initialize structured logging
setup_logging()
logger = get_logger("algo_lab.api")


PUBLIC_PATHS = {
    "/",
    "/health",
    "/health/ready",
    "/health/live",
    f"{settings.API_V1_PREFIX}/health",
    f"{settings.API_V1_PREFIX}/health/ready",
    f"{settings.API_V1_PREFIX}/health/live",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/favicon.ico",
}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan management: fail-closed in production with secret redaction."""
    # Enforce non-negotiable safety invariants at startup
    if LIVE_TRADING_ENABLED or REAL_BROKER_EXECUTION_ENABLED or settings.ALLOW_LIVE_TRADING or settings.ALLOW_REAL_BROKER_EXECUTION:
        raise RuntimeError(
            "CRITICAL SAFETY VIOLATION: LIVE_TRADING_ENABLED or REAL_BROKER_EXECUTION_ENABLED is true. "
            "Algo Lab must fail closed and cannot start with live order routing enabled."
        )

    try:
        validate_api_key_at_startup()

        if settings.ENVIRONMENT == "production":
            admin_key = (
                settings.ALGO_LAB_API_KEY
                or getattr(settings, "ALGO_LAB_API_KEY_SYSTEM_ADMIN", "")
                or getattr(settings, "ALGO_LAB_API_KEY_ADMIN", "")
            )
            if is_invalid_secret(admin_key):
                raise RuntimeError("ALGO_LAB_API_KEY must be configured in production.")
            if is_invalid_secret(settings.BROKER_CREDENTIAL_ENCRYPTION_KEY):
                raise RuntimeError("BROKER_CREDENTIAL_ENCRYPTION_KEY must be configured in production.")
            if is_invalid_secret(settings.CIRCUIT_BREAKER_STATE_KEY):
                raise RuntimeError("CIRCUIT_BREAKER_STATE_KEY must be configured in production.")
            if is_invalid_secret(settings.CIRCUIT_BREAKER_REARM_SECRET):
                raise RuntimeError("CIRCUIT_BREAKER_REARM_SECRET must be configured in production.")

        logger.info(
            "Algo Lab OS API starting up",
            extra={
                "version": SEMANTIC_VERSION,
                "lifecycle_state": CURRENT_LIFECYCLE_STATE.value,
                "environment": settings.ENVIRONMENT,
                "allow_live_trading": False,
                "allow_real_broker": False,
            },
        )
        yield
        logger.info("Algo Lab OS API shutting down")
    except Exception as exc:
        sanitized_msg = redact_sensitive_secrets(str(exc))
        logger.error(f"Application startup failure: {sanitized_msg}")
        raise RuntimeError(f"Application startup failure: {sanitized_msg}") from None


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.PROJECT_VERSION,
    description="Quantitative Research and Decision Operating System for Indian Markets.",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Sanitized validation error handler that strips sensitive input values."""
    sanitized_errors = []
    for err in exc.errors():
        sanitized = {
            "type": err.get("type"),
            "loc": err.get("loc"),
            "msg": redact_sensitive_secrets(str(err.get("msg", ""))),
        }
        sanitized_errors.append(sanitized)
    return JSONResponse(
        status_code=422,
        content={"detail": sanitized_errors},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    """Sanitized global exception handler preventing credentials or internal secrets leakage."""
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": redact_sensitive_secrets(str(exc.detail))},
        )
    sanitized_msg = redact_sensitive_secrets(str(exc))
    logger.error(f"Internal server error: {sanitized_msg}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )



_RATE_LIMIT_STORE: Dict[str, List[float]] = {}


@app.middleware("http")
async def security_and_telemetry_middleware(request: Request, call_next):
    """Middleware enforcing API authentication, strict request size limits, rate limits, and nonce-based CSP."""
    path = request.url.path
    csp_nonce = secrets.token_hex(16)
    request.state.csp_nonce = csp_nonce
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    start_time = time.perf_counter()

    # 1. Enforce Request Body Size Limits
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > settings.REQUEST_BODY_MAX_BYTES:
                return JSONResponse(
                    status_code=413,
                    content={"detail": f"Request body exceeds maximum allowed size of {settings.REQUEST_BODY_MAX_BYTES} bytes."},
                    headers={"X-Request-ID": request_id},
                )
        except ValueError:
            pass

    # 2. In-Memory Sliding Window Rate Limiting (per client IP / key)
    client_ident = request.headers.get("X-API-Key") or (request.client.host if request.client else "anonymous")
    now_ts = time.time()
    timestamps = _RATE_LIMIT_STORE.get(client_ident, [])
    cutoff = now_ts - 60.0
    timestamps = [t for t in timestamps if t > cutoff]
    if len(timestamps) >= settings.RATE_LIMIT_REQUESTS_PER_MINUTE:
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded. Maximum requests per minute cap reached."},
            headers={"X-Request-ID": request_id, "Retry-After": "60"},
        )
    timestamps.append(now_ts)
    _RATE_LIMIT_STORE[client_ident] = timestamps

    # 3. Enforce API Key Authentication on all non-public routes
    # Notice: /research is authenticated by default
    is_public = (
        path in PUBLIC_PATHS
        or path.startswith("/docs")
        or path.startswith("/redoc")
        or path.startswith("/openapi.json")
    )

    actor_id = "anonymous"
    actor_role = "none"

    if not is_public:
        enforce_auth = (
            settings.ENVIRONMENT == "production"
            or (has_configured_keys() and not settings.ALLOW_LOCAL_AUTH_BYPASS)
        )
        if enforce_auth:
            api_key = request.headers.get("X-API-Key", "")
            if not api_key:
                return JSONResponse(status_code=401, content={"detail": "X-API-Key header required"}, headers={"X-Request-ID": request_id})

            role = resolve_key_role(api_key)
            if role is None:
                return JSONResponse(status_code=403, content={"detail": "Invalid API key"}, headers={"X-Request-ID": request_id})
            actor_role = role.value
            actor_id = f"key_{hashlib.sha256(api_key.encode()).hexdigest()[:8]}"

    response = await call_next(request)

    process_time = time.perf_counter() - start_time
    response.headers["X-Process-Time"] = f"{process_time:.6f}"
    response.headers["X-Request-ID"] = request_id

    # Defense in Depth: Hardened Nonce-based Security Headers
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        f"script-src 'self' 'nonce-{csp_nonce}'; "
        f"style-src 'self' 'nonce-{csp_nonce}'; "
        "img-src 'self' data: https:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none';"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    if request.url.scheme == "https" or request.headers.get("X-Forwarded-Proto") == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    # Structured telemetry logging
    logger.info(
        "HTTP Request completed",
        extra={
            "request_id": request_id,
            "actor_id": actor_id,
            "role": actor_role,
            "method": request.method,
            "endpoint": path,
            "status_code": response.status_code,
            "latency_ms": round(process_time * 1000, 2),
        },
    )

    return response


# Mount Root / Health probes
app.include_router(health_router)

# Mount API v1 Routers
app.include_router(health_router, prefix=settings.API_V1_PREFIX)
app.include_router(system_router, prefix=settings.API_V1_PREFIX)
app.include_router(data_router, prefix=settings.API_V1_PREFIX)
app.include_router(experiments_router, prefix=settings.API_V1_PREFIX)
app.include_router(datasets_router, prefix=settings.API_V1_PREFIX)
app.include_router(replay_router, prefix=settings.API_V1_PREFIX)
app.include_router(paper_trading_router, prefix=settings.API_V1_PREFIX)
app.include_router(brokers_router, prefix=settings.API_V1_PREFIX)
app.include_router(circuit_breaker_router, prefix=settings.API_V1_PREFIX)
app.include_router(research_ui_router)


@app.get("/", summary="Root endpoint")
async def root():
    status_info = get_canonical_project_status()
    return {
        **status_info,
        "name": settings.PROJECT_NAME,
        "stage": status_info["lifecycle_state"],
        "description": "Systematic research and decision platform for Indian markets",
        "research_ui_url": "/research",
        "principles_url": f"{settings.API_V1_PREFIX}/system/principles",
        "system_status_url": f"{settings.API_V1_PREFIX}/system/info",
        "docs_url": "/docs",
        "safeguards": {
            "live_trading_allowed": False,
            "real_broker_connected": False,
            "data_validation_enforced": settings.REQUIRE_DATA_VALIDATION,
            "lookahead_protection_enforced": settings.ENFORCE_STRICT_LOOKAHEAD_PROTECTION,
        },
    }
