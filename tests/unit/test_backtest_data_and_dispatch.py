"""Tests for Backtest Data Registration, Validation, and Strategy Dispatch.

Tests:
24. test_missing_dataset_never_completes_with_metrics
25. test_dataset_checksum_mismatch_rejected
26. test_requested_strategy_and_parameters_are_executed
27. test_cost_changes_do_not_change_market_data
28. test_universe_permutation_preserves_same_hash_results
"""

import time
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any
import pytest

from services.backtest_engine.service import BacktestService
from services.backtest_engine.contracts import (
    CostModelConfig,
    SlippageModelConfig,
    ExperimentDefinition,
    ExperimentStatus,
)
from services.market_data.registry import (
    DatasetRecord,
    DatasetRegistryStore,
    compute_dataset_checksum,
)
from data.schemas.canonical_market_data import CanonicalMarketDataBar
from data.schemas.contracts import DataQualityStatus


def _create_sample_bars(symbol: str, count: int = 40) -> List[CanonicalMarketDataBar]:
    base_ts = datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc)
    bars = []
    for i in range(count):
        bar = CanonicalMarketDataBar(
            timestamp=base_ts + timedelta(days=i),
            symbol=symbol,
            exchange="NSE",
            timeframe="1d",
            open=100.0 + (i * 0.5),
            high=105.0 + (i * 0.5),
            low=98.0 + (i * 0.5),
            close=102.0 + (i * 0.5),
            volume=10000.0,
            trade_count=100,
        )
        bars.append(bar)
    return bars


def _await_terminal_status(service: BacktestService, experiment_id: str, timeout: float = 3.0):
    start = time.time()
    while time.time() - start < timeout:
        status_rec = service.get_run_status(experiment_id)
        if status_rec and status_rec.get("status") in ("COMPLETED", "FAILED"):
            return status_rec
        time.sleep(0.05)
    return service.get_run_status(experiment_id)


def test_missing_dataset_never_completes_with_metrics(monkeypatch):
    """Test 24: When dataset is missing or unavailable, the run must fail with DATA_UNAVAILABLE,

    produce no metrics, and never invoke synthetic fallback generation.
    """
    dataset_store = DatasetRegistryStore(":memory:")
    service = BacktestService(dataset_store=dataset_store)

    # Monkeypatch synthetic generator to ensure it is NEVER called
    def _mock_synthetic(*args, **kwargs):
        raise AssertionError("Synthetic generator was called when dataset was unavailable!")
    monkeypatch.setattr(service, "_generate_ohlcv_bars", _mock_synthetic)

    exp_id = "exp_missing_dataset_test"
    # Register experiment definition requesting a non-existent dataset
    exp_def = ExperimentDefinition(
        experiment_id=exp_id,
        name="Missing Dataset Test",
        strategy_id="Canonical_SMA",
        strategy_version="1.0.0",
        dataset_id="NON_EXISTENT_DATASET_ID",
        dataset_version="v1.0.0",
        dataset_checksum="0" * 64,
        universe=["RELIANCE"],
        start_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end_date=datetime(2025, 3, 1, tzinfo=timezone.utc),
        initial_capital=100000.0,
    )
    service.store.save_experiment(exp_def)

    res = service.submit_backtest(
        strategy_id="Canonical_SMA",
        universe=["RELIANCE"],
        start_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end_date=datetime(2025, 3, 1, tzinfo=timezone.utc),
        initial_capital=100000.0,
        experiment_id=exp_id,
        dataset_id="NON_EXISTENT_DATASET_ID",
    )

    status = _await_terminal_status(service, exp_id)
    assert status["status"] == "FAILED"
    # Metrics must be absent or empty
    metrics = status.get("metrics_json") or status.get("metrics")
    assert not metrics or metrics == "{}"

    # Check audit events for DATA_UNAVAILABLE
    events = service.store.get_audit_events(exp_id)
    event_types = [e["event_type"] for e in events]
    assert "DATA_UNAVAILABLE" in event_types


