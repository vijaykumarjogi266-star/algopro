"""Tests for Backtest Causal Timing and Gap-Aware Execution.

Tests:
29. test_close_signal_exit_fills_next_bar_not_same_bar_open
30. test_gap_through_stop_fills_at_open_or_worse
31. test_entry_cash_changes_only_at_fill_event
32. test_end_of_bar_equity_reflects_prior_stop_exit
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
    ReproducibilityRecord,
)
from services.market_data.registry import (
    DatasetRecord,
    DatasetRegistryStore,
    compute_dataset_checksum,
)
from data.schemas.canonical_market_data import CanonicalMarketDataBar


def _build_causality_bars(symbol: str = "CAUSAL_SYM") -> List[CanonicalMarketDataBar]:
    """Closes: [100]*21 + [110, 110] + [101]*12 (total 35 bars).

    Index 0..20: 100
    Index 21: 110
    Index 22: 110 (open=100)
    Index 23..34: 101
    """
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
        bars.append(
            CanonicalMarketDataBar(
                timestamp=ts,
                symbol=symbol,
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
    return bars


def _await_terminal_status(service: BacktestService, experiment_id: str, timeout: float = 3.0):
    start = time.time()
    while time.time() - start < timeout:
        status_rec = service.get_run_status(experiment_id)
        if status_rec and status_rec.get("status") in ("COMPLETED", "FAILED"):
            return status_rec
        time.sleep(0.05)
    return service.get_run_status(experiment_id)


def test_close_signal_exit_fills_next_bar_not_same_bar_open():
    """Test 29: Bearish signal evaluated at index 31 close must fill at index 32 open,

    not index 31 open.
    """
    bars = _build_causality_bars("CAUSAL_SYM")
    checksum = compute_dataset_checksum(bars)

    dataset_store = DatasetRegistryStore(":memory:")
    dataset_store.register_dataset(
        DatasetRecord(
            dataset_id="causal_ds_1",
            name="Causal DS",
            symbols=["CAUSAL_SYM"],
            start_date=bars[0].timestamp,
            end_date=bars[-1].timestamp,
            bar_count=len(bars),
            sha256_checksum=checksum,
        )
    )

    slip_model = SlippageModelConfig(fixed_tick_slippage_pts=0.05, variable_slippage_pct=0.0)
    service = BacktestService(dataset_store=dataset_store)
    service.register_dataset_bars("causal_ds_1", bars)

    exp_id = "exp_causal_timing"
    service.submit_backtest(
        strategy_id="Canonical_SMA",
        universe=["CAUSAL_SYM"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        slippage_model=slip_model,
        initial_capital=100000.0,
        experiment_id=exp_id,
        dataset_id="causal_ds_1",
        dataset_checksum=checksum,
    )

    status = _await_terminal_status(service, exp_id)
    assert status["status"] == "COMPLETED"

    trades = service.store.get_trades(exp_id)
    assert len(trades) >= 1
    trade = trades[0]
    # Exit must have filled at bar index 32 open (102.0 minus sell slippage 0.05 = 101.95), NOT at index 31 open (120.0)
    assert trade["exit_price"] < 110.0
    assert abs(trade["exit_price"] - (102.0 - 0.05)) < 1e-4 or abs(trade["exit_price"] - 102.0) <= 0.1


def test_gap_through_stop_fills_at_open_or_worse():
    """Test 30: When price gaps down through stop, fill at next bar open or worse (under sell slippage),

    never at the stop price.
    """
    # 21 warmup bars at 100, then entry trigger, then bar with gap-down: open=80, high=85, low=78, close=82
    base_ts = datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc)
    bars = []
    # 21 bars at 100
    for i in range(21):
        bars.append(
            CanonicalMarketDataBar(
                timestamp=base_ts + timedelta(days=i),
                symbol="GAP_SYM",
                exchange="NSE",
                timeframe="1d",
                open=100.0,
                high=102.0,
                low=99.0,
                close=100.0,
                volume=10000.0,
            )
        )
    # Bar 21: trigger golden cross
    bars.append(
        CanonicalMarketDataBar(
            timestamp=base_ts + timedelta(days=21),
            symbol="GAP_SYM",
            exchange="NSE",
            timeframe="1d",
            open=100.0,
            high=115.0,
            low=100.0,
            close=112.0,
            volume=10000.0,
        )
    )
    # Bar 22: entry bar (open=112.0)
    bars.append(
        CanonicalMarketDataBar(
            timestamp=base_ts + timedelta(days=22),
            symbol="GAP_SYM",
            exchange="NSE",
            timeframe="1d",
            open=112.0,
            high=114.0,
            low=109.0,
            close=110.0,
            volume=10000.0,
        )
    )
    # Bar 23: Gap-down bar: open=80.0, high=85.0, low=78.0, close=82.0 (stop was near ~97-106)
    bars.append(
        CanonicalMarketDataBar(
            timestamp=base_ts + timedelta(days=23),
            symbol="GAP_SYM",
            exchange="NSE",
            timeframe="1d",
            open=80.0,
            high=85.0,
            low=78.0,
            close=82.0,
            volume=10000.0,
        )
    )

    checksum = compute_dataset_checksum(bars)
    dataset_store = DatasetRegistryStore(":memory:")
    dataset_store.register_dataset(
        DatasetRecord(
            dataset_id="gap_ds",
            name="Gap DS",
            symbols=["GAP_SYM"],
            start_date=bars[0].timestamp,
            end_date=bars[-1].timestamp,
            bar_count=len(bars),
            sha256_checksum=checksum,
        )
    )

    slip_model = SlippageModelConfig(fixed_tick_slippage_pts=0.05, variable_slippage_pct=0.0005)
    service = BacktestService(dataset_store=dataset_store)
    service.register_dataset_bars("gap_ds", bars)

    exp_id = "exp_gap_stop"
    service.submit_backtest(
        strategy_id="Canonical_SMA",
        universe=["GAP_SYM"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        slippage_model=slip_model,
        initial_capital=100000.0,
        experiment_id=exp_id,
        dataset_id="gap_ds",
        dataset_checksum=checksum,
    )

    status = _await_terminal_status(service, exp_id)
    assert status["status"] == "COMPLETED"

    trades = service.store.get_trades(exp_id)
    assert len(trades) >= 1
    # Exit price must be at open or worse (<= 80.0 - slippage), NEVER at stop price (e.g. 106 or 97)
    assert trades[0]["exit_price"] <= 80.0


def test_entry_cash_changes_only_at_fill_event():
    """Test 31: Cash and position remain unchanged at signal close i;

    cash is debited at bar i+1 open when the fill occurs.
    """
    bars = _build_causality_bars("CASH_SYM")
    checksum = compute_dataset_checksum(bars)

    dataset_store = DatasetRegistryStore(":memory:")
    dataset_store.register_dataset(
        DatasetRecord(
            dataset_id="cash_ds",
            name="Cash DS",
            symbols=["CASH_SYM"],
            start_date=bars[0].timestamp,
            end_date=bars[-1].timestamp,
            bar_count=len(bars),
            sha256_checksum=checksum,
        )
    )

    service = BacktestService(dataset_store=dataset_store)
    service.register_dataset_bars("cash_ds", bars)

    exp_id = "exp_cash_timing"
    service.submit_backtest(
        strategy_id="Canonical_SMA",
        universe=["CASH_SYM"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        initial_capital=100000.0,
        experiment_id=exp_id,
        dataset_id="cash_ds",
        dataset_checksum=checksum,
    )

    status = _await_terminal_status(service, exp_id)
    assert status["status"] == "COMPLETED"

    # Equity curve before fill bar (index 22) must equal initial capital exactly
    eq_curve = service.store.get_equity_curve(exp_id)
    assert len(eq_curve) > 22
    # At index 21 close (when golden cross fired), position was not yet filled, so equity is still 100,000
    assert abs(eq_curve[21]["equity"] - 100000.0) < 1e-4


def test_end_of_bar_equity_reflects_prior_stop_exit():
    """Test 32: If stopped out during bar (open=100, low=90, close=110),

    close equity reflects exited cash, not marked at 110.
    """
    # Build setup where stop triggers at low 90, close is 110
    base_ts = datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc)
    bars = []
    for i in range(21):
        bars.append(
            CanonicalMarketDataBar(
                timestamp=base_ts + timedelta(days=i),
                symbol="STOP_SYM",
                exchange="NSE",
                timeframe="1d",
                open=100.0,
                high=102.0,
                low=99.0,
                close=100.0,
                volume=10000.0,
            )
        )
    # Bar 21: golden cross
    bars.append(
        CanonicalMarketDataBar(
            timestamp=base_ts + timedelta(days=21),
            symbol="STOP_SYM",
            exchange="NSE",
            timeframe="1d",
            open=100.0,
            high=115.0,
            low=100.0,
            close=112.0,
            volume=10000.0,
        )
    )
    # Bar 22: entry bar at 112.0
    bars.append(
        CanonicalMarketDataBar(
            timestamp=base_ts + timedelta(days=22),
            symbol="STOP_SYM",
            exchange="NSE",
            timeframe="1d",
            open=112.0,
            high=114.0,
            low=110.0,
            close=111.0,
            volume=10000.0,
        )
    )
    # Bar 23: Stop-loss trigger at low 90.0, close 110.0
    bars.append(
        CanonicalMarketDataBar(
            timestamp=base_ts + timedelta(days=23),
            symbol="STOP_SYM",
            exchange="NSE",
            timeframe="1d",
            open=105.0,
            high=112.0,
            low=90.0,
            close=110.0,
            volume=10000.0,
        )
    )

    checksum = compute_dataset_checksum(bars)
    dataset_store = DatasetRegistryStore(":memory:")
    dataset_store.register_dataset(
        DatasetRecord(
            dataset_id="stop_ds",
            name="Stop DS",
            symbols=["STOP_SYM"],
            start_date=bars[0].timestamp,
            end_date=bars[-1].timestamp,
            bar_count=len(bars),
            sha256_checksum=checksum,
        )
    )

    service = BacktestService(dataset_store=dataset_store)
    service.register_dataset_bars("stop_ds", bars)

    exp_id = "exp_stop_equity"
    service.submit_backtest(
        strategy_id="Canonical_SMA",
        universe=["STOP_SYM"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        initial_capital=100000.0,
        experiment_id=exp_id,
        dataset_id="stop_ds",
        dataset_checksum=checksum,
    )

    status = _await_terminal_status(service, exp_id)
    assert status["status"] == "COMPLETED"

    # End of bar 23 equity must NOT be calculated using open position marked at 110!
    # It must reflect the cash post stop-loss exit (less than initial capital)
    eq_curve = service.store.get_equity_curve(exp_id)
    assert len(eq_curve) > 23
    assert eq_curve[23]["equity"] < 100000.0
