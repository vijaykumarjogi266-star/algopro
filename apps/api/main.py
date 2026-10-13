"""Algo Lab FastAPI Application.

Entry point for the Algo Lab Quantitative Research Operating System API.
"""

import hashlib
import hmac
import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from apps.api.core.auth import validate_api_key_at_startup
from apps.api.core.config import is_invalid_secret, settings
from apps.api.core.logging import get_logger, setup_logging
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
    f"{settings.API_V1_PREFIX}/health",
    f"{settings.API_V1_PREFIX}/health/ready",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/favicon.ico",
}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan management: fail-closed in production."""
    validate_api_key_at_startup()

    if settings.ENVIRONMENT == "production":
        if is_invalid_secret(settings.ALGO_LAB_API_KEY):
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
            "version": settings.PROJECT_VERSION,
            "environment": settings.ENVIRONMENT,
            "allow_live_trading": settings.ALLOW_LIVE_TRADING,
            "allow_real_broker": settings.ALLOW_REAL_BROKER_EXECUTION,
        },
    )
    yield
    logger.info("Algo Lab OS API shutting down")


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
            "msg": err.get("msg"),
        }
        sanitized_errors.append(sanitized)
    return JSONResponse(
        status_code=422,
        content={"detail": sanitized_errors},
    )


@app.middleware("http")
async def security_and_telemetry_middleware(request: Request, call_next):
    """Middleware enforcing API authentication, security headers, and request tracking."""
    path = request.url.path

    # Enforce API Key authentication on all non-public routes in production or when auth is enabled
    is_public = path in PUBLIC_PATHS or path.startswith("/docs") or path.startswith("/redoc")

    if not is_public:
        enforce_auth = (
            settings.ENVIRONMENT == "production"
            or (bool(settings.ALGO_LAB_API_KEY) and not settings.ALLOW_LOCAL_AUTH_BYPASS)
        )
        if enforce_auth:
            api_key = request.headers.get("X-API-Key", "")
            if not api_key:
                return JSONResponse(status_code=401, content={"detail": "X-API-Key header required"})

            configured_key = settings.ALGO_LAB_API_KEY.strip() if settings.ALGO_LAB_API_KEY else ""
            if not configured_key:
                return JSONResponse(status_code=500, content={"detail": "ALGO_LAB_API_KEY not configured on server"})

            provided_hash = hashlib.sha256(api_key.encode()).digest()
            expected_hash = hashlib.sha256(configured_key.encode()).digest()
            if not hmac.compare_digest(provided_hash, expected_hash):
                return JSONResponse(status_code=403, content={"detail": "Invalid API key"})

    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    start_time = time.perf_counter()

    response = await call_next(request)

    process_time = time.perf_counter() - start_time
    response.headers["X-Process-Time"] = f"{process_time:.6f}"
    response.headers["X-Request-ID"] = request_id

    # Defense in Depth: Security headers
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "object-src 'none'; "
        "base-uri 'self';"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"

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
    return {
        "name": settings.PROJECT_NAME,
        "version": settings.PROJECT_VERSION,
        "stage": "Stage 1: Foundation",
        "description": "Systematic research and decision platform for Indian markets",
        "research_ui_url": "/research",
        "principles_url": f"{settings.API_V1_PREFIX}/system/principles",
        "system_status_url": f"{settings.API_V1_PREFIX}/system/info",
        "docs_url": "/docs",
        "safeguards": {
            "live_trading_allowed": settings.ALLOW_LIVE_TRADING,
            "real_broker_connected": settings.ALLOW_REAL_BROKER_EXECUTION,
            "data_validation_enforced": settings.REQUIRE_DATA_VALIDATION,
            "lookahead_protection_enforced": settings.ENFORCE_STRICT_LOOKAHEAD_PROTECTION,
        },
    }