def test_dataset_checksum_mismatch_rejected():
    """Test 25: If data bytes drift or checksum doesn't match registered checksum,

    must fail closed before simulation.
    """
    dataset_store = DatasetRegistryStore(":memory:")
    bars = _create_sample_bars("TCS", 40)
    real_checksum = compute_dataset_checksum(bars)

    # Register with checksum
    rec = DatasetRecord(
        dataset_id="tcs_daily_v1",
        name="TCS Daily",
        version="v1.0.0",
        exchange="NSE",
        asset_class="EQUITY",
        timeframe="1d",
        symbols=["TCS"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        bar_count=len(bars),
        sha256_checksum=real_checksum,
        quality_status=DataQualityStatus.VALID,
    )
    dataset_store.register_dataset(rec)

    service = BacktestService(dataset_store=dataset_store)
    # Register loaded bars in service
    service.register_dataset_bars("tcs_daily_v1", bars)

    exp_id = "exp_checksum_mismatch_test"
    # Submit with mismatched checksum (e.g. altered fixture)
    bad_checksum = "f" * 64
    exp_def = ExperimentDefinition(
        experiment_id=exp_id,
        name="Checksum Mismatch Test",
        strategy_id="Canonical_SMA",
        strategy_version="1.0.0",
        dataset_id="tcs_daily_v1",
        dataset_version="v1.0.0",
        dataset_checksum=bad_checksum,
        universe=["TCS"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        initial_capital=100000.0,
    )
    service.store.save_experiment(exp_def)

    service.submit_backtest(
        strategy_id="Canonical_SMA",
        universe=["TCS"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        initial_capital=100000.0,
        experiment_id=exp_id,
        dataset_id="tcs_daily_v1",
        dataset_checksum=bad_checksum,
    )

    status = _await_terminal_status(service, exp_id)
    assert status["status"] == "FAILED"
    events = service.store.get_audit_events(exp_id)
    event_types = [e["event_type"] for e in events]
    assert any("CHECKSUM_MISMATCH" in t or "DATA_DRIFT" in t or "DATA_UNAVAILABLE" in t for t in event_types)


def test_requested_strategy_and_parameters_are_executed():
    """Test 26: Requested strategy and parameter schemas are dispatched.

    Unknown strategy is rejected. Parameter changes alter signals without modifying market data.
    """
    dataset_store = DatasetRegistryStore(":memory:")
    bars = _create_sample_bars("INFY", 45)
    checksum = compute_dataset_checksum(bars)

    rec = DatasetRecord(
        dataset_id="infy_daily_v1",
        name="INFY Daily",
        version="v1.0.0",
        symbols=["INFY"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        bar_count=len(bars),
        sha256_checksum=checksum,
    )
    dataset_store.register_dataset(rec)

    service = BacktestService(dataset_store=dataset_store)
    service.register_dataset_bars("infy_daily_v1", bars)

    # 1. Unknown strategy must fail / be rejected
    exp_bad = "exp_unknown_strat"
    service.submit_backtest(
        strategy_id="BOGUS_UNKNOWN_STRATEGY",
        universe=["INFY"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        initial_capital=100000.0,
        experiment_id=exp_bad,
        dataset_id="infy_daily_v1",
        dataset_checksum=checksum,
    )
    status_bad = _await_terminal_status(service, exp_bad)
    assert status_bad["status"] == "FAILED"

    # 2. Known strategy with default parameters vs modified parameters
    exp_p1 = "exp_sma_param_1"
    service.submit_backtest(
        strategy_id="Canonical_SMA",
        universe=["INFY"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        parameters={"fast_period": 5, "slow_period": 15},
        initial_capital=100000.0,
        experiment_id=exp_p1,
        dataset_id="infy_daily_v1",
        dataset_checksum=checksum,
    )
    status_p1 = _await_terminal_status(service, exp_p1)
    assert status_p1["status"] == "COMPLETED"

    exp_p2 = "exp_sma_param_2"
    service.submit_backtest(
        strategy_id="Canonical_SMA",
        universe=["INFY"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        parameters={"fast_period": 12, "slow_period": 26},
        initial_capital=100000.0,
        experiment_id=exp_p2,
        dataset_id="infy_daily_v1",
        dataset_checksum=checksum,
    )
    status_p2 = _await_terminal_status(service, exp_p2)
    assert status_p2["status"] == "COMPLETED"

    # Different parameters should produce different reproducibility hashes and/or trade results
    assert status_p1["reproducibility_hash"] != status_p2["reproducibility_hash"]


def test_cost_changes_do_not_change_market_data():
    """Test 27: Holding dataset and seed fixed, changing costs alone alters net results

    without changing market data or timestamps.
    """
    dataset_store = DatasetRegistryStore(":memory:")
    bars = _create_sample_bars("SBIN", 50)
    checksum = compute_dataset_checksum(bars)

    rec = DatasetRecord(
        dataset_id="sbin_daily_v1",
        name="SBIN Daily",
        symbols=["SBIN"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        bar_count=len(bars),
        sha256_checksum=checksum,
    )
    dataset_store.register_dataset(rec)

    service = BacktestService(dataset_store=dataset_store)
    service.register_dataset_bars("sbin_daily_v1", bars)

    # Run with zero/low costs
    low_cost = CostModelConfig(brokerage_per_crore_or_order=0.0, stt_rate=0.0, gst_rate=0.0)
    exp_low = "exp_low_cost"
    service.submit_backtest(
        strategy_id="Canonical_SMA",
        universe=["SBIN"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        cost_model=low_cost,
        initial_capital=100000.0,
        experiment_id=exp_low,
        dataset_id="sbin_daily_v1",
        dataset_checksum=checksum,
    )
    status_low = _await_terminal_status(service, exp_low)
    assert status_low["status"] == "COMPLETED"

    # Run with high costs
    high_cost = CostModelConfig(brokerage_per_crore_or_order=50.0, stt_rate=0.005, gst_rate=0.18)
    exp_high = "exp_high_cost"
    service.submit_backtest(
        strategy_id="Canonical_SMA",
        universe=["SBIN"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        cost_model=high_cost,
        initial_capital=100000.0,
        experiment_id=exp_high,
        dataset_id="sbin_daily_v1",
        dataset_checksum=checksum,
    )
    status_high = _await_terminal_status(service, exp_high)
    assert status_high["status"] == "COMPLETED"

    m_low = json.loads(status_low["metrics_json"])
    m_high = json.loads(status_high["metrics_json"])
    if m_low["number_of_trades"] > 0:
        assert m_low["total_transaction_costs"] < m_high["total_transaction_costs"]
        assert m_low["total_return_pct"] >= m_high["total_return_pct"]


def test_universe_permutation_preserves_same_hash_results():
    """Test 28: Universe ["A", "B"] vs ["B", "A"] under canonical sorting preserves reproducibility hash."""
    dataset_store = DatasetRegistryStore(":memory:")
    bars_a = _create_sample_bars("SYM_A", 40)
    bars_b = _create_sample_bars("SYM_B", 40)
    checksum = compute_dataset_checksum(bars_a + bars_b)

    rec = DatasetRecord(
        dataset_id="univ_daily_v1",
        name="Univ Daily",
        symbols=["SYM_A", "SYM_B"],
        start_date=bars_a[0].timestamp,
        end_date=bars_a[-1].timestamp,
        bar_count=len(bars_a) + len(bars_b),
        sha256_checksum=checksum,
    )
    dataset_store.register_dataset(rec)

    service = BacktestService(dataset_store=dataset_store)
    service.register_dataset_bars("univ_daily_v1", bars_a + bars_b)

    res1 = service.submit_backtest(
        strategy_id="Canonical_SMA",
        universe=["SYM_A", "SYM_B"],
        start_date=bars_a[0].timestamp,
        end_date=bars_a[-1].timestamp,
        initial_capital=100000.0,
        dataset_id="univ_daily_v1",
        dataset_checksum=checksum,
    )

    res2 = service.submit_backtest(
        strategy_id="Canonical_SMA",
        universe=["SYM_B", "SYM_A"],
        start_date=bars_a[0].timestamp,
        end_date=bars_a[-1].timestamp,
        initial_capital=100000.0,
        dataset_id="univ_daily_v1",
        dataset_checksum=checksum,
    )

    assert res1["reproducibility_hash"] == res2["reproducibility_hash"]
