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
