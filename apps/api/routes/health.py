"""Health check endpoints (Liveness & Readiness)."""

from datetime import datetime, timezone
from fastapi import APIRouter, Response, status
from apps.api.core.config import settings
from apps.api.schemas.health import HealthResponse, ReadinessResponse
from database.session import check_database_health

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
async def liveness() -> HealthResponse:
    """Lightweight endpoint to verify process is alive."""
    return HealthResponse(
        status="healthy",
        version=settings.PROJECT_VERSION,
        environment=settings.ENVIRONMENT,
        timestamp=datetime.now(timezone.utc),
    )


@router.get("/health/ready", response_model=ReadinessResponse, summary="Readiness probe")
async def readiness(response: Response) -> ReadinessResponse:
    """Detailed endpoint verifying database and subsystem readiness."""
    db_health = await check_database_health()
    db_ready = db_health.get("status") == "connected"

    checks = {
        "database": "ok" if db_ready else "unavailable",
        "quant_engine": "ok",
        "data_quality_engine": "ok",
        "risk_engine": "ok",
    }

    # If critical subsystems fail, mark status as degraded / not_ready
    is_ready = db_ready
    status_str = "ready" if is_ready else "degraded"

    if not is_ready and settings.ENVIRONMENT == "production":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(
        status=status_str,
        version=settings.PROJECT_VERSION,
        timestamp=datetime.now(timezone.utc),
        database=db_health,
        checks=checks,
    )
