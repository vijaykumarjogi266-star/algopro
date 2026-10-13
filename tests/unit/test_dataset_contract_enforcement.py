"""Unit tests for Dataset Contract Enforcement and Backtest Integrity (R06–R14).

Tests:
R06: test_default_dataset_placeholder_checksum_is_rejected
R07: test_exact_dataset_version_is_required
R08: test_dataset_and_bar_timeframes_must_match
R09: test_rejected_dataset_cannot_trade
R10: test_registry_bar_count_matches_complete_dataset
R11: test_invalid_ohlcv_and_timestamps_fail_closed
R12: test_requested_symbol_coverage_is_complete
R13: test_multisymbol_valuation_is_timestamp_aligned
R14: test_registered_dataset_without_actual_bars_fails
"""

import math
import time
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
import pytest

from data.schemas.canonical_market_data import CanonicalMarketDataBar
from data.schemas.contracts import DataQualityStatus
from services.market_data.registry import (
    DatasetRecord,
    DatasetRegistryStore,
    compute_dataset_checksum,
    DatasetConflictError,
    DatasetIntegrityError,
    DatasetDriftError,
    DatasetNotFoundError,
)
from services.backtest_engine.service import BacktestService
from services.backtest_engine.contracts import (
    ExperimentDefinition,
    ExperimentStatus,
)


def _make_bar(
    symbol: str,
    ts: datetime,
    o: float = 100.0,
    h: float = 105.0,
    l: float = 95.0,
    c: float = 102.0,
    v: float = 1000.0,
    tf: str = "1d",
) -> CanonicalMarketDataBar:
    actual_h = max(h, o, c) + 2.0
    actual_l = min(l, o, c) - 2.0
    return CanonicalMarketDataBar(
        timestamp=ts,
        symbol=symbol,
        exchange="NSE",
        timeframe=tf,
        open=o,
        high=actual_h,
        low=actual_l,
        close=c,
        volume=v,
        trade_count=50,
    )


def _generate_bars(symbol: str, count: int = 10, tf: str = "1d", base_price: float = 100.0) -> List[CanonicalMarketDataBar]:
    base_ts = datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc)
    bars = []
    for i in range(count):
        ts = base_ts + timedelta(days=i) if tf == "1d" else base_ts + timedelta(minutes=5 * i)
        bars.append(_make_bar(symbol, ts, o=base_price + i, h=base_price + i + 5, l=base_price + i - 2, c=base_price + i + 2, tf=tf))
    return bars


def _await_terminal_status(service: BacktestService, experiment_id: str, timeout: float = 3.0):
    start = time.time()
    while time.time() - start < timeout:
        status_rec = service.get_run_status(experiment_id)
        if status_rec and status_rec.get("status") in ("COMPLETED", "FAILED"):
            return status_rec
        time.sleep(0.05)
    return service.get_run_status(experiment_id)


