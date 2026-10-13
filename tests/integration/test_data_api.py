"""Integration tests for Market Data & Quality API endpoints."""

from datetime import datetime, timezone
import pytest
from httpx import ASGITransport, AsyncClient
from apps.api.main import app


@pytest.fixture
async def async_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.mark.asyncio
async def test_api_session_status(async_client: AsyncClient):
    response = await async_client.get("/api/v1/data/session/status")
    assert response.status_code == 200
    data = response.json()
    assert "current_time_ist" in data
    assert "is_trading_day" in data
    assert "is_regular_trading_session" in data
    assert "session_reason" in data


@pytest.mark.asyncio
async def test_api_instruments_list(async_client: AsyncClient):
    response = await async_client.get("/api/v1/data/instruments")
    assert response.status_code == 200
    instruments = response.json()
    assert len(instruments) >= 5
    symbols = [i["symbol"] for i in instruments]
    assert "RELIANCE" in symbols
    assert "NIFTY 50" in symbols


@pytest.mark.asyncio
async def test_api_validate_bars_endpoint(async_client: AsyncClient):
    now = datetime(2024, 9, 2, 10, 0, tzinfo=timezone.utc)
    payload = {
        "bars": [
            {
                "symbol": "TCS",
                "exchange": "NSE",
                "timeframe": "5m",
                "market_timestamp": now.isoformat(),
                "open": 3800.0,
                "high": 3820.0,
                "low": 3795.0,
                "close": 3810.0,
                "volume": 2500.0,
            }
        ],
        "enforce_session_hours": False,
    }

    response = await async_client.post("/api/v1/data/validate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "TCS"
    assert data["total_bars"] == 1
    assert data["overall_status"] == "VALID"
    assert data["has_critical_failures"] is False


@pytest.mark.asyncio
async def test_a06_conflicting_dataset_registration_returns_conflict(async_client: AsyncClient, monkeypatch):
    from apps.api.core.config import settings

    researcher_key = "test_key_researcher_0123456789abcdef"
    monkeypatch.setattr(settings, "ALGO_LAB_API_KEY_RESEARCHER", researcher_key)
    monkeypatch.setattr(settings, "ALGO_LAB_API_KEY_ADMIN", "admin_key_0123456789abcdef0123456789")
    monkeypatch.setattr(settings, "ALLOW_LOCAL_AUTH_BYPASS", False)

    headers = {"X-API-Key": researcher_key}
    now = datetime(2025, 1, 1, tzinfo=timezone.utc)
    payload1 = {
        "dataset_id": "test_api_conflict_ds",
        "name": "API Conflict Test",
        "version": "v1.0.0",
        "exchange": "NSE",
        "asset_class": "EQUITY",
        "timeframe": "1d",
        "symbols": ["TCS"],
        "start_date": now.isoformat(),
        "end_date": datetime(2025, 1, 15, tzinfo=timezone.utc).isoformat(),
        "bar_count": 10,
        "sha256_checksum": "a" * 64,
        "metadata": {"source": "unit_test"},
    }

    # First registration must succeed with 201 Created
    res1 = await async_client.post("/api/v1/datasets/register", json=payload1, headers=headers)
    assert res1.status_code == 201
    data1 = res1.json()
    assert data1["dataset_id"] == "test_api_conflict_ds"
    assert data1["version"] == "v1.0.0"

    # Conflicting registration (different checksum for same version) must return 409 Conflict
    payload_conflict = dict(payload1)
    payload_conflict["sha256_checksum"] = "b" * 64
    res2 = await async_client.post("/api/v1/datasets/register", json=payload_conflict, headers=headers)
    assert res2.status_code == 409
    assert "already exists with differing" in res2.json()["detail"]
