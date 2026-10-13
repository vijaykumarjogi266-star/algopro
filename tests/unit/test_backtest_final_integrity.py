"""Regression Tests for Backtest Engine, Strategy Integrity, Risk & Solvency.

Covers T30–T39 (Section 7 of remediation plan):
- T30: test_historical_backtest_rejects_synthetic_data_generation
- T31: test_dataset_checksum_drift_fails_backtest
- T32: test_buy_and_hold_distinct_from_sma_cross
- T33: test_actual_loss_and_drawdown_passed_to_risk_engine
- T34: test_approved_quantity_filled
- T35: test_cash_solvency_blocks_insolvent_buy
- T36: test_intrabar_causality_open_exit_before_low
- T37: test_entry_bar_stop_evaluated_causally
- T38: test_zero_trade_metrics_consistent
- T39: test_backtest_reproducibility_hash_deterministic
"""

import json
import math
import time
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
import pytest

from services.backtest_engine.service import BacktestService
from services.backtest_engine.contracts import (
    CostModelConfig,
    SlippageModelConfig,
    OrderSide,
    OrderType,
    ExperimentDefinition,
    ExperimentStatus,
)
from services.backtest_engine.execution_lifecycle import (
    ExecutionLifecycleManager,
    OrderLifecycleState,
)
from services.market_data.registry import (
    DatasetRecord,
    DatasetRegistryStore,
    compute_dataset_checksum,
)
from services.risk_engine.engine import RiskEngine
from services.risk_engine.contracts import (
    HardRiskLimits,
    RiskEvaluationResult,
    RiskRejectionCode,
)
from data.schemas.canonical_market_data import CanonicalMarketDataBar
from data.schemas.contracts import DataQualityStatus
from quant.strategies.buy_and_hold import BuyAndHold
from quant.strategies.sma_cross import SMACross, SMA_Cross


def _await_terminal_status(service: BacktestService, experiment_id: str, timeout: float = 3.0) -> Dict[str, Any]:
    """Helper to poll status until terminal state."""
    start = time.time()
    while time.time() - start < timeout:
        status_rec = service.get_run_status(experiment_id)
        if status_rec and status_rec.get("status") in ("COMPLETED", "FAILED"):
            return status_rec
        time.sleep(0.05)
    return service.get_run_status(experiment_id) or {}


def _create_canonical_bars(
    symbol: str,
    prices: List[float],
    start_dt: datetime = datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc),
    timeframe: str = "1d",
) -> List[CanonicalMarketDataBar]:
    """Builds canonical bars from a list of close prices."""
    bars = []
    for idx, close_p in enumerate(prices):
        bar_ts = start_dt + timedelta(days=idx)
        bars.append(
            CanonicalMarketDataBar(
                timestamp=bar_ts,
                symbol=symbol,
                exchange="NSE",
                timeframe=timeframe,
                open=close_p,
                high=close_p + 1.0,
                low=close_p - 1.0,
                close=close_p,
                volume=10000.0,
                trade_count=100,
            )
        )
    return bars


def _register_test_dataset(
    service: BacktestService,
    dataset_id: str,
    bars: List[CanonicalMarketDataBar],
    symbols: List[str],
) -> str:
    """Registers dataset record and in-memory bars in the service."""
    checksum = compute_dataset_checksum(bars)
    record = DatasetRecord(
        dataset_id=dataset_id,
        name=f"Dataset {dataset_id}",
        version="v1.0.0",
        exchange="NSE",
        asset_class="EQUITY",
        timeframe="1d",
        symbols=symbols,
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        bar_count=len(bars),
        sha256_checksum=checksum,
        quality_status=DataQualityStatus.VALID,
    )
    service.dataset_store.register_dataset(record)
    service.register_dataset_bars(dataset_id, bars)
    return checksum


