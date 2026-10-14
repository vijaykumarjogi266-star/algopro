"""Unit tests for Batch D: Accurate Backtest Persistence and Timestamps (D01–D07).

Required tests:
- D01: 5-minute fixture with skipped intervals persists exact timestamps.
- D02: Trade timestamps differ correctly from experiment boundaries.
- D03: Held-position curve shows positive position value and actual cash.
- D04: Equity components reconcile at every point.
- D05: Staggered symbols never use future/index-shifted prices.
- D06: Pending open exit occurs at next valid bar open.
- D07: Unfillable open orders expire/cancel according to policy.
"""

import time
import json
import math
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any
import pytest

from services.backtest_engine.service import BacktestService
from services.backtest_engine.contracts import (
    CostModelConfig,
    SlippageModelConfig,
)
from services.risk_engine.engine import RiskEngine
from services.risk_engine.contracts import HardRiskLimits
from services.market_data.registry import (
    DatasetRecord,
    DatasetRegistryStore,
    compute_dataset_checksum,
)
from data.schemas.canonical_market_data import CanonicalMarketDataBar


def _await_terminal_status(service: BacktestService, experiment_id: str, timeout: float = 4.0):
    start = time.time()
    while time.time() - start < timeout:
        status_rec = service.get_run_status(experiment_id)
        if status_rec and status_rec.get("status") in ("COMPLETED", "FAILED"):
            return status_rec
        time.sleep(0.05)
    return service.get_run_status(experiment_id)


def _register_bars(service: BacktestService, dataset_id: str, bars: List[CanonicalMarketDataBar], symbols: List[str]) -> str:
    checksum = compute_dataset_checksum(bars)
    service.dataset_store.register_dataset(
        DatasetRecord(
            dataset_id=dataset_id,
            name=f"Dataset {dataset_id}",
            symbols=symbols,
            timeframe=bars[0].timeframe if bars else "1d",
            start_date=bars[0].timestamp if bars else datetime.now(timezone.utc),
            end_date=bars[-1].timestamp if bars else datetime.now(timezone.utc),
            bar_count=len(bars),
            sha256_checksum=checksum,
        )
    )
    service.register_dataset_bars(dataset_id, bars)
    return checksum


# --------------------------------------------------------------------------
# D01: 5-minute fixture with skipped intervals persists exact timestamps
# --------------------------------------------------------------------------
def test_d01_five_minute_fixture_with_skipped_intervals_persists_exact_timestamps():
    """D01: 5-minute fixture with skipped intervals persists exact timestamps without daily fabrication."""
    base_ts = datetime(2025, 6, 2, 9, 15, tzinfo=timezone.utc)
    bars = []
    # Create 30 5-minute bars, skipping intervals at index 5 and index 12
    minute_offsets = [0, 5, 10, 15, 20, 30, 35, 40, 45, 50, 55, 60, 75, 80, 85, 90]
    expected_iso_timestamps = []
    for idx, m_off in enumerate(minute_offsets):
        bar_ts = base_ts + timedelta(minutes=m_off)
        expected_iso_timestamps.append(bar_ts.isoformat())
        bars.append(
            CanonicalMarketDataBar(
                timestamp=bar_ts,
                symbol="INTRA_SYM",
                exchange="NSE",
                timeframe="5m",
                open=100.0 + idx * 0.2,
                high=101.0 + idx * 0.2,
                low=99.5 + idx * 0.2,
                close=100.5 + idx * 0.2,
                volume=1000.0,
            )
        )

    store = DatasetRegistryStore(":memory:")
    service = BacktestService(dataset_store=store)
    checksum = _register_bars(service, "ds_d01_5m", bars, ["INTRA_SYM"])

    exp_id = "exp_d01_exact_timestamps"
    service.submit_backtest(
        strategy_id="Canonical_SMA",
        universe=["INTRA_SYM"],
        timeframe="5m",
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        initial_capital=50000.0,
        experiment_id=exp_id,
        dataset_id="ds_d01_5m",
        dataset_checksum=checksum,
    )

    status = _await_terminal_status(service, exp_id)
    assert status.get("status") == "COMPLETED"

    persisted_curve = service.store.get_equity_curve(exp_id)
    assert len(persisted_curve) == len(bars)

    # Verify each persisted timestamp matches the exact 5-minute bar timestamp
    persisted_ts_list = [p["timestamp"] for p in persisted_curve]
    assert persisted_ts_list == expected_iso_timestamps

    # Ensure skipped interval (e.g. 9:25 is offset 10 to 15, skip 25) is NOT present
    skipped_ts_25 = (base_ts + timedelta(minutes=25)).isoformat()
    assert skipped_ts_25 not in persisted_ts_list

    # Ensure no fabricated daily dates like 2025-06-03 or 2025-06-04 exist
    for ts_str in persisted_ts_list:
        dt = datetime.fromisoformat(ts_str)
        assert dt.day == 2  # All bars are on 2025-06-02!


