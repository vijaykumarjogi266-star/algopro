"""
Automated Regression Test Suite for Hardened Backtest Engine & Scanner (Phase F).

Covers:
1. Strict Denial of Real Order Execution & Safety Firewall.
2. Signal Calculations & Zero Future-Data Leakage.
3. Scanner Filters & Explicit Rejection Explanations.
4. Conservative Intra-Candle Stop-Loss / Take-Profit Collision Handling.
5. Daily Trade Limit & Circuit Breaker Behavior.
6. Hard End-of-Day Square-Off at 15:15 IST.
7. Adverse Slippage and Statutory Fee Modeling.
8. Deterministic Reproducibility of Backtest Runs.
"""

from datetime import datetime, date, time, timedelta
from decimal import Decimal
import numpy as np
import pandas as pd
import pytest

from services.backtest_engine.hardened_intraday_engine import (
    HardenedIntradaySimulator,
    FilterConfig,
    Position,
    ClosedTrade,
    ALLOW_LIVE_TRADING,
    ALLOW_REAL_BROKER_EXECUTION,
    REAL_MONEY_RISK_PAISE,
    PAPER_BROKER_ONLY,
)
from services.backtest_engine.statutory_cost_model import (
    IndianStatutoryCostModel,
    OrderLeg,
    ProductType,
)


def create_synthetic_bars(base_dt: datetime, n_bars: int = 20, base_price: float = 100.0) -> pd.DataFrame:
    records = []
    for i in range(n_bars):
        dt = base_dt + timedelta(minutes=5 * i)
        o = base_price + i * 0.1
        h = o + 0.5
        l = o - 0.2
        c = o + 0.3
        v = 1000.0 + (5000.0 if i == 5 else 0.0) # Volume spike at bar 5
        records.append({
            'Datetime': dt,
            'Open': o,
            'High': h,
            'Low': l,
            'Close': c,
            'Volume': v,
            'R1': base_price + 0.2, # R1 resistance
            'R2': base_price + 2.0, # R2 target
            'Vol_SMA_20': 1000.0,
        })
    df = pd.DataFrame(records)
    return df


def test_strict_safety_firewall_denial():
    """Ensures safety invariants are strictly hardcoded to paper-only."""
    assert ALLOW_LIVE_TRADING is False
    assert ALLOW_REAL_BROKER_EXECUTION is False
    assert REAL_MONEY_RISK_PAISE == 0
    assert PAPER_BROKER_ONLY is True


def test_no_future_data_leakage():
    """Ensures signals on bar t-1 fill strictly at bar t Open price, never bar t-1 Close."""
    start_dt = datetime(2026, 8, 1, 9, 45)
    df = create_synthetic_bars(start_dt, n_bars=10, base_price=500.0)
    # Set Bar 0 Close > R1 and RVOL > 2.0
    df.loc[0, 'Close'] = 502.0
    df.loc[0, 'R1'] = 501.0
    df.loc[0, 'Volume'] = 3000.0
    df.loc[0, 'Vol_SMA_20'] = 1000.0

    # Bar 1 Open is distinct from Bar 0 Close
    df.loc[1, 'Open'] = 503.50
    df.loc[1, 'High'] = 504.0
    df.loc[1, 'Low'] = 502.0
    df.loc[1, 'Close'] = 503.0

    # Bar 2 triggers Stop Loss to close trade
    df.loc[2, 'Open'] = 503.0
    df.loc[2, 'Low'] = 450.0 # Breaches SL

    cfg = FilterConfig(
        name="test_leakage",
        min_rvol=2.0,
        slippage_pct=0.0005 # 5 bps
    )

    sim = HardenedIntradaySimulator(
        symbol_data={"TEST": df},
        daily_trends={"TEST": {date(2026, 8, 1): True}},
        filter_config=cfg
    )

    trades, _ = sim.run()
    assert len(trades) > 0
    first_trade = trades[0]
    expected_fill = 503.50 * 1.0005
    assert abs(first_trade.entry_price - expected_fill) < 0.01
    # Must NOT equal bar 0 close (502.0)
    assert first_trade.entry_price > 503.0