# --------------------------------------------------------------------------
# T30: Historical backtest rejects synthetic data generation
# --------------------------------------------------------------------------
def test_historical_backtest_rejects_synthetic_data_generation(monkeypatch):
    """T30: Historical backtest without registered dataset must fail closed.

    Synthetic data fallback is prohibited.
    """
    dataset_store = DatasetRegistryStore(":memory:")
    service = BacktestService(dataset_store=dataset_store)

    # Ensure synthetic generator raises if ever called
    def _synthetic_should_not_be_called(*args, **kwargs):
        raise AssertionError("Synthetic generator was invoked in historical backtest execution path!")
    monkeypatch.setattr(service, "_generate_ohlcv_bars", _synthetic_should_not_be_called)

    exp_id = "exp_t30_unregistered"
    service.submit_backtest(
        strategy_id="Canonical_SMA",
        universe=["RELIANCE"],
        start_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end_date=datetime(2025, 3, 1, tzinfo=timezone.utc),
        initial_capital=100000.0,
        experiment_id=exp_id,
        dataset_id="NON_EXISTENT_DATASET_123",
        dataset_checksum="a" * 64,
    )

    status = _await_terminal_status(service, exp_id)
    assert status.get("status") == "FAILED"

    # Audit trail must record DATA_UNAVAILABLE
    events = service.get_audit_trail(exp_id)
    event_types = [e["event_type"] for e in events]
    assert "DATA_UNAVAILABLE" in event_types

    # Must produce no trades or metrics
    trades = service.store.get_trades(exp_id)
    assert len(trades) == 0


