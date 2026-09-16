"""Unit tests for Broker Adapters and Secret Management (Stage 6)."""

from datetime import datetime, timezone, timedelta
import pytest

from data.schemas.canonical_market_data import CanonicalMarketDataBar
from services.market_data.adapters.base import MockMarketDataProvider
from services.paper_engine.adapters.credentials import (
    BrokerConnectionConfig,
    BrokerCredentialStore,
    ExecutionEnvironment,
    mask_secret,
    LIVE_TRADING_ENABLED,
)
from services.paper_engine.adapters.base import SimulatedBrokerAdapter
from services.backtest_engine.contracts import OrderSide
from services.backtest_engine.execution_lifecycle import ExecutionLifecycleManager, OrderLifecycleState


def test_mock_market_data_provider():
    """Verify MockMarketDataProvider seeded query and health checks."""
    provider = MockMarketDataProvider("test_feed")
    res = provider.test_connection()
    assert res["connected"] is True
    assert res["status"] == "CONNECTED"

    # Seed bars
    now = datetime.now(timezone.utc)
    bar = CanonicalMarketDataBar(
        timestamp=now,
        symbol="TCS",
        open=3500.0,
        high=3520.0,
        low=3490.0,
        close=3510.0,
        volume=1000.0,
    )
    provider.seed_bars("TCS", [bar])

    latest = provider.get_latest_bar("TCS")
    assert latest is not None
    assert latest.close == 3510.0

    bars = provider.get_bars("TCS", "1d", now - timedelta(hours=1), now + timedelta(hours=1))
    assert len(bars) == 1

    # Failure mode
    fail_provider = MockMarketDataProvider("failing_feed", should_fail=True)
    res_fail = fail_provider.test_connection()
    assert res_fail["connected"] is False
    with pytest.raises(ConnectionError):
        fail_provider.get_latest_bar("TCS")


def test_secret_masking_and_safe_dict():
    """Secrets must NEVER appear in plain text in repr, str, or to_safe_dict()."""
    raw_key = "ak_production_secret_key_998877"
    raw_secret = "sec_super_confidential_token_12345"

    config = BrokerConnectionConfig(
        broker_name="zerodha",
        environment=ExecutionEnvironment.PAPER,
        api_key=raw_key,
        api_secret=raw_secret,
        extra_params={"auth_token": "token_abc123xyz", "client_id": "AB1234"},
    )

    # 1. Repr and Str must mask secret
    repr_str = repr(config)
    assert raw_key not in repr_str
    assert raw_secret not in repr_str
    assert "ak****8877" in repr_str

    # 2. to_safe_dict must not include raw secret
    safe = config.to_safe_dict()
    assert "api_key" not in safe
    assert "api_secret" not in safe
    assert safe["api_key_masked"] == "ak****8877"
    assert safe["api_key_configured"] is True
    assert safe["api_secret_configured"] is True
    assert raw_secret not in str(safe)
    # Extra params token is masked
    assert "token_abc123xyz" not in str(safe)


def test_broker_credential_store():
    """Test saving, retrieving, listing, and testing broker credentials."""
    store = BrokerCredentialStore(":memory:")

    config = BrokerConnectionConfig(
        connection_id="conn_zerodha_01",
        broker_name="zerodha",
        environment=ExecutionEnvironment.PAPER,
        api_key="ak_live_sample_key_1234",
        api_secret="sec_sample_secret_5678",
    )
    store.save_connection(config)

    # Listed connections are masked
    listed = store.list_connections(masked=True)
    assert len(listed) == 1
    assert listed[0]["connection_id"] == "conn_zerodha_01"
    assert "api_key" not in listed[0]
    assert listed[0]["api_key_masked"] == "ak****1234"

    # Test connection
    test_res = store.test_connection("conn_zerodha_01")
    assert test_res["connected"] is True
    assert test_res["status"] == "HEALTHY"

    # Delete
    assert store.delete_connection("conn_zerodha_01") is True
    assert store.get_connection("conn_zerodha_01") is None


def test_live_trading_hard_disable():
    """Setting LIVE mode must fail closed with PermissionError."""
    assert LIVE_TRADING_ENABLED is False

    store = BrokerCredentialStore(":memory:")
    live_config = BrokerConnectionConfig(
        connection_id="conn_live_01",
        broker_name="upstox",
        environment=ExecutionEnvironment.LIVE,  # Forbidden
        api_key="ak_live",
    )

    with pytest.raises(PermissionError) as exc:
        store.save_connection(live_config)
    assert "LIVE trading execution is strictly prohibited" in str(exc.value)

    with pytest.raises(PermissionError) as exc2:
        SimulatedBrokerAdapter(connection_config=live_config)
    assert "LIVE mode" in str(exc2.value)


def test_simulated_broker_adapter_execution():
    """Verify paper order execution through SimulatedBrokerAdapter."""
    adapter = SimulatedBrokerAdapter()
    test_res = adapter.test_connection()
    assert test_res["connected"] is True
    assert test_res["environment"] == "PAPER"

    manager = ExecutionLifecycleManager()
    order = manager.propose_order(
        symbol="INFY",
        side=OrderSide.BUY,
        quantity=10,
        price=1500.0,
        stop_loss=1450.0,
    )
    # Risk check
    manager.evaluate_risk(order, current_portfolio_value=1_000_000.0)
    assert order.state == OrderLifecycleState.ORDER_ACCEPTED

    # Execute paper order
    filled_order, fill = adapter.submit_paper_order(order, execution_price=1500.0)
    assert filled_order.state == OrderLifecycleState.ORDER_FILLED
    assert fill.symbol == "INFY"
    assert fill.quantity == 10
    assert fill.fill_price > 1500.0  # Slippage added

    # Verify retrieval
    retrieved = adapter.get_order(filled_order.order_id)
    assert retrieved is not None
    assert retrieved.state == OrderLifecycleState.ORDER_FILLED
    assert len(adapter.list_orders()) == 1
    assert len(adapter.list_fills()) == 1
