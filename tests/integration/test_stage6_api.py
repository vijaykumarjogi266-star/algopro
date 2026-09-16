"""Integration tests for Stage 6 REST APIs (Datasets, Replay, Paper Trading, Brokers)."""

from datetime import datetime, timezone, timedelta
import pytest
from httpx import ASGITransport, AsyncClient
from apps.api.main import app
from services.market_data.registry import compute_dataset_checksum
from data.schemas.canonical_market_data import CanonicalMarketDataBar


@pytest.fixture
async def async_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


def _sample_bars(symbol: str = "TCS", count: int = 3):
    base_ts = datetime(2025, 2, 3, 9, 15, tzinfo=timezone.utc)
    bars = []
    for i in range(count):
        b = CanonicalMarketDataBar(
            timestamp=base_ts + timedelta(days=i),
            symbol=symbol,
            exchange="NSE",
            timeframe="1d",
            open=3500.0 + i * 10,
            high=3550.0 + i * 10,
            low=3480.0 + i * 10,
            close=3520.0 + i * 10,
            volume=5000.0,
            trade_count=300,
        )
        bars.append(b)
    return bars


@pytest.mark.asyncio
async def test_dataset_registry_api(async_client: AsyncClient):
    """Test /api/v1/datasets CRUD, verification and drift detection."""
    bars = _sample_bars("TCS", 3)
    checksum = compute_dataset_checksum(bars)

    # 1. Register
    payload = {
        "dataset_id": "ds_tcs_stage6",
        "name": "TCS Stage 6 Daily",
        "version": "v1.0.0",
        "exchange": "NSE",
        "asset_class": "EQUITY",
        "timeframe": "1d",
        "symbols": ["TCS"],
        "start_date": bars[0].timestamp.isoformat(),
        "end_date": bars[-1].timestamp.isoformat(),
        "bar_count": len(bars),
        "sha256_checksum": checksum,
    }
    resp = await async_client.post("/api/v1/datasets/register", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["dataset_id"] == "ds_tcs_stage6"

    # 2. List
    list_resp = await async_client.get("/api/v1/datasets")
    assert list_resp.status_code == 200
    assert any(d["dataset_id"] == "ds_tcs_stage6" for d in list_resp.json())

    # 3. Get
    get_resp = await async_client.get("/api/v1/datasets/ds_tcs_stage6")
    assert get_resp.status_code == 200
    assert get_resp.json()["sha256_checksum"] == checksum

    # 4. Verify (Match)
    bar_dicts = [b.model_dump(mode="json") for b in bars]
    verify_resp = await async_client.post(
        "/api/v1/datasets/ds_tcs_stage6/verify",
        json={"bars": bar_dicts},
    )
    assert verify_resp.status_code == 200
    assert verify_resp.json()["status"] == "VERIFIED"

    # 5. Verify Drift (Modified price fails closed with 409)
    corrupt_bars = [b.model_copy() for b in bars]
    corrupt_bars[1].close += 5.0
    corrupt_dicts = [b.model_dump(mode="json") for b in corrupt_bars]
    drift_resp = await async_client.post(
        "/api/v1/datasets/ds_tcs_stage6/verify",
        json={"bars": corrupt_dicts},
    )
    assert drift_resp.status_code == 409


@pytest.mark.asyncio
async def test_replay_api(async_client: AsyncClient):
    """Test /api/v1/replay/run and /api/v1/replay/status endpoints."""
    bars = _sample_bars("INFY", 3)
    bar_dicts = [b.model_dump(mode="json") for b in bars]

    run_resp = await async_client.post(
        "/api/v1/replay/run",
        json={
            "bars": bar_dicts,
            "symbols": ["INFY"],
            "filter_holidays": False,
        },
    )
    assert run_resp.status_code == 200
    data = run_resp.json()
    assert data["status"] == "COMPLETED"
    assert data["events_processed"] == 3
    replay_id = data["replay_id"]

    # Check status
    status_resp = await async_client.get(f"/api/v1/replay/status/{replay_id}")
    assert status_resp.status_code == 200
    assert status_resp.json()["events_processed"] == 3


@pytest.mark.asyncio
async def test_paper_trading_api(async_client: AsyncClient):
    """Test /api/v1/paper-trading session lifecycle and risk-gated order execution."""
    # 1. Reject LIVE session
    live_resp = await async_client.post(
        "/api/v1/paper-trading/sessions",
        json={
            "name": "Live Test",
            "strategy_id": "strat_1",
            "universe": ["SBIN"],
            "environment": "LIVE",
        },
    )
    assert live_resp.status_code == 403

    # 2. Create Paper session
    create_resp = await async_client.post(
        "/api/v1/paper-trading/sessions",
        json={
            "name": "Stage 6 Session",
            "strategy_id": "strat_stage6",
            "universe": ["SBIN"],
            "initial_capital": 1_000_000.0,
            "environment": "PAPER",
        },
    )
    assert create_resp.status_code == 201
    sess = create_resp.json()
    session_id = sess["session_id"]
    assert sess["status"] == "CREATED"

    # 3. Start session
    start_resp = await async_client.post(f"/api/v1/paper-trading/sessions/{session_id}/start")
    assert start_resp.status_code == 200
    assert start_resp.json()["status"] == "RUNNING"

    # 4. Submit valid paper order (50 shares of SBIN at 750 INR = 37,500 INR <= 50,000 INR limit)
    order_resp = await async_client.post(
        f"/api/v1/paper-trading/sessions/{session_id}/orders",
        json={
            "symbol": "SBIN",
            "side": "BUY",
            "quantity": 50,
            "price": 750.0,
            "stop_loss": 740.0,
        },
    )
    assert order_resp.status_code == 200
    order_data = order_resp.json()
    assert order_data["status"] == "ORDER_FILLED"
    assert order_data["fill"] is not None

    # 5. Verify portfolio updated
    get_resp = await async_client.get(f"/api/v1/paper-trading/sessions/{session_id}")
    assert get_resp.status_code == 200
    portfolio = get_resp.json()["portfolio"]
    assert "SBIN" in portfolio["positions"]
    assert portfolio["positions"]["SBIN"]["quantity"] == 50


@pytest.mark.asyncio
async def test_broker_connections_api(async_client: AsyncClient):
    """Test /api/v1/brokers connection management and secret masking."""
    # 1. Reject LIVE environment
    live_resp = await async_client.post(
        "/api/v1/brokers/connections",
        json={
            "broker_name": "zerodha",
            "environment": "LIVE",
            "api_key": "raw_secret_key",
        },
    )
    assert live_resp.status_code == 403

    # 2. Save Paper connection
    raw_key = "ak_prod_secret_123456"
    save_resp = await async_client.post(
        "/api/v1/brokers/connections",
        json={
            "broker_name": "simulated",
            "environment": "PAPER",
            "api_key": raw_key,
            "api_secret": "my_confidential_secret",
        },
    )
    assert save_resp.status_code == 201
    saved = save_resp.json()
    conn_id = saved["connection_id"]

    # Verify secret is strictly masked in response
    assert raw_key not in str(saved)
    assert saved["api_key_masked"] == "ak****3456"
    assert saved["api_key_configured"] is True
    assert saved["api_secret_configured"] is True

    # 3. List connections (masked)
    list_resp = await async_client.get("/api/v1/brokers/connections")
    assert list_resp.status_code == 200
    items = list_resp.json()
    match = next(i for i in items if i["connection_id"] == conn_id)
    assert match["api_key_masked"] == "ak****3456"
    assert "api_secret" not in match

    # 4. Test connection
    test_resp = await async_client.post(f"/api/v1/brokers/connections/{conn_id}/test")
    assert test_resp.status_code == 200
    assert test_resp.json()["connected"] is True

    # 5. Delete connection
    del_resp = await async_client.delete(f"/api/v1/brokers/connections/{conn_id}")
    assert del_resp.status_code == 200
