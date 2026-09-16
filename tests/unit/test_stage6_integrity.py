"""Algo Lab Stage 6: Integrity, Concurrency, and 15 Architectural Invariants Test Suite.

Verifies the 15 Stage 6 Non-Negotiable Invariants:
1. Zero Live Trading Invariant
2. Zero Look-Ahead Bias Invariant
3. Deterministic Historical Replay Invariant
4. Cryptographic Dataset Integrity Invariant
5. Canonical OHLCV Mathematical Invariant
6. Secret Masking & Protection Invariant
7. Independent Risk Gate Invariant
8. Zero Portfolio Mutation on Rejection Invariant
9. Strict Financial Accounting Invariant
10. Multi-Symbol Portfolio Isolation Invariant
11. Concurrent Replay Safety Invariant (5+ threads)
12. Concurrent Paper Session Safety Invariant (5+ threads)
13. Fail-Closed Data Quarantine Invariant
14. Indian Market Calendar Trading Session Invariant
15. Realistic Transaction Friction & Slippage Invariant
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
import pytest
from pydantic import ValidationError

from data.schemas.canonical_market_data import CanonicalMarketDataBar
from services.market_data.calendar import IndianMarketCalendar
from services.market_data.registry import (
    DatasetRecord,
    DatasetRegistryStore,
    compute_dataset_checksum,
    DatasetDriftError,
    DatasetIntegrityError,
)
from services.backtest_engine.replay import (
    HistoricalReplayEngine,
    ReplayConfig,
    LookAheadBiasError,
)
from services.backtest_engine.contracts import OrderSide, OrderType, CostModelConfig, SlippageModelConfig
from services.backtest_engine.cost_models import IndianCostCalculator, SlippageCalculator
from services.backtest_engine.execution_lifecycle import (
    ExecutionLifecycleManager,
    ExecutionOrder,
    ExecutionFill,
    OrderLifecycleState,
)
from services.paper_engine.adapters.credentials import (
    BrokerConnectionConfig,
    BrokerCredentialStore,
    ExecutionEnvironment,
    LIVE_TRADING_ENABLED,
    REAL_BROKER_EXECUTION_ENABLED,
)
from services.paper_engine.adapters.base import SimulatedBrokerAdapter
from services.paper_engine.session import (
    PaperTradingEngine,
    SessionStatus,
    PaperPortfolio,
)


def _make_bar(symbol: str, dt: datetime, price: float = 100.0) -> CanonicalMarketDataBar:
    return CanonicalMarketDataBar(
        timestamp=dt,
        symbol=symbol,
        exchange="NSE",
        timeframe="1d",
        open=price,
        high=price + 5.0,
        low=price - 5.0,
        close=price + 2.0,
        volume=10000.0,
        trade_count=500,
    )


def test_invariant_1_zero_live_trading():
    """Invariant 1: LIVE real money trading is hard-disabled across all modules."""
    assert LIVE_TRADING_ENABLED is False
    assert REAL_BROKER_EXECUTION_ENABLED is False

    # Credential store rejection
    cred_store = BrokerCredentialStore(":memory:")
    with pytest.raises(PermissionError):
        cred_store.save_connection(
            BrokerConnectionConfig(
                broker_name="upstox",
                environment=ExecutionEnvironment.LIVE,
            )
        )

    # Paper engine rejection
    paper_engine = PaperTradingEngine(":memory:")
    with pytest.raises(PermissionError):
        paper_engine.create_session(
            name="Live Attempt",
            strategy_id="strat_1",
            universe=["RELIANCE"],
            environment=ExecutionEnvironment.LIVE,
        )


def test_invariant_2_zero_look_ahead():
    """Invariant 2: No future timestamp data leakage during replay."""
    t0 = datetime(2025, 2, 3, 9, 15, tzinfo=timezone.utc)
    b1 = _make_bar("TCS", t0)
    b2 = _make_bar("TCS", t0 + timedelta(days=1))

    engine = HistoricalReplayEngine([b1, b2])
    engine.step()  # At t0

    # History only has t0
    history = engine.get_history("TCS")
    assert len(history) == 1
    assert history[0].timestamp == t0

    # Looking ahead into tomorrow raises LookAheadBiasError
    with pytest.raises(LookAheadBiasError):
        engine.peek_future(t0 + timedelta(days=1))


def test_invariant_3_deterministic_replay():
    """Invariant 3: Identical inputs yield identical chronological replay sequences."""
    base = datetime(2025, 2, 3, 9, 15, tzinfo=timezone.utc)
    bars = [_make_bar("INFY", base + timedelta(days=i), 1500.0 + i) for i in range(5)]

    engine1 = HistoricalReplayEngine(bars)
    engine2 = HistoricalReplayEngine(list(reversed(bars)))

    events1 = []
    engine1.run(on_event=lambda ev, eng: events1.append(ev.timestamp))
    events2 = []
    engine2.run(on_event=lambda ev, eng: events2.append(ev.timestamp))

    assert events1 == events2


def test_invariant_4_cryptographic_dataset():
    """Invariant 4: SHA-256 checksums detect any data drift and fail closed."""
    store = DatasetRegistryStore(":memory:")
    bars = [_make_bar("SBIN", datetime(2025, 2, 3, 9, 15, tzinfo=timezone.utc) + timedelta(days=i)) for i in range(3)]
    c = compute_dataset_checksum(bars)

    record = DatasetRecord(
        dataset_id="ds_sbin_inv",
        name="SBIN Daily",
        symbols=["SBIN"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        bar_count=3,
        sha256_checksum=c,
    )
    store.register_dataset(record)

    # Valid verify
    assert store.verify_dataset_integrity("ds_sbin_inv", bars) is True

    # Tampered bar
    tampered = [b.model_copy() for b in bars]
    tampered[0].close += 0.01
    with pytest.raises(DatasetDriftError):
        store.verify_dataset_integrity("ds_sbin_inv", tampered)


def test_invariant_5_canonical_ohlcv_math():
    """Invariant 5: OHLC relationships enforced; NaN/Inf strictly prohibited."""
    ts = datetime(2025, 2, 3, 9, 15, tzinfo=timezone.utc)

    # High < Close
    with pytest.raises(ValidationError):
        CanonicalMarketDataBar(
            timestamp=ts,
            symbol="HDFC",
            open=100.0,
            high=95.0,
            low=90.0,
            close=105.0,
            volume=100.0,
        )

    # NaN price
    with pytest.raises(ValidationError):
        CanonicalMarketDataBar(
            timestamp=ts,
            symbol="HDFC",
            open=float("nan"),
            high=105.0,
            low=95.0,
            close=100.0,
            volume=100.0,
        )


def test_invariant_6_secret_masking():
    """Invariant 6: Credentials are never exposed in plain text in repr, str, or serialized dicts."""
    raw_key = "ak_top_secret_prod_key_12345"
    raw_secret = "sec_confidential_token_67890"

    cfg = BrokerConnectionConfig(
        broker_name="zerodha",
        api_key=raw_key,
        api_secret=raw_secret,
    )
    assert raw_key not in repr(cfg)
    assert raw_secret not in repr(cfg)

    safe = cfg.to_safe_dict()
    assert "api_key" not in safe
    assert "api_secret" not in safe
    assert raw_key not in str(safe)
    assert raw_secret not in str(safe)
    assert safe["api_key_configured"] is True
    assert safe["api_secret_configured"] is True


def test_invariant_7_independent_risk_gate():
    """Invariant 7: Orders must be evaluated by independent RiskEngine before execution."""
    mgr = ExecutionLifecycleManager()
    order = mgr.propose_order("TCS", OrderSide.BUY, 10, 3500.0, stop_loss=3400.0)
    assert order.state == OrderLifecycleState.ORDER_PROPOSED

    # Cannot submit unapproved order
    with pytest.raises(ValueError):
        mgr.submit_order(order)

    # Evaluate risk
    mgr.evaluate_risk(order, current_portfolio_value=1_000_000.0)
    assert order.state == OrderLifecycleState.ORDER_ACCEPTED

    # Now can submit
    mgr.submit_order(order)
    assert order.state == OrderLifecycleState.ORDER_SUBMITTED


def test_invariant_8_zero_portfolio_mutation_on_rejection():
    """Invariant 8: Risk rejections cause ZERO portfolio mutation."""
    engine = PaperTradingEngine(":memory:")
    session = engine.create_session("Zero Mutation", "strat_1", ["INFY"], 1_000_000.0)
    engine.start_session(session.session_id)

    initial_cash = session.portfolio.cash
    initial_equity = session.portfolio.total_equity

    # Order that violates 5% max capital limit (400 shares at 1500 = 600,000 INR > 50,000 INR limit)
    order, fill = engine.submit_manual_order(session.session_id, "INFY", OrderSide.BUY, 400, 1500.0, stop_loss=1400.0)
    assert order.state == OrderLifecycleState.ORDER_REJECTED
    assert fill is None

    s = engine.get_session(session.session_id)
    assert s.portfolio.cash == initial_cash
    assert s.portfolio.total_equity == initial_equity
    assert len(s.portfolio.positions) == 0


def test_invariant_9_financial_accounting():
    """Invariant 9: Total Equity == Cash + Open Positions Market Value."""
    portfolio = PaperPortfolio.initialize(1_000_000.0)
    # Buy fill
    cost_calc = IndianCostCalculator()
    costs = cost_calc.calculate_transaction_costs(OrderSide.BUY, 20, 1500.0)
    fill = ExecutionFill(
        order_id="o1",
        symbol="INFY",
        side=OrderSide.BUY,
        quantity=20,
        base_price=1500.0,
        fill_price=1500.50,
        slippage_pts=0.50,
        slippage_cost=10.0,
        transaction_costs=costs,
        net_traded_value=20 * 1500.50,
    )
    portfolio.on_fill(fill)

    # Cash + Market value == Total equity
    expected = portfolio.cash + portfolio.positions["INFY"].market_value
    assert portfolio.total_equity == pytest.approx(expected, abs=1e-3)


def test_invariant_10_multi_symbol_portfolio_isolation():
    """Invariant 10: Multi-symbol portfolio maintains isolated position state."""
    portfolio = PaperPortfolio.initialize(2_000_000.0)

    f1 = ExecutionFill(
        order_id="o1", symbol="TCS", side=OrderSide.BUY, quantity=10,
        base_price=3500.0, fill_price=3500.0, slippage_pts=0, slippage_cost=0,
        transaction_costs=20.0, net_traded_value=35000.0
    )
    f2 = ExecutionFill(
        order_id="o2", symbol="INFY", side=OrderSide.BUY, quantity=20,
        base_price=1500.0, fill_price=1500.0, slippage_pts=0, slippage_cost=0,
        transaction_costs=15.0, net_traded_value=30000.0
    )
    portfolio.on_fill(f1)
    portfolio.on_fill(f2)

    assert len(portfolio.positions) == 2
    # Mark TCS up, INFY down
    portfolio.mark_to_market({"TCS": 3600.0, "INFY": 1450.0})
    assert portfolio.positions["TCS"].unrealized_pnl == 1000.0
    assert portfolio.positions["INFY"].unrealized_pnl == -1000.0
    assert portfolio.total_unrealized_pnl == 0.0


def test_invariant_11_concurrency_replays():
    """Invariant 11: 5+ concurrent replays execute without race condition or interference."""
    base = datetime(2025, 2, 3, 9, 15, tzinfo=timezone.utc)
    bars = [_make_bar("TCS", base + timedelta(days=i), 3500.0 + i) for i in range(10)]

    def run_sim(idx: int):
        eng = HistoricalReplayEngine(
            bars,
            config=ReplayConfig(symbols=["TCS"], filter_holidays=False),
        )
        return eng.run()

    with ThreadPoolExecutor(max_workers=5) as ex:
        results = list(ex.map(run_sim, range(6)))

    assert len(results) == 6
    assert all(r == 10 for r in results)


def test_invariant_12_concurrency_paper_sessions():
    """Invariant 12: 5+ concurrent paper sessions update without SQLite locking errors."""
    engine = PaperTradingEngine(":memory:")
    sessions = [
        engine.create_session(f"Sess_{i}", f"strat_{i}", ["SBIN"], 1_000_000.0)
        for i in range(6)
    ]
    for s in sessions:
        engine.start_session(s.session_id)

    def submit_order_for_session(sess):
        order, fill = engine.submit_manual_order(
            sess.session_id, "SBIN", OrderSide.BUY, 20, 750.0, stop_loss=740.0
        )
        return fill is not None

    with ThreadPoolExecutor(max_workers=6) as ex:
        successes = list(ex.map(submit_order_for_session, sessions))

    assert all(successes)
    # Verify all sessions have 1 position
    for s in sessions:
        recovered = engine.get_session(s.session_id)
        assert len(recovered.portfolio.positions) == 1


def test_invariant_13_data_quarantine():
    """Invariant 13: Quarantined datasets fail closed on verification."""
    store = DatasetRegistryStore(":memory:")
    bars = [_make_bar("WIPRO", datetime(2025, 2, 3, 9, 15, tzinfo=timezone.utc))]
    record = DatasetRecord(
        dataset_id="ds_wipro_quarantine",
        name="Wipro Daily",
        symbols=["WIPRO"],
        start_date=bars[0].timestamp,
        end_date=bars[0].timestamp,
        bar_count=1,
        sha256_checksum=compute_dataset_checksum(bars),
    )
    store.register_dataset(record)
    store.quarantine_dataset("ds_wipro_quarantine", "Suspect tick clustering")

    with pytest.raises(DatasetIntegrityError):
        store.verify_dataset_integrity("ds_wipro_quarantine", bars)


def test_invariant_14_nse_calendar_filtering():
    """Invariant 14: Official exchange holidays are filtered out."""
    cal = IndianMarketCalendar()
    # 2025-01-26 is Republic Day
    republic_day = datetime(2025, 1, 26, 9, 15, tzinfo=timezone.utc)
    assert cal.is_trading_day(republic_day) is False

    # 2025-08-15 is Independence Day
    independence_day = datetime(2025, 8, 15, 9, 15, tzinfo=timezone.utc)
    assert cal.is_trading_day(independence_day) is False


def test_invariant_15_realistic_friction_and_costs():
    """Invariant 15: Transaction costs and slippage reflect realistic Indian market frictions."""
    cost_calc = IndianCostCalculator()
    slip_calc = SlippageCalculator(SlippageModelConfig(fixed_tick_slippage_pts=0.05, variable_slippage_pct=0.0005))

    # Buy order: slippage pushes price up
    fill_price, slip_pts = slip_calc.calculate_fill_price(OrderSide.BUY, 2500.0)
    assert fill_price > 2500.0
    assert slip_pts > 0

    # Costs include brokerage, turnover charges, GST, stamp duty
    costs = cost_calc.calculate_transaction_costs(OrderSide.BUY, 50, fill_price)
    assert costs > 20.0  # Brokerage + statutory charges
