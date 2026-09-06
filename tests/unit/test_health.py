"""Unit tests for Health and System Endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient
from apps.api.main import app
from apps.api.core.config import settings


@pytest.fixture
async def async_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.mark.asyncio
async def test_root_endpoint(async_client: AsyncClient):
    response = await async_client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["version"] == settings.PROJECT_VERSION
    assert data["stage"] == "Stage 1: Foundation"
    assert data["safeguards"]["live_trading_allowed"] is False
    assert data["safeguards"]["real_broker_connected"] is False


@pytest.mark.asyncio
async def test_liveness_endpoint(async_client: AsyncClient):
    response = await async_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "timestamp" in data
    assert data["version"] == settings.PROJECT_VERSION


@pytest.mark.asyncio
async def test_readiness_endpoint(async_client: AsyncClient):
    response = await async_client.get("/health/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ["ready", "degraded"]
    assert "checks" in data
    assert "database" in data


@pytest.mark.asyncio
async def test_system_info_endpoint(async_client: AsyncClient):
    response = await async_client.get("/api/v1/system/info")
    assert response.status_code == 200
    data = response.json()
    assert data["core_principles_count"] == 25
    safety = data["safety_status"]
    assert safety["allow_live_trading"] is False
    assert safety["allow_real_broker_execution"] is False
    assert len(safety["active_guardrails"]) >= 4


@pytest.mark.asyncio
async def test_principles_endpoint(async_client: AsyncClient):
    response = await async_client.get("/api/v1/system/principles")
    assert response.status_code == 200
    principles = response.json()
    assert len(principles) == 25
    assert "1. Never force a trade." in principles[0]
    assert "2. WAIT is a valid decision." in principles[1]
    assert "25. No live capital deployment during the initial development stages." in principles[24]


def test_safety_validator_blocks_live_trading():
    with pytest.raises(ValueError, match="CRITICAL SAFETY VIOLATION"):
        from apps.api.core.config import Settings
        Settings(ALLOW_LIVE_TRADING=True)
