"""Algo Lab FastAPI Application.

Entry point for the Algo Lab Quantitative Research Operating System API.
"""

import hashlib
import hmac
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from apps.api.core.auth import validate_api_key_at_startup
from apps.api.core.config import settings
from apps.api.core.logging import get_logger, setup_logging
from apps.api.routes.health import router as health_router
from apps.api.routes.system import router as system_router
from apps.api.routes.data import router as data_router
from apps.api.routes.experiments import router as experiments_router
from apps.api.routes.datasets import router as datasets_router
from apps.api.routes.replay import router as replay_router
from apps.api.routes.paper_trading import router as paper_trading_router
from apps.api.routes.brokers import router as brokers_router
from apps.api.routes.research_ui import router as research_ui_router

# Initialize structured logging
setup_logging()
logger = get_logger("algo_lab.api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan management."""
    validate_api_key_at_startup()
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


@app.middleware("http")
async def add_process_time_and_request_id(request: Request, call_next):
    """Middleware attaching request_id and execution duration headers."""
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    start_time = time.perf_counter()

    response = await call_next(request)

    process_time = time.perf_counter() - start_time
    response.headers["X-Process-Time"] = f"{process_time:.6f}"
    response.headers["X-Request-ID"] = request_id
    return response


@app.middleware("http")
async def enforce_api_key_on_mutations(request: Request, call_next):
    """Enforces authentication on state-changing endpoints (POST, PUT, DELETE, PATCH)."""
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        env = os.environ.get("ENVIRONMENT", "development").lower()
        expected_key = os.environ.get("ALGO_LAB_API_KEY", "").strip()

        if expected_key:
            api_key = request.headers.get("X-API-Key", "")
            if not api_key:
                return JSONResponse(status_code=401, content={"detail": "X-API-Key header required"})
            provided_hash = hashlib.sha256(api_key.encode()).digest()
            expected_hash = hashlib.sha256(expected_key.encode()).digest()
            if not hmac.compare_digest(provided_hash, expected_hash):
                return JSONResponse(status_code=403, content={"detail": "Invalid API key"})
        elif env not in ("development", "dev", "test", "testing"):
            return JSONResponse(status_code=500, content={"detail": "ALGO_LAB_API_KEY not configured in production"})

    return await call_next(request)


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