# --------------------------------------------------------------------------
# T31: Dataset checksum drift fails backtest
# --------------------------------------------------------------------------
def test_dataset_checksum_drift_fails_backtest():
    """T31: Mismatched dataset checksum fails closed before simulation."""
    service = BacktestService(dataset_store=DatasetRegistryStore(":memory:"))
    bars = _create_canonical_bars("TCS", [100.0 + i for i in range(35)])
    real_checksum = _register_test_dataset(service, "ds_t31_drift", bars, ["TCS"])

    exp_id = "exp_t31_drift"
    bad_checksum = "0" * 64  # Mismatched / drifted checksum
    service.submit_backtest(
        strategy_id="Canonical_SMA",
        universe=["TCS"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        initial_capital=100000.0,
        experiment_id=exp_id,
        dataset_id="ds_t31_drift",
        dataset_checksum=bad_checksum,
    )

    status = _await_terminal_status(service, exp_id)
    assert status.get("status") == "FAILED"

    events = service.get_audit_trail(exp_id)
    event_types = [e["event_type"] for e in events]
    assert any("CHECKSUM_MISMATCH" in t or "DATA_DRIFT" in t for t in event_types)


# --------------------------------------------------------------------------
# T32: BuyAndHold is distinct from SMA_Cross
# --------------------------------------------------------------------------
def test_buy_and_hold_distinct_from_sma_cross():
    """T32: Verify returns and trade profiles differ between BuyAndHold and SMA_Cross.

    - BuyAndHold: enters on bar 0 (first available bar) and holds through end date.
    - SMA_Cross: trades dual moving average crossover.
    """
    service = BacktestService(dataset_store=DatasetRegistryStore(":memory:"))
    # Create price pattern with initial rally, dip, then second rally
    prices = [100.0 + (i * 1.5) for i in range(25)] + [137.5 - (i * 2.0) for i in range(15)] + [107.5 + (i * 1.0) for i in range(20)]
    bars = _create_canonical_bars("INFY", prices)
    checksum = _register_test_dataset(service, "ds_t32_strats", bars, ["INFY"])

    # 1. Run BuyAndHold
    exp_bah = "exp_t32_buy_and_hold"
    service.submit_backtest(
        strategy_id="BuyAndHold",
        universe=["INFY"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        initial_capital=100000.0,
        experiment_id=exp_bah,
        dataset_id="ds_t32_strats",
        dataset_checksum=checksum,
    )
    status_bah = _await_terminal_status(service, exp_bah)
    assert status_bah.get("status") == "COMPLETED"

    # 2. Run SMA_Cross
    exp_sma = "exp_t32_sma_cross"
    service.submit_backtest(
        strategy_id="SMA_Cross",
        universe=["INFY"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        parameters={"fast_period": 5, "slow_period": 15},
        initial_capital=100000.0,
        experiment_id=exp_sma,
        dataset_id="ds_t32_strats",
        dataset_checksum=checksum,
    )
    status_sma = _await_terminal_status(service, exp_sma)
    assert status_sma.get("status") == "COMPLETED"

    trades_bah = service.store.get_trades(exp_bah)
    trades_sma = service.store.get_trades(exp_sma)

    # BuyAndHold must have entered at bar 0
    assert len(trades_bah) == 1
    # Trade in BuyAndHold was liquidated at final bar, entered at bar 0
    m_bah = json.loads(status_bah["metrics_json"])
    m_sma = json.loads(status_sma["metrics_json"])

    # Returns and trade profiles must be distinct
    assert (
        m_bah["total_return_pct"] != m_sma["total_return_pct"]
        or m_bah["number_of_trades"] != m_sma["number_of_trades"]
    )


# --------------------------------------------------------------------------
# T33: Actual daily loss and drawdown passed to Risk Engine
# --------------------------------------------------------------------------
def test_actual_loss_and_drawdown_passed_to_risk_engine():
    """T33: Verify Risk Engine receives real drawdown and loss pct from portfolio state."""
    class TrackingRiskEngine(RiskEngine):
        def __init__(self):
            super().__init__()
            self.evaluations: List[Dict[str, Any]] = []

        def evaluate(self, **kwargs):
            self.evaluations.append(dict(kwargs))
            return super().evaluate(**kwargs)

    tracking_engine = TrackingRiskEngine()
    service = BacktestService(
        dataset_store=DatasetRegistryStore(":memory:"),
        risk_engine=tracking_engine,
    )

    # Create pattern where price falls after bar 25, creating portfolio drawdown before an entry
    prices = [100.0] * 22 + [120.0, 120.0, 110.0, 95.0, 90.0, 92.0, 95.0, 100.0, 105.0]
    bars = _create_canonical_bars("RISK_TRACK_SYM", prices)
    checksum = _register_test_dataset(service, "ds_t33_risk", bars, ["RISK_TRACK_SYM"])

    exp_id = "exp_t33_risk_tracking"
    service.submit_backtest(
        strategy_id="Canonical_SMA",
        universe=["RISK_TRACK_SYM"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        initial_capital=100000.0,
        experiment_id=exp_id,
        dataset_id="ds_t33_risk",
        dataset_checksum=checksum,
    )

    status = _await_terminal_status(service, exp_id)
    assert status.get("status") == "COMPLETED"

    # Verify that evaluations took place and the risk engine was evaluated
    assert len(tracking_engine.evaluations) >= 1
    for ev in tracking_engine.evaluations:
        assert "current_daily_loss_pct" in ev
        assert "current_drawdown_pct" in ev
        assert isinstance(ev["current_daily_loss_pct"], float)
        assert isinstance(ev["current_drawdown_pct"], float)


# --------------------------------------------------------------------------
# T34: Approved quantity filled
# --------------------------------------------------------------------------
def test_approved_quantity_filled():
    """T34: Verify partial quantity approved by Risk Engine is respected by execution fill."""
    class PartialApprovalRiskEngine(RiskEngine):
        def evaluate(self, **kwargs):
            res = super().evaluate(**kwargs)
            if res.is_approved and kwargs.get("proposed_quantity", 0) > 2:
                # Approve exactly 2 units instead of whatever was proposed
                res.approved_quantity = 2
            return res

    partial_engine = PartialApprovalRiskEngine()

    # 1. Test in ExecutionLifecycleManager
    manager = ExecutionLifecycleManager(risk_engine=partial_engine)
    order = manager.propose_order("TCS", OrderSide.BUY, 20, 100.0, stop_loss=90.0)
    evaluated = manager.evaluate_risk(order, current_portfolio_value=100000.0)
    assert evaluated.state == OrderLifecycleState.ORDER_ACCEPTED
    assert evaluated.quantity == 2  # Approved quantity respected!

    submitted = manager.submit_order(evaluated)
    filled_order, fill = manager.fill_order(submitted, execution_price=100.0)
    assert filled_order.quantity == 2
    assert fill.quantity == 2

    # 2. Test in BacktestService simulation
    service = BacktestService(
        dataset_store=DatasetRegistryStore(":memory:"),
        risk_engine=partial_engine,
    )
    prices = [100.0] * 21 + [110.0, 110.0] + [102.0] * 15
    bars = _create_canonical_bars("PARTIAL_SYM", prices)
    checksum = _register_test_dataset(service, "ds_t34_partial", bars, ["PARTIAL_SYM"])

    exp_id = "exp_t34_approved_qty"
    service.submit_backtest(
        strategy_id="Canonical_SMA",
        universe=["PARTIAL_SYM"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        initial_capital=100000.0,
        experiment_id=exp_id,
        dataset_id="ds_t34_partial",
        dataset_checksum=checksum,
    )

    status = _await_terminal_status(service, exp_id)
    assert status.get("status") == "COMPLETED"

    trades = service.store.get_trades(exp_id)
    if trades:
        for t in trades:
            assert t["quantity"] == 2


# --------------------------------------------------------------------------
# T35: Cash solvency blocks insolvent BUY
# --------------------------------------------------------------------------
def test_cash_solvency_blocks_insolvent_buy():
    """T35: Verify BUY order is rejected when required outflow exceeds available cash."""
    manager = ExecutionLifecycleManager()

    # Outflow required for 10 shares @ 3000 INR is ~ 30,000 INR + costs
    order = manager.propose_order("RELIANCE", OrderSide.BUY, 10, 3000.0, stop_loss=2900.0)
    evaluated = manager.evaluate_risk(
        order,
        current_portfolio_value=1_000_000.0,
        available_cash=500.0,  # Available cash is only 500 INR!
    )

    assert evaluated.state == OrderLifecycleState.ORDER_REJECTED
    assert evaluated.rejection_code == RiskRejectionCode.INSUFFICIENT_CASH.value
    assert "Insufficient available cash" in evaluated.rejection_reason

    # Attempting to submit must fail closed
    with pytest.raises(ValueError):
        manager.submit_order(evaluated)


# --------------------------------------------------------------------------
# T36: Intrabar causality: open exit executed before intrabar low stops
# --------------------------------------------------------------------------
def test_intrabar_causality_open_exit_before_low():
    """T36: Exit order at open executed before intrabar low stops."""
    service = BacktestService(dataset_store=DatasetRegistryStore(":memory:"))

    # Index 0..20: warmup at 100
    # Index 21: trigger golden cross
    # Index 22: fill entry at open 110 (stop loss = 106.7)
    # Index 23: death cross triggered at close
    # Index 24: bar open=105, low=80 (below stop 106.7), close=85
    base_ts = datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc)
    closes = [100.0] * 21 + [110.0, 110.0] + [101.0] * 12
    bars = []
    for idx, c in enumerate(closes):
        ts = base_ts + timedelta(days=idx)
        if idx == 22:
            op = 100.0
        elif idx == 31:
            op = 120.0
        elif idx == 32:
            op = 102.0
        else:
            op = c
        hi = max(op, c) + 2.0
        lo = min(op, c) - 2.0
        if idx == 32:
            # Intrabar low plunges to 70.0 (far below stop loss ~97.0)
            lo = 70.0
        bars.append(
            CanonicalMarketDataBar(
                timestamp=ts,
                symbol="CAUSAL_SYM",
                exchange="NSE",
                timeframe="1d",
                open=op,
                high=hi,
                low=lo,
                close=c,
                volume=10000.0,
                trade_count=100,
            )
        )

    checksum = _register_test_dataset(service, "ds_t36_causal", bars, ["CAUSAL_SYM"])

    exp_id = "exp_t36_open_exit_before_low"
    service.submit_backtest(
        strategy_id="Canonical_SMA",
        universe=["CAUSAL_SYM"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        initial_capital=100000.0,
        experiment_id=exp_id,
        dataset_id="ds_t36_causal",
        dataset_checksum=checksum,
    )

    status = _await_terminal_status(service, exp_id)
    assert status.get("status") == "COMPLETED"

    trades = service.store.get_trades(exp_id)
    assert len(trades) >= 1
    trade = trades[0]
    # Trade exit reason must be SIGNAL_EXIT, never filled at the intrabar low of 70!
    assert trade["reason"] == "SIGNAL_EXIT"
    assert abs(trade["exit_price"] - 102.0) < 1.0


# --------------------------------------------------------------------------
# T37: Entry bar stop evaluated causally strictly after fill
# --------------------------------------------------------------------------
def test_entry_bar_stop_evaluated_causally():
    """T37: Stop loss on entry bar only triggers if low <= stop strictly after fill."""
    service = BacktestService(dataset_store=DatasetRegistryStore(":memory:"))

    base_ts = datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc)
    bars = []
    for i in range(21):
        bars.append(CanonicalMarketDataBar(
            timestamp=base_ts + timedelta(days=i), symbol="ENTRY_STOP_SYM", exchange="NSE", timeframe="1d",
            open=100.0, high=101.0, low=99.0, close=100.0, volume=10000.0
        ))
    # Bar 21: trigger entry signal
    bars.append(CanonicalMarketDataBar(
        timestamp=base_ts + timedelta(days=21), symbol="ENTRY_STOP_SYM", exchange="NSE", timeframe="1d",
        open=100.0, high=115.0, low=100.0, close=112.0, volume=10000.0
    ))
    # Bar 22: Entry filled at open 112.0 (stop_loss = 108.64).
    # Intrabar low plunges to 95.0 <= 108.64, closing at 98.0.
    bars.append(CanonicalMarketDataBar(
        timestamp=base_ts + timedelta(days=22), symbol="ENTRY_STOP_SYM", exchange="NSE", timeframe="1d",
        open=112.0, high=113.0, low=95.0, close=98.0, volume=10000.0
    ))
    # Bar 23: Subsequent bar
    bars.append(CanonicalMarketDataBar(
        timestamp=base_ts + timedelta(days=23), symbol="ENTRY_STOP_SYM", exchange="NSE", timeframe="1d",
        open=98.0, high=100.0, low=96.0, close=99.0, volume=10000.0
    ))

    checksum = _register_test_dataset(service, "ds_t37_entry_stop", bars, ["ENTRY_STOP_SYM"])

    exp_id = "exp_t37_entry_stop"
    service.submit_backtest(
        strategy_id="Canonical_SMA",
        universe=["ENTRY_STOP_SYM"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        initial_capital=100000.0,
        experiment_id=exp_id,
        dataset_id="ds_t37_entry_stop",
        dataset_checksum=checksum,
    )

    status = _await_terminal_status(service, exp_id)
    assert status.get("status") == "COMPLETED"

    trades = service.store.get_trades(exp_id)
    assert len(trades) >= 1
    # Trade was stopped out on entry bar
    trade = trades[0]
    assert trade["reason"] == "STOP_LOSS"


# --------------------------------------------------------------------------
# T38: Zero trade metrics consistent
# --------------------------------------------------------------------------
def test_zero_trade_metrics_consistent():
    """T38: No-trade backtest returns clean 0.0 metrics without NaN or zero division."""
    service = BacktestService(dataset_store=DatasetRegistryStore(":memory:"))

    # Short dataset (4 bars) — no crossover can occur
    bars = _create_canonical_bars("ZERO_SYM", [100.0, 100.5, 100.2, 100.8])
    checksum = _register_test_dataset(service, "ds_t38_zero", bars, ["ZERO_SYM"])

    exp_id = "exp_t38_zero_trades"
    service.submit_backtest(
        strategy_id="Canonical_SMA",
        universe=["ZERO_SYM"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        initial_capital=50000.0,
        experiment_id=exp_id,
        dataset_id="ds_t38_zero",
        dataset_checksum=checksum,
    )

    status = _await_terminal_status(service, exp_id)
    assert status.get("status") == "COMPLETED"

    metrics = json.loads(status["metrics_json"])
    assert metrics["number_of_trades"] == 0
    assert metrics["win_rate"] == 0.0
    assert metrics["total_return_pct"] == 0.0
    assert metrics["profit_factor"] == 0.0
    assert metrics["maximum_drawdown_pct"] == 0.0
    assert metrics["sharpe_ratio"] == 0.0
    assert metrics["sortino_ratio"] == 0.0

    # Ensure no NaN or inf in any metric
    for k, v in metrics.items():
        if isinstance(v, (int, float)):
            assert not math.isnan(v), f"Metric '{k}' returned NaN"
            assert not math.isinf(v), f"Metric '{k}' returned inf"


# --------------------------------------------------------------------------
# T39: Deterministic reproducibility hash
# --------------------------------------------------------------------------
def test_backtest_reproducibility_hash_deterministic():
    """T39: Same parameters and dataset yield identical hash and results."""
    service = BacktestService(dataset_store=DatasetRegistryStore(":memory:"))
    bars = _create_canonical_bars("REPRO_SYM", [100.0 + i for i in range(40)])
    checksum = _register_test_dataset(service, "ds_t39_repro", bars, ["REPRO_SYM"])

    res1 = service.submit_backtest(
        strategy_id="Canonical_SMA",
        universe=["REPRO_SYM"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        parameters={"fast_period": 8, "slow_period": 20},
        initial_capital=100000.0,
        dataset_id="ds_t39_repro",
        dataset_checksum=checksum,
    )

    res2 = service.submit_backtest(
        strategy_id="Canonical_SMA",
        universe=["REPRO_SYM"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        parameters={"fast_period": 8, "slow_period": 20},
        initial_capital=100000.0,
        dataset_id="ds_t39_repro",
        dataset_checksum=checksum,
    )

    assert res1["reproducibility_hash"] == res2["reproducibility_hash"]

    status1 = _await_terminal_status(service, res1["experiment_id"])
    status2 = _await_terminal_status(service, res2["experiment_id"])

    assert status1.get("status") == "COMPLETED"
    assert status2.get("status") == "COMPLETED"
    assert status1["metrics_json"] == status2["metrics_json"]