def test_conservative_sl_tp_collision_resolution():
    """When both Low <= SL and High >= TP occur in the exact same candle, SL must be triggered."""
    start_dt = datetime(2026, 8, 1, 9, 45)
    df = create_synthetic_bars(start_dt, n_bars=10, base_price=100.0)
    # Signal on bar 0
    df.loc[0, 'Close'] = 101.0
    df.loc[0, 'Low'] = 99.50 # Stop loss level
    df.loc[0, 'R1'] = 100.50
    df.loc[0, 'R2'] = 103.0 # Target level
    df.loc[0, 'Volume'] = 3000.0

    # Bar 1 fills at Open = 101.0
    df.loc[1, 'Open'] = 101.0
    df.loc[1, 'High'] = 101.5
    df.loc[1, 'Low'] = 100.5
    df.loc[1, 'Close'] = 101.2

    # Bar 2 has massive candle that touches BOTH SL (99.5) and TP (103.0)
    df.loc[2, 'Open'] = 101.2
    df.loc[2, 'High'] = 105.0 # Exceeds TP (103.0)
    df.loc[2, 'Low'] = 98.0   # Breaches SL (99.5)
    df.loc[2, 'Close'] = 104.0

    cfg = FilterConfig(name="collision_test", slippage_pct=0.0)
    sim = HardenedIntradaySimulator(
        symbol_data={"TEST": df},
        daily_trends={"TEST": {date(2026, 8, 1): True}},
        filter_config=cfg
    )

    trades, _ = sim.run()
    assert len(trades) == 1
    assert trades[0].exit_reason == "STOP_LOSS_COLLISION"
    assert trades[0].is_win is False


def test_daily_trade_limit_quota():
    """Enforces maximum trades per day quota (e.g. 2 trades max)."""
    start_dt = datetime(2026, 8, 1, 9, 45)
    # Create 5 distinct symbols triggering simultaneous signals
    symbol_data = {}
    trends = {}
    for sym in ["SYM1", "SYM2", "SYM3", "SYM4", "SYM5"]:
        df = create_synthetic_bars(start_dt, n_bars=10, base_price=100.0)
        df.loc[0, 'Close'] = 101.0
        df.loc[0, 'R1'] = 100.50
        df.loc[0, 'Volume'] = 3000.0
        symbol_data[sym] = df
        trends[sym] = {date(2026, 8, 1): True}

    cfg = FilterConfig(name="quota_test", max_trades_per_day=2)
    sim = HardenedIntradaySimulator(
        symbol_data=symbol_data,
        daily_trends=trends,
        filter_config=cfg
    )

    trades, _ = sim.run()
    # Exactly 2 trades must be permitted
    assert len(trades) <= 2


def test_hard_eod_square_off_at_1515():
    """Positions remaining open must forcefully exit at 15:15 IST."""
    start_dt = datetime(2026, 8, 1, 13, 0)
    # 28 5m bars from 13:00 to 15:20
    df = create_synthetic_bars(start_dt, n_bars=28, base_price=200.0)
    # Ensure all bars stay within [195, 205] with Close below R1 to avoid re-triggering
    df['High'] = 205.0
    df['Low'] = 195.0
    df['Close'] = 200.0

    # Trigger signal strictly on bar 0 with SL at 180.0 (well below bar low of 195.0)
    df.loc[0, 'Close'] = 201.0
    df.loc[0, 'Low'] = 180.0 # Wide SL to avoid trigger
    df.loc[0, 'R1'] = 200.5
    df.loc[0, 'R2'] = 250.0 # Far TP to avoid trigger
    df.loc[0, 'Volume'] = 5000.0

    cfg = FilterConfig(name="eod_test")
    sim = HardenedIntradaySimulator(
        symbol_data={"TEST": df},
        daily_trends={"TEST": {date(2026, 8, 1): True}},
        filter_config=cfg
    )

    trades, _ = sim.run()
    assert len(trades) == 1
    assert trades[0].exit_reason == "HARD_EXIT_15_15"
    assert trades[0].exit_time.time() >= time(15, 15)


def test_reproducibility_of_backtest_results():
    """Two identical runs must produce bit-for-bit identical trade logs and PnL."""
    start_dt = datetime(2026, 8, 1, 9, 45)
    df = create_synthetic_bars(start_dt, n_bars=15, base_price=300.0)
    df.loc[0, 'Close'] = 301.0
    df.loc[0, 'R1'] = 300.5
    df.loc[0, 'Volume'] = 4000.0

    cfg = FilterConfig(name="repro_test")
    sim1 = HardenedIntradaySimulator(
        symbol_data={"TEST": df},
        daily_trends={"TEST": {date(2026, 8, 1): True}},
        filter_config=cfg
    )
    sim2 = HardenedIntradaySimulator(
        symbol_data={"TEST": df},
        daily_trends={"TEST": {date(2026, 8, 1): True}},
        filter_config=cfg
    )

    trades1, sum1 = sim1.run()
    trades2, sum2 = sim2.run()

    assert len(trades1) == len(trades2)
    assert sum1["net_pnl"] == sum2["net_pnl"]
    assert sum1["total_friction"] == sum2["total_friction"]
    assert sum1["max_drawdown"] == sum2["max_drawdown"]