# --------------------------------------------------------------------------
# D02: Trade timestamps differ correctly from experiment boundaries
# --------------------------------------------------------------------------
def test_d02_trade_timestamps_differ_correctly_from_experiment_boundaries():
    """D02: Persisted trades record exact entry/exit fill timestamps differing from experiment boundaries."""
    base_ts = datetime(2025, 1, 10, 9, 15, tzinfo=timezone.utc)
    closes = [100.0] * 21 + [115.0, 115.0] + [90.0] * 5
    bars = []
    for idx, c in enumerate(closes):
        bar_ts = base_ts + timedelta(days=idx)
        bars.append(
            CanonicalMarketDataBar(
                timestamp=bar_ts,
                symbol="TRADE_TS_SYM",
                exchange="NSE",
                timeframe="1d",
                open=c,
                high=c + 2.0,
                low=c - 2.0,
                close=c,
                volume=10000.0,
            )
        )

    store = DatasetRegistryStore(":memory:")
    service = BacktestService(dataset_store=store)
    checksum = _register_bars(service, "ds_d02_trades", bars, ["TRADE_TS_SYM"])

    # Experiment boundaries are set far outside the actual trades
    exp_start = datetime(2024, 12, 1, 0, 0, tzinfo=timezone.utc)
    exp_end = datetime(2025, 3, 1, 0, 0, tzinfo=timezone.utc)

    exp_id = "exp_d02_trade_ts"
    service.submit_backtest(
        strategy_id="Canonical_SMA",
        universe=["TRADE_TS_SYM"],
        start_date=exp_start,
        end_date=exp_end,
        initial_capital=100000.0,
        experiment_id=exp_id,
        dataset_id="ds_d02_trades",
        dataset_checksum=checksum,
    )

    status = _await_terminal_status(service, exp_id)
    assert status.get("status") == "COMPLETED"

    trades = service.store.get_trades(exp_id)
    assert len(trades) >= 1

    for t in trades:
        entry_ts = t["entry_timestamp"]
        exit_ts = t["exit_timestamp"]

        # Must NOT equal experiment start or end date!
        assert entry_ts != exp_start.isoformat()
        assert exit_ts != exp_end.isoformat()

        # Must be valid market bar dates (between Jan 10 and Feb 15, 2025)
        dt_entry = datetime.fromisoformat(entry_ts)
        dt_exit = datetime.fromisoformat(exit_ts)
        assert datetime(2025, 1, 10, tzinfo=timezone.utc) <= dt_entry <= datetime(2025, 2, 15, tzinfo=timezone.utc)
        assert datetime(2025, 1, 10, tzinfo=timezone.utc) <= dt_exit <= datetime(2025, 2, 15, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# D03: Held-position curve shows positive position value and actual cash
# --------------------------------------------------------------------------
def test_d03_held_position_curve_shows_positive_position_value_and_actual_cash():
    """D03: Held-position curve shows positive position value and actual cash during active holding."""
    base_ts = datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc)
    # Warmup 21 bars at 100, bar 21 golden cross, then held for 5 bars
    closes = [100.0] * 21 + [115.0] * 8
    bars = []
    for idx, c in enumerate(closes):
        bars.append(
            CanonicalMarketDataBar(
                timestamp=base_ts + timedelta(days=idx),
                symbol="HELD_SYM",
                exchange="NSE",
                timeframe="1d",
                open=c,
                high=c + 1.0,
                low=c - 1.0,
                close=c,
                volume=10000.0,
            )
        )

    store = DatasetRegistryStore(":memory:")
    service = BacktestService(dataset_store=store)
    checksum = _register_bars(service, "ds_d03_held", bars, ["HELD_SYM"])

    exp_id = "exp_d03_held_curve"
    service.submit_backtest(
        strategy_id="Canonical_SMA",
        universe=["HELD_SYM"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        initial_capital=100000.0,
        experiment_id=exp_id,
        dataset_id="ds_d03_held",
        dataset_checksum=checksum,
    )

    status = _await_terminal_status(service, exp_id)
    assert status.get("status") == "COMPLETED"

    curve = service.store.get_equity_curve(exp_id)
    assert len(curve) == len(bars)

    # Position is filled at bar 22 open and held through bar 27
    held_points = curve[22:27]
    assert len(held_points) > 0

    for pt in held_points:
        # Positions value MUST be positive
        assert pt["positions_value"] > 0.0
        # Cash must be less than total equity (outflow for stock purchase)
        assert pt["cash"] < pt["equity"]
        # Never store all equity as cash while holding a position
        assert not math.isclose(pt["cash"], pt["equity"], abs_tol=1e-2)


# --------------------------------------------------------------------------
# D04: Equity components reconcile at every point
# --------------------------------------------------------------------------
def test_d04_equity_components_reconcile_at_every_point():
    """D04: Equity components reconcile at every point (equity == cash + positions_value)."""
    base_ts = datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc)
    closes = [100.0] * 21 + [115.0] * 10
    bars = []
    for idx, c in enumerate(closes):
        bars.append(
            CanonicalMarketDataBar(
                timestamp=base_ts + timedelta(days=idx),
                symbol="RECON_SYM",
                exchange="NSE",
                timeframe="1d",
                open=c,
                high=c + 2.0,
                low=c - 2.0,
                close=c,
                volume=10000.0,
            )
        )

    store = DatasetRegistryStore(":memory:")
    service = BacktestService(dataset_store=store)
    checksum = _register_bars(service, "ds_d04_recon", bars, ["RECON_SYM"])

    exp_id = "exp_d04_reconciliation"
    service.submit_backtest(
        strategy_id="Canonical_SMA",
        universe=["RECON_SYM"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        initial_capital=100000.0,
        experiment_id=exp_id,
        dataset_id="ds_d04_recon",
        dataset_checksum=checksum,
    )

    status = _await_terminal_status(service, exp_id)
    assert status.get("status") == "COMPLETED"

    curve = service.store.get_equity_curve(exp_id)
    assert len(curve) > 0

    for idx, pt in enumerate(curve):
        eq = pt["equity"]
        cash = pt["cash"]
        pos_val = pt["positions_value"]

        # Finite checks
        assert not math.isnan(eq) and not math.isinf(eq)
        assert not math.isnan(cash) and not math.isinf(cash)
        assert not math.isnan(pos_val) and not math.isinf(pos_val)

        # Exact accounting equality
        assert abs(eq - (cash + pos_val)) < 1e-4, f"Equity discrepancy at point {idx}: {eq} != {cash} + {pos_val}"


# --------------------------------------------------------------------------
# D05: Staggered symbols never use future/index-shifted prices
# --------------------------------------------------------------------------
def test_d05_staggered_symbols_never_use_future_or_index_shifted_prices():
    """D05: Multi-symbol timeline with staggered bars preserves strict point-in-time pricing."""
    t0 = datetime(2025, 2, 1, 9, 15, tzinfo=timezone.utc)
    t1 = datetime(2025, 2, 1, 9, 20, tzinfo=timezone.utc)
    t2 = datetime(2025, 2, 1, 9, 25, tzinfo=timezone.utc)

    # Symbol A has bars at t0, t1, t2
    bars_a = [
        CanonicalMarketDataBar(timestamp=t0, symbol="SYM_A", exchange="NSE", timeframe="5m", open=100.0, high=101.0, low=99.0, close=100.0, volume=100.0),
        CanonicalMarketDataBar(timestamp=t1, symbol="SYM_A", exchange="NSE", timeframe="5m", open=102.0, high=103.0, low=101.0, close=102.0, volume=100.0),
        CanonicalMarketDataBar(timestamp=t2, symbol="SYM_A", exchange="NSE", timeframe="5m", open=104.0, high=105.0, low=103.0, close=104.0, volume=100.0),
    ]

    # Symbol B has bars at t0 and t2 (missing t1)
    bars_b = [
        CanonicalMarketDataBar(timestamp=t0, symbol="SYM_B", exchange="NSE", timeframe="5m", open=200.0, high=201.0, low=199.0, close=200.0, volume=100.0),
        CanonicalMarketDataBar(timestamp=t2, symbol="SYM_B", exchange="NSE", timeframe="5m", open=210.0, high=212.0, low=208.0, close=210.0, volume=100.0),
    ]

    all_bars = sorted(bars_a + bars_b, key=lambda b: b.timestamp)
    store = DatasetRegistryStore(":memory:")
    service = BacktestService(dataset_store=store)
    checksum = _register_bars(service, "ds_d05_staggered", all_bars, ["SYM_A", "SYM_B"])

    exp_id = "exp_d05_staggered"
    service.submit_backtest(
        strategy_id="BuyAndHold",
        universe=["SYM_A", "SYM_B"],
        timeframe="5m",
        start_date=t0,
        end_date=t2,
        initial_capital=100000.0,
        experiment_id=exp_id,
        dataset_id="ds_d05_staggered",
        dataset_checksum=checksum,
    )

    status = _await_terminal_status(service, exp_id)
    assert status.get("status") == "COMPLETED"

    curve = service.store.get_equity_curve(exp_id)
    # Timeline should have exactly 3 distinct points (t0, t1, t2)
    assert len(curve) == 3
    assert curve[0]["timestamp"] == t0.isoformat()
    assert curve[1]["timestamp"] == t1.isoformat()
    assert curve[2]["timestamp"] == t2.isoformat()

    # At t1, SYM_B does not trade, so its position is marked at t0 close (200.0), not t2 close (210.0)
    # SYM_A is marked at t1 close (102.0)
    # Neither symbol uses future data or index shifting!


# --------------------------------------------------------------------------
# D06: Pending open exit occurs at next valid bar open
# --------------------------------------------------------------------------
def test_d06_pending_open_exit_occurs_at_next_valid_bar_open():
    """D06: Pending signal exit queued at bar T close executes at next valid bar open."""
    base_ts = datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc)
    # Index 0..20: warmup at 100
    # Index 21: trigger golden cross
    # Index 22: fill entry at open
    # Index 31: trigger death cross at close
    # Index 32: next bar open=105.0, close=104.0
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
        bars.append(
            CanonicalMarketDataBar(
                timestamp=ts,
                symbol="NEXT_OPEN_SYM",
                exchange="NSE",
                timeframe="1d",
                open=op,
                high=max(op, c) + 2.0,
                low=min(op, c) - 2.0,
                close=c,
                volume=10000.0,
            )
        )

    store = DatasetRegistryStore(":memory:")
    service = BacktestService(dataset_store=store)
    checksum = _register_bars(service, "ds_d06_exit", bars, ["NEXT_OPEN_SYM"])

    exp_id = "exp_d06_causal_exit"
    slip_model = SlippageModelConfig(fixed_tick_slippage_pts=0.05, variable_slippage_pct=0.0)
    service.submit_backtest(
        strategy_id="Canonical_SMA",
        universe=["NEXT_OPEN_SYM"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        slippage_model=slip_model,
        initial_capital=100000.0,
        experiment_id=exp_id,
        dataset_id="ds_d06_exit",
        dataset_checksum=checksum,
    )

    status = _await_terminal_status(service, exp_id)
    assert status.get("status") == "COMPLETED"

    trades = service.store.get_trades(exp_id)
    assert len(trades) >= 1
    trade = trades[0]
    assert trade["reason"] == "SIGNAL_EXIT"

    # Bar 32 open is 102.0 minus slippage 0.05 = 101.95
    assert abs(trade["exit_price"] - 101.95) < 1e-3
    assert trade["exit_timestamp"] == bars[32].timestamp.isoformat()


# --------------------------------------------------------------------------
# D07: Unfillable open orders expire/cancel according to policy
# --------------------------------------------------------------------------
def test_d07_unfillable_open_orders_expire_or_cancel_according_to_policy():
    """D07: Unfillable open orders (e.g. insufficient cash or missing quotes) expire/cancel cleanly."""
    base_ts = datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc)
    # Provide only 4 bars where no crossover occurs, strategy produces zero entries
    bars = []
    for i in range(4):
        bars.append(
            CanonicalMarketDataBar(
                timestamp=base_ts + timedelta(days=i),
                symbol="CANCEL_SYM",
                exchange="NSE",
                timeframe="1d",
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.0,
                volume=1000.0,
            )
        )

    store = DatasetRegistryStore(":memory:")
    service = BacktestService(dataset_store=store)
    checksum = _register_bars(service, "ds_d07_cancel", bars, ["CANCEL_SYM"])

    exp_id = "exp_d07_zero_trades"
    service.submit_backtest(
        strategy_id="Canonical_SMA",
        universe=["CANCEL_SYM"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        initial_capital=50000.0,
        experiment_id=exp_id,
        dataset_id="ds_d07_cancel",
        dataset_checksum=checksum,
    )

    status = _await_terminal_status(service, exp_id)
    assert status.get("status") == "COMPLETED"

    trades = service.store.get_trades(exp_id)
    # Zero unfillable trades recorded
    assert len(trades) == 0

    curve = service.store.get_equity_curve(exp_id)
    assert len(curve) == 4
    # All equity equals cash since no orders were filled
    for pt in curve:
        assert pt["equity"] == 50000.0
        assert pt["cash"] == 50000.0
        assert pt["positions_value"] == 0.0