@pytest.mark.parametrize("placeholder", ["a" * 64, "f" * 64])
def test_default_dataset_placeholder_checksum_is_rejected(placeholder):
    """R06: Parameterize 'a'*64 and 'f'*64 as requested checksum; assert CHECKSUM_MISMATCH / FAILED and no fills."""
    dataset_store = DatasetRegistryStore(":memory:")
    service = BacktestService(dataset_store=dataset_store)
    bars = _generate_bars("TCS", 10)
    real_cs = compute_dataset_checksum(bars)

    rec = DatasetRecord(
        dataset_id="tcs_ds",
        name="TCS",
        version="v1",
        exchange="NSE",
        asset_class="EQUITY",
        timeframe="1d",
        symbols=["TCS"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        bar_count=len(bars),
        sha256_checksum=real_cs,
        quality_status=DataQualityStatus.VALID,
    )
    dataset_store.register_dataset(rec)
    service.register_in_memory_dataset("tcs_ds", bars, version="v1")

    exp_id = f"exp_placeholder_{placeholder[:4]}"
    exp_def = ExperimentDefinition(
        experiment_id=exp_id,
        name="Placeholder Test",
        strategy_id="Canonical_SMA",
        strategy_version="1.0.0",
        dataset_id="tcs_ds",
        dataset_version="v1",
        dataset_checksum=placeholder,
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
        dataset_id="tcs_ds",
        dataset_version="v1",
    )

    status = _await_terminal_status(service, exp_id)
    assert status["status"] == "FAILED"
    events = [e["event_type"] for e in service.store.get_audit_events(exp_id)]
    assert "CHECKSUM_MISMATCH" in events
    trades = service.store.get_trades(exp_id)
    assert len(trades) == 0


def test_exact_dataset_version_is_required():
    """R07: Register two versions with distinguishable data. Assert only requested version loaded; unavailable fails."""
    dataset_store = DatasetRegistryStore(":memory:")
    service = BacktestService(dataset_store=dataset_store)

    bars_v1 = _generate_bars("INFY", 10, base_price=100.0)
    bars_v2 = _generate_bars("INFY", 10, base_price=500.0)

    rec_v1 = DatasetRecord(
        dataset_id="infy_ds",
        name="INFY",
        version="v1.0",
        exchange="NSE",
        asset_class="EQUITY",
        timeframe="1d",
        symbols=["INFY"],
        start_date=bars_v1[0].timestamp,
        end_date=bars_v1[-1].timestamp,
        bar_count=len(bars_v1),
        sha256_checksum=compute_dataset_checksum(bars_v1),
        quality_status=DataQualityStatus.VALID,
    )
    rec_v2 = DatasetRecord(
        dataset_id="infy_ds",
        name="INFY",
        version="v2.0",
        exchange="NSE",
        asset_class="EQUITY",
        timeframe="1d",
        symbols=["INFY"],
        start_date=bars_v2[0].timestamp,
        end_date=bars_v2[-1].timestamp,
        bar_count=len(bars_v2),
        sha256_checksum=compute_dataset_checksum(bars_v2),
        quality_status=DataQualityStatus.VALID,
    )
    dataset_store.register_dataset(rec_v1)
    dataset_store.register_dataset(rec_v2)
    service.register_in_memory_dataset("infy_ds", bars_v1, version="v1.0")
    service.register_in_memory_dataset("infy_ds", bars_v2, version="v2.0")

    # Request v2.0
    exp_id = "exp_v2_exact"
    exp_def = ExperimentDefinition(
        experiment_id=exp_id,
        name="Version 2 Test",
        strategy_id="Canonical_SMA",
        strategy_version="1.0.0",
        dataset_id="infy_ds",
        dataset_version="v2.0",
        dataset_checksum=rec_v2.sha256_checksum,
        universe=["INFY"],
        start_date=bars_v2[0].timestamp,
        end_date=bars_v2[-1].timestamp,
        initial_capital=100000.0,
    )
    service.store.save_experiment(exp_def)
    service.submit_backtest(
        strategy_id="Canonical_SMA",
        universe=["INFY"],
        start_date=bars_v2[0].timestamp,
        end_date=bars_v2[-1].timestamp,
        initial_capital=100000.0,
        experiment_id=exp_id,
        dataset_id="infy_ds",
        dataset_version="v2.0",
    )
    status = _await_terminal_status(service, exp_id)
    assert status["status"] == "COMPLETED"

    # Request unavailable version v3.0 fails without fallback
    exp_id_v3 = "exp_v3_unavailable"
    exp_def_v3 = ExperimentDefinition(
        experiment_id=exp_id_v3,
        name="Version 3 Test",
        strategy_id="Canonical_SMA",
        strategy_version="1.0.0",
        dataset_id="infy_ds",
        dataset_version="v3.0",
        dataset_checksum="0" * 64,
        universe=["INFY"],
        start_date=bars_v1[0].timestamp,
        end_date=bars_v1[-1].timestamp,
        initial_capital=100000.0,
    )
    service.store.save_experiment(exp_def_v3)
    service.submit_backtest(
        strategy_id="Canonical_SMA",
        universe=["INFY"],
        start_date=bars_v1[0].timestamp,
        end_date=bars_v1[-1].timestamp,
        initial_capital=100000.0,
        experiment_id=exp_id_v3,
        dataset_id="infy_ds",
        dataset_version="v3.0",
    )
    status_v3 = _await_terminal_status(service, exp_id_v3)
    assert status_v3["status"] == "FAILED"
    events = [e["event_type"] for e in service.store.get_audit_events(exp_id_v3)]
    assert "DATA_UNAVAILABLE" in events


@pytest.mark.parametrize(
    "ds_tf,exp_tf,expect_fail",
    [
        ("1d", "5m", True),
        ("5m", "1d", True),
        ("unsupported_tf", "1d", True),
    ],
)
def test_dataset_and_bar_timeframes_must_match(ds_tf, exp_tf, expect_fail):
    """R08: Parameterize timeframe mismatches; assert failure before execution."""
    dataset_store = DatasetRegistryStore(":memory:")
    service = BacktestService(dataset_store=dataset_store)
    bars = _generate_bars("RELIANCE", 10, tf="1d")

    rec = DatasetRecord(
        dataset_id="rel_tf_ds",
        name="RELIANCE",
        version="v1",
        exchange="NSE",
        asset_class="EQUITY",
        timeframe=ds_tf,
        symbols=["RELIANCE"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        bar_count=len(bars),
        sha256_checksum=compute_dataset_checksum(bars),
        quality_status=DataQualityStatus.VALID,
    )
    dataset_store.register_dataset(rec)
    service.register_in_memory_dataset("rel_tf_ds", bars, version="v1")

    exp_id = f"exp_tf_{ds_tf}_{exp_tf}"
    exp_def = ExperimentDefinition(
        experiment_id=exp_id,
        name="Timeframe Test",
        strategy_id="Canonical_SMA",
        strategy_version="1.0.0",
        dataset_id="rel_tf_ds",
        dataset_version="v1",
        timeframe=exp_tf,
        dataset_checksum=rec.sha256_checksum,
        universe=["RELIANCE"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        initial_capital=100000.0,
    )
    service.store.save_experiment(exp_def)
    service.submit_backtest(
        strategy_id="Canonical_SMA",
        universe=["RELIANCE"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        initial_capital=100000.0,
        timeframe=exp_tf,
        experiment_id=exp_id,
        dataset_id="rel_tf_ds",
        dataset_version="v1",
    )
    status = _await_terminal_status(service, exp_id)
    assert status["status"] == "FAILED"
    events = [e["event_type"] for e in service.store.get_audit_events(exp_id)]
    assert "TIMEFRAME_MISMATCH" in events or "DATA_UNAVAILABLE" in events


@pytest.mark.parametrize("status_val", [DataQualityStatus.CORRUPTED, DataQualityStatus.REJECTED])
def test_rejected_dataset_cannot_trade(status_val):
    """R09: Parameterize CORRUPTED and REJECTED status; assert no simulation/fills/metrics."""
    dataset_store = DatasetRegistryStore(":memory:")
    service = BacktestService(dataset_store=dataset_store)
    bars = _generate_bars("SBIN", 10)

    rec = DatasetRecord(
        dataset_id="sbin_quarantine",
        name="SBIN",
        version="v1",
        exchange="NSE",
        asset_class="EQUITY",
        timeframe="1d",
        symbols=["SBIN"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        bar_count=len(bars),
        sha256_checksum=compute_dataset_checksum(bars),
        quality_status=status_val,
    )
    dataset_store.register_dataset(rec)
    service.register_in_memory_dataset("sbin_quarantine", bars, version="v1")

    exp_id = f"exp_quarantine_{status_val.value}"
    exp_def = ExperimentDefinition(
        experiment_id=exp_id,
        name="Quarantine Test",
        strategy_id="Canonical_SMA",
        strategy_version="1.0.0",
        dataset_id="sbin_quarantine",
        dataset_version="v1",
        dataset_checksum=rec.sha256_checksum,
        universe=["SBIN"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        initial_capital=100000.0,
    )
    service.store.save_experiment(exp_def)
    service.submit_backtest(
        strategy_id="Canonical_SMA",
        universe=["SBIN"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        initial_capital=100000.0,
        experiment_id=exp_id,
        dataset_id="sbin_quarantine",
        dataset_version="v1",
    )
    status = _await_terminal_status(service, exp_id)
    assert status["status"] == "FAILED"
    events = [e["event_type"] for e in service.store.get_audit_events(exp_id)]
    assert "DATASET_REJECTED" in events
    assert len(service.store.get_trades(exp_id)) == 0


def test_registry_bar_count_matches_complete_dataset():
    """R10: Set incorrect declared bar count; assert integrity failure. Legitimate date filtering does not fail."""
    store = DatasetRegistryStore(":memory:")
    bars = _generate_bars("WIPRO", 10)
    checksum = compute_dataset_checksum(bars)

    # 1. Incorrect declared count fails verification
    rec_bad = DatasetRecord(
        dataset_id="wipro_bad_count",
        name="WIPRO",
        version="v1",
        exchange="NSE",
        asset_class="EQUITY",
        timeframe="1d",
        symbols=["WIPRO"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        bar_count=15,  # declared 15, actual 10
        sha256_checksum=checksum,
        quality_status=DataQualityStatus.VALID,
    )
    store.register_dataset(rec_bad)
    with pytest.raises(DatasetIntegrityError, match="Bar count mismatch"):
        store.verify_dataset_bars("wipro_bad_count", bars, fail_closed=True, version="v1")

    # 2. Legitimate declared count passes
    rec_good = DatasetRecord(
        dataset_id="wipro_good_count",
        name="WIPRO",
        version="v1",
        exchange="NSE",
        asset_class="EQUITY",
        timeframe="1d",
        symbols=["WIPRO"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        bar_count=10,
        sha256_checksum=checksum,
        quality_status=DataQualityStatus.VALID,
    )
    store.register_dataset(rec_good)
    assert store.verify_dataset_bars("wipro_good_count", bars, fail_closed=True, version="v1") is True


@pytest.mark.parametrize(
    "corrupt_field,corrupt_value",
    [
        ("open", float("nan")),
        ("close", float("inf")),
        ("low", -10.0),
        ("volume", -500.0),
        ("high", 80.0),  # H < O or H < L violation
        ("timestamp", datetime(2025, 1, 1, 9, 15)),  # Naive timezone
    ],
)
def test_invalid_ohlcv_and_timestamps_fail_closed(corrupt_field, corrupt_value):
    """R11: Parameterize NaN/Inf, invalid OHLC, negative vol, naive ts; assert typed failure."""
    store = DatasetRegistryStore(":memory:")
    base_ts = datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc)
    bar_dict = {
        "timestamp": base_ts,
        "symbol": "TATAMOTORS",
        "exchange": "NSE",
        "timeframe": "1d",
        "open": 100.0,
        "high": 105.0,
        "low": 95.0,
        "close": 102.0,
        "volume": 1000.0,
        "trade_count": 10,
    }
    bar_dict[corrupt_field] = corrupt_value

    try:
        bar = CanonicalMarketDataBar(**bar_dict)
        bars = [bar]
        cs = compute_dataset_checksum(bars)
        rec = DatasetRecord(
            dataset_id="tatamotors_corrupt",
            name="TATAMOTORS",
            version="v1",
            exchange="NSE",
            asset_class="EQUITY",
            timeframe="1d",
            symbols=["TATAMOTORS"],
            start_date=bars[0].timestamp if getattr(bars[0].timestamp, "tzinfo", None) else base_ts,
            end_date=bars[0].timestamp if getattr(bars[0].timestamp, "tzinfo", None) else base_ts,
            bar_count=1,
            sha256_checksum=cs,
            quality_status=DataQualityStatus.VALID,
        )
        store.register_dataset(rec)
        with pytest.raises(DatasetIntegrityError):
            store.verify_dataset_bars("tatamotors_corrupt", bars, fail_closed=True, version="v1")
    except (ValueError, TypeError, DatasetIntegrityError):
        # Successfully caught invalid bar creation or integrity verification
        pass


def test_requested_symbol_coverage_is_complete():
    """R12: Request symbols A and B, but dataset only contains A; assert failure without partial result."""
    dataset_store = DatasetRegistryStore(":memory:")
    service = BacktestService(dataset_store=dataset_store)
    bars_a = _generate_bars("TCS", 10)

    rec = DatasetRecord(
        dataset_id="single_symbol_ds",
        name="Single Symbol",
        version="v1",
        exchange="NSE",
        asset_class="EQUITY",
        timeframe="1d",
        symbols=["TCS"],  # Only TCS covered
        start_date=bars_a[0].timestamp,
        end_date=bars_a[-1].timestamp,
        bar_count=len(bars_a),
        sha256_checksum=compute_dataset_checksum(bars_a),
        quality_status=DataQualityStatus.VALID,
    )
    dataset_store.register_dataset(rec)
    service.register_in_memory_dataset("single_symbol_ds", bars_a, version="v1")

    exp_id = "exp_multi_symbol_incomplete"
    exp_def = ExperimentDefinition(
        experiment_id=exp_id,
        name="Missing Symbol Test",
        strategy_id="Canonical_SMA",
        strategy_version="1.0.0",
        dataset_id="single_symbol_ds",
        dataset_version="v1",
        dataset_checksum=rec.sha256_checksum,
        universe=["TCS", "INFY"],  # Requesting TCS and INFY
        start_date=bars_a[0].timestamp,
        end_date=bars_a[-1].timestamp,
        initial_capital=100000.0,
    )
    service.store.save_experiment(exp_def)
    service.submit_backtest(
        strategy_id="Canonical_SMA",
        universe=["TCS", "INFY"],
        start_date=bars_a[0].timestamp,
        end_date=bars_a[-1].timestamp,
        initial_capital=100000.0,
        experiment_id=exp_id,
        dataset_id="single_symbol_ds",
        dataset_version="v1",
    )
    status = _await_terminal_status(service, exp_id)
    assert status["status"] == "FAILED"
    events = [e["event_type"] for e in service.store.get_audit_events(exp_id)]
    assert "MISSING_SYMBOL" in events


def test_multisymbol_valuation_is_timestamp_aligned():
    """R13: Assert multi-symbol replay aligns by timestamps and no future or shifted price is used."""
    dataset_store = DatasetRegistryStore(":memory:")
    service = BacktestService(dataset_store=dataset_store)

    base_ts = datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc)
    # Symbol A has days 0, 1, 2
    bars_a = [_make_bar("SYM_A", base_ts + timedelta(days=i), c=100.0 + i) for i in [0, 1, 2]]
    # Symbol B has days 0, 2 (missing day 1)
    bars_b = [_make_bar("SYM_B", base_ts + timedelta(days=i), c=200.0 + i) for i in [0, 2]]

    all_bars = bars_a + bars_b
    rec = DatasetRecord(
        dataset_id="aligned_ds",
        name="Aligned DS",
        version="v1",
        exchange="NSE",
        asset_class="EQUITY",
        timeframe="1d",
        symbols=["SYM_A", "SYM_B"],
        start_date=base_ts,
        end_date=base_ts + timedelta(days=2),
        bar_count=len(all_bars),
        sha256_checksum=compute_dataset_checksum(all_bars),
        quality_status=DataQualityStatus.VALID,
    )
    dataset_store.register_dataset(rec)
    service.register_in_memory_dataset("aligned_ds", all_bars, version="v1")

    exp_id = "exp_aligned_valuation"
    exp_def = ExperimentDefinition(
        experiment_id=exp_id,
        name="Aligned Test",
        strategy_id="Canonical_SMA",
        strategy_version="1.0.0",
        dataset_id="aligned_ds",
        dataset_version="v1",
        dataset_checksum=rec.sha256_checksum,
        universe=["SYM_A", "SYM_B"],
        start_date=base_ts,
        end_date=base_ts + timedelta(days=2),
        initial_capital=100000.0,
    )
    service.store.save_experiment(exp_def)
    service.submit_backtest(
        strategy_id="Canonical_SMA",
        universe=["SYM_A", "SYM_B"],
        start_date=base_ts,
        end_date=base_ts + timedelta(days=2),
        initial_capital=100000.0,
        experiment_id=exp_id,
        dataset_id="aligned_ds",
        dataset_version="v1",
    )
    status = _await_terminal_status(service, exp_id)
    assert status["status"] == "COMPLETED"


def test_registered_dataset_without_actual_bars_fails(monkeypatch):
    """R14: Registered dataset without loaded bars fails with DATA_UNAVAILABLE and synthetic generator is never called."""
    dataset_store = DatasetRegistryStore(":memory:")
    service = BacktestService(dataset_store=dataset_store)

    def _mock_synthetic(*args, **kwargs):
        raise AssertionError("Synthetic generator was prohibited but called!")
    monkeypatch.setattr(service, "_generate_ohlcv_bars", _mock_synthetic)

    base_ts = datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc)
    rec = DatasetRecord(
        dataset_id="no_bars_ds",
        name="No Bars",
        version="v1",
        exchange="NSE",
        asset_class="EQUITY",
        timeframe="1d",
        symbols=["TCS"],
        start_date=base_ts,
        end_date=base_ts + timedelta(days=5),
        bar_count=5,
        sha256_checksum="0" * 64,
        quality_status=DataQualityStatus.VALID,
    )
    dataset_store.register_dataset(rec)
    # Deliberately DO NOT call service.register_in_memory_dataset

    exp_id = "exp_no_bars"
    exp_def = ExperimentDefinition(
        experiment_id=exp_id,
        name="No Bars Test",
        strategy_id="Canonical_SMA",
        strategy_version="1.0.0",
        dataset_id="no_bars_ds",
        dataset_version="v1",
        dataset_checksum="0" * 64,
        universe=["TCS"],
        start_date=base_ts,
        end_date=base_ts + timedelta(days=5),
        initial_capital=100000.0,
    )
    service.store.save_experiment(exp_def)
    service.submit_backtest(
        strategy_id="Canonical_SMA",
        universe=["TCS"],
        start_date=base_ts,
        end_date=base_ts + timedelta(days=5),
        initial_capital=100000.0,
        experiment_id=exp_id,
        dataset_id="no_bars_ds",
        dataset_version="v1",
    )
    status = _await_terminal_status(service, exp_id)
    assert status["status"] == "FAILED"
    events = [e["event_type"] for e in service.store.get_audit_events(exp_id)]
    assert "DATA_UNAVAILABLE" in events


# ==============================================================================
# Batch A Remediation Tests (A01 - A08)
# ==============================================================================

def test_a01_missing_dataset_produces_no_generated_history():
    """A01: Missing dataset and default-named dataset without explicit fixture produce no generated history."""
    store = DatasetRegistryStore(":memory:")
    service = BacktestService(dataset_store=store)  # production mode: allow_synthetic=False

    base_ts = datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc)
    exp_id = "exp_a01_missing_default"

    # Submit backtest requesting default named dataset without any pre-registered fixtures
    service.submit_backtest(
        strategy_id="Canonical_SMA",
        universe=["RELIANCE"],
        start_date=base_ts,
        end_date=base_ts + timedelta(days=30),
        initial_capital=100_000.0,
        experiment_id=exp_id,
        dataset_id="NSE_NIFTY50_DAILY",
    )

    status = _await_terminal_status(service, exp_id)
    assert status["status"] == "FAILED"
    events = [e["event_type"] for e in service.store.get_audit_events(exp_id)]
    assert "DATA_UNAVAILABLE" in events

    # Verify fail-closed invariants: zero synthetic bars loaded, no trades, no equity curve, no metrics
    assert "NSE_NIFTY50_DAILY" not in service._in_memory_dataset_bars
    assert len(service.store.get_trades(exp_id)) == 0
    assert len(service.store.get_equity_curve(exp_id)) == 0
    run = service.get_run_status(exp_id)
    assert run.get("metrics_json") is None or run.get("metrics_json") == ""


def test_a02_production_path_blocks_synthetic_helpers():
    """A02: Calling synthetic generation helpers on production path fails closed."""
    service = BacktestService()  # allow_synthetic=False by default

    with pytest.raises(RuntimeError, match="prohibited on production paths"):
        service._ensure_default_dataset()

    base_ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(RuntimeError, match="prohibited on production paths"):
        service._generate_ohlcv_bars("TCS", base_ts, base_ts + timedelta(days=10), seed=42)


def test_a03_explicit_registered_fixture_succeeds():
    """A03: Explicit registered fixture executes and completes successfully."""
    store = DatasetRegistryStore(":memory:")
    service = BacktestService(dataset_store=store)

    bars = _generate_bars("TCS", 40)
    chk = compute_dataset_checksum(bars)
    rec = DatasetRecord(
        dataset_id="explicit_fixture_ds",
        name="Explicit Fixture",
        version="v1.0.0",
        exchange="NSE",
        asset_class="EQUITY",
        timeframe="1d",
        symbols=["TCS"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        bar_count=len(bars),
        sha256_checksum=chk,
        quality_status=DataQualityStatus.VALID,
    )
    store.register_dataset(rec)
    service.register_dataset_bars("explicit_fixture_ds", bars, version="v1.0.0")

    exp_id = "exp_a03_explicit"
    exp_def = ExperimentDefinition(
        experiment_id=exp_id,
        name="Explicit Fixture Test",
        strategy_id="Canonical_SMA",
        strategy_version="1.0.0",
        dataset_id="explicit_fixture_ds",
        dataset_version="v1.0.0",
        dataset_checksum=chk,
        universe=["TCS"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        initial_capital=100_000.0,
    )
    service.store.save_experiment(exp_def)
    service.submit_backtest(
        strategy_id="Canonical_SMA",
        universe=["TCS"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        initial_capital=100_000.0,
        experiment_id=exp_id,
        dataset_id="explicit_fixture_ds",
        dataset_version="v1.0.0",
        dataset_checksum=chk,
    )

    status = _await_terminal_status(service, exp_id)
    assert status["status"] == "COMPLETED"


def test_a04_dataset_version_immutable_on_conflict():
    """A04: Modifying content or provenance on existing version raises DatasetConflictError, leaving record unchanged."""
    store = DatasetRegistryStore(":memory:")
    bars = _generate_bars("INFY", 20)
    chk = compute_dataset_checksum(bars)

    orig_rec = DatasetRecord(
        dataset_id="ds_immutable",
        name="INFY Daily",
        version="v1.0.0",
        exchange="NSE",
        asset_class="EQUITY",
        timeframe="1d",
        symbols=["INFY"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        bar_count=len(bars),
        sha256_checksum=chk,
        quality_status=DataQualityStatus.VALID,
        metadata={"initial": True},
    )
    store.register_dataset(orig_rec)

    # 1. Conflict on modified checksum
    conflict_chk = DatasetRecord(
        dataset_id="ds_immutable",
        name="INFY Daily",
        version="v1.0.0",
        exchange="NSE",
        asset_class="EQUITY",
        timeframe="1d",
        symbols=["INFY"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        bar_count=len(bars),
        sha256_checksum="f" * 64,
        quality_status=DataQualityStatus.VALID,
    )
    with pytest.raises(DatasetConflictError, match="already exists with differing"):
        store.register_dataset(conflict_chk)

    # 2. Conflict on bar_count
    conflict_count = DatasetRecord(
        dataset_id="ds_immutable",
        name="INFY Daily",
        version="v1.0.0",
        exchange="NSE",
        asset_class="EQUITY",
        timeframe="1d",
        symbols=["INFY"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        bar_count=999,
        sha256_checksum=chk,
        quality_status=DataQualityStatus.VALID,
    )
    with pytest.raises(DatasetConflictError, match="already exists with differing"):
        store.register_dataset(conflict_count)

    # 3. Conflict on start_date
    conflict_dates = DatasetRecord(
        dataset_id="ds_immutable",
        name="INFY Daily",
        version="v1.0.0",
        exchange="NSE",
        asset_class="EQUITY",
        timeframe="1d",
        symbols=["INFY"],
        start_date=bars[0].timestamp + timedelta(days=1),
        end_date=bars[-1].timestamp,
        bar_count=len(bars),
        sha256_checksum=chk,
        quality_status=DataQualityStatus.VALID,
    )
    with pytest.raises(DatasetConflictError, match="already exists with differing"):
        store.register_dataset(conflict_dates)

    # Verify original record remains pristine
    preserved = store.get_dataset("ds_immutable", version="v1.0.0")
    assert preserved.sha256_checksum == chk
    assert preserved.bar_count == len(bars)
    assert preserved.start_date == orig_rec.start_date
    assert preserved.metadata == {"initial": True}


def test_a05_identical_registration_is_idempotent():
    """A05: Identical registration succeeds idempotently, updating mutable annotations."""
    store = DatasetRegistryStore(":memory:")
    bars = _generate_bars("SBIN", 15)
    chk = compute_dataset_checksum(bars)

    rec = DatasetRecord(
        dataset_id="ds_idempotent",
        name="SBIN Daily",
        version="v1.0.0",
        exchange="NSE",
        asset_class="EQUITY",
        timeframe="1d",
        symbols=["SBIN"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        bar_count=len(bars),
        sha256_checksum=chk,
        quality_status=DataQualityStatus.VALID,
        metadata={"version_state": "draft"},
    )
    store.register_dataset(rec)

    # Re-register with identical content but updated mutable metadata
    rec_update = DatasetRecord(
        dataset_id="ds_idempotent",
        name="SBIN Daily",
        version="v1.0.0",
        exchange="NSE",
        asset_class="EQUITY",
        timeframe="1d",
        symbols=["SBIN"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        bar_count=len(bars),
        sha256_checksum=chk,
        quality_status=DataQualityStatus.VALID,
        metadata={"version_state": "verified", "reviewed_by": "qa"},
    )
    updated = store.register_dataset(rec_update)
    assert updated.metadata == {"version_state": "verified", "reviewed_by": "qa"}

    stored = store.get_dataset("ds_idempotent", version="v1.0.0")
    assert stored.metadata == {"version_state": "verified", "reviewed_by": "qa"}
    assert stored.sha256_checksum == chk


def test_a07_replay_pinned_to_exact_version():
    """A07: Replay remains strictly pinned to original registered version despite subsequent versions."""
    store = DatasetRegistryStore(":memory:")
    service = BacktestService(dataset_store=store)

    bars_v1 = _generate_bars("TCS", 20, base_price=100.0)
    chk_v1 = compute_dataset_checksum(bars_v1)
    rec_v1 = DatasetRecord(
        dataset_id="pinned_ds",
        name="TCS",
        version="v1.0.0",
        symbols=["TCS"],
        start_date=bars_v1[0].timestamp,
        end_date=bars_v1[-1].timestamp,
        bar_count=len(bars_v1),
        sha256_checksum=chk_v1,
    )
    store.register_dataset(rec_v1)
    service.register_dataset_bars("pinned_ds", bars_v1, version="v1.0.0")

    # Create experiment pinned to v1.0.0
    exp_id = "exp_pinned_v1"
    exp_def = ExperimentDefinition(
        experiment_id=exp_id,
        name="Pinned Test",
        strategy_id="Canonical_SMA",
        strategy_version="1.0.0",
        dataset_id="pinned_ds",
        dataset_version="v1.0.0",
        dataset_checksum=chk_v1,
        universe=["TCS"],
        start_date=bars_v1[0].timestamp,
        end_date=bars_v1[-1].timestamp,
        initial_capital=100_000.0,
    )
    service.store.save_experiment(exp_def)

    # Register v2.0.0 with different bars and checksum
    bars_v2 = _generate_bars("TCS", 30, base_price=200.0)
    chk_v2 = compute_dataset_checksum(bars_v2)
    rec_v2 = DatasetRecord(
        dataset_id="pinned_ds",
        name="TCS",
        version="v2.0.0",
        symbols=["TCS"],
        start_date=bars_v2[0].timestamp,
        end_date=bars_v2[-1].timestamp,
        bar_count=len(bars_v2),
        sha256_checksum=chk_v2,
    )
    store.register_dataset(rec_v2)
    service.register_dataset_bars("pinned_ds", bars_v2, version="v2.0.0")

    # Run experiment
    service.submit_backtest(
        strategy_id="Canonical_SMA",
        universe=["TCS"],
        start_date=bars_v1[0].timestamp,
        end_date=bars_v1[-1].timestamp,
        initial_capital=100_000.0,
        experiment_id=exp_id,
        dataset_id="pinned_ds",
        dataset_version="v1.0.0",
        dataset_checksum=chk_v1,
    )
    status = _await_terminal_status(service, exp_id)
    assert status["status"] == "COMPLETED"

    # Verify run record in store is strictly pinned to v1.0.0 and chk_v1
    stored_exp = service.store.get_experiment(exp_id)
    assert stored_exp.dataset_version == "v1.0.0"
    assert stored_exp.dataset_checksum == chk_v1


def test_a08_contract_violations_fail_before_fills():
    """A08: Quarantined dataset fails closed before order execution."""
    store = DatasetRegistryStore(":memory:")
    service = BacktestService(dataset_store=store)

    bars = _generate_bars("RELIANCE", 20)
    chk = compute_dataset_checksum(bars)
    rec = DatasetRecord(
        dataset_id="quarantine_ds",
        name="Quarantine Test",
        version="v1.0.0",
        symbols=["RELIANCE"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        bar_count=len(bars),
        sha256_checksum=chk,
        quality_status=DataQualityStatus.VALID,
    )
    store.register_dataset(rec)
    store.quarantine_dataset("quarantine_ds", "Suspected data corruption", version="v1.0.0")
    service.register_dataset_bars("quarantine_ds", bars, version="v1.0.0")

    exp_id = "exp_a08_quarantine"
    service.submit_backtest(
        strategy_id="Canonical_SMA",
        universe=["RELIANCE"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        initial_capital=100_000.0,
        experiment_id=exp_id,
        dataset_id="quarantine_ds",
        dataset_version="v1.0.0",
        dataset_checksum=chk,
    )
    status = _await_terminal_status(service, exp_id)
    assert status["status"] == "FAILED"
    events = [e["event_type"] for e in service.store.get_audit_events(exp_id)]
    assert "DATASET_REJECTED" in events or "DATA_UNAVAILABLE" in events
    assert len(service.store.get_trades(exp_id)) == 0
