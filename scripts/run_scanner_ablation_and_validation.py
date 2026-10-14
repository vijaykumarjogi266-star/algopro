#!/usr/bin/env python3
"""
Scientific Scanner Ablation Study & Out-of-Sample Validation Engine.
Evaluates candidate filters individually and in combination:
1. RVOL >= 2.0 (Volume Expansion)
2. Higher Timeframe Daily Trend Confluence (Daily Close > 20 EMA)
3. Minimum 1:2 Risk-to-Reward Feasibility (Target >= 2.0 * Risk)
4. Time Window Optimization (09:45 - 11:30 IST)
5. Daily Trade Limit Circuit Breaker (Max 2 trades/day)
6. Trailing Stop Loss to Breakeven at +1R

Chronological Partitions:
- In-Sample (Development): 2026-07-16 to 2026-09-08 (~40 trading days)
- Out-of-Sample (Validation): 2026-09-09 to 2026-10-09 (~20 trading days)
"""

import sys
import os
import json
from pathlib import Path
from datetime import datetime, date, time
import pandas as pd
import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from services.backtest_engine.hardened_intraday_engine import (
    HardenedIntradaySimulator,
    FilterConfig,
)
from scripts.run_baseline_backtest import calculate_daily_pivots
from services.scanner.universe_manager import Nifty50UniverseManager

CACHE_INTRADAY = BASE_DIR / "data" / "cache_intraday_5m"
CACHE_DAILY = BASE_DIR / "data" / "cache"
ARTIFACTS_DIR = BASE_DIR / "artifacts"
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)


def load_universe_data():
    symbols = sorted(Nifty50UniverseManager().get_symbols())
    symbol_5m: dict[str, pd.DataFrame] = {}
    daily_trends: dict[str, dict[date, bool]] = {}

    print(f"Loading data for {len(symbols)} symbols...")
    for sym in symbols:
        # Load 5m data
        f_5m = CACHE_INTRADAY / f"{sym}_5m.parquet"
        if f_5m.exists():
            df = pd.read_parquet(f_5m)
            df['Datetime'] = pd.to_datetime(df['Datetime'])
            df = df.sort_values('Datetime').reset_index(drop=True)
            df = calculate_daily_pivots(df)
            df['Vol_SMA_20'] = df['Volume'].rolling(window=20).mean()
            symbol_5m[sym] = df

        # Load daily data for 20 EMA trend calculation
        f_daily = CACHE_DAILY / f"{sym}_NS_5y_1d.parquet"
        daily_trends[sym] = {}
        if f_daily.exists() and sym in symbol_5m:
            df_d = pd.read_parquet(f_daily)
            df_d.columns = [c.lower() for c in df_d.columns]
            df_d['d_date'] = pd.to_datetime(df_d['date']).dt.date
            df_d = df_d[['d_date', 'close']].drop_duplicates('d_date')
            
            # Append any newer daily closes from 5m data
            df_5m = symbol_5m[sym]
            df_5m['d_date'] = pd.to_datetime(df_5m['Datetime']).dt.date
            daily_recent = df_5m.groupby('d_date')['Close'].last().reset_index()
            daily_recent.rename(columns={'Close': 'close'}, inplace=True)
            
            # Merge and sort
            combined = pd.concat([df_d[df_d['d_date'] < daily_recent['d_date'].min()], daily_recent], ignore_index=True)
            combined = combined.sort_values('d_date').reset_index(drop=True)
            combined['ema_20'] = combined['close'].ewm(span=20, adjust=False).mean()
            # Prior day close > prior day EMA 20 (point-in-time)
            combined['is_uptrend'] = combined['close'].shift(1) > combined['ema_20'].shift(1)
            for _, r in combined.iterrows():
                daily_trends[sym][r['d_date']] = bool(r['is_uptrend'])

    print(f"Loaded {len(symbol_5m)} symbols with 5m data.")
    return symbol_5m, daily_trends


def run_ablation_and_validation():
    symbol_5m, daily_trends = load_universe_data()

    in_sample_start = date(2026, 7, 16)
    in_sample_end = date(2026, 9, 8)
    oos_start = date(2026, 9, 9)
    oos_end = date(2026, 10, 9)

    # Define Configurations
    configurations = [
        # 1. Hardened Baseline (No filters, just point-in-time execution & slippage)
        FilterConfig(
            name="1_Hardened_Baseline",
            min_rvol=1.5,
            require_daily_trend=False,
            min_risk_reward=0.0,
            allowed_entry_start=time(9, 45),
            allowed_entry_end=time(13, 30),
            max_trades_per_day=999,
            use_trailing_breakeven=False
        ),
        # 2. Filter 1: RVOL >= 2.0 (Volume Expansion)
        FilterConfig(
            name="2_Filter_RVOL_2.0",
            min_rvol=2.0,
            require_daily_trend=False,
            min_risk_reward=0.0,
            allowed_entry_start=time(9, 45),
            allowed_entry_end=time(13, 30),
            max_trades_per_day=999,
            use_trailing_breakeven=False
        ),
        # 3. Filter 2: Daily Trend Confluence (Daily Close > 20 EMA)
        FilterConfig(
            name="3_Filter_Daily_Trend",
            min_rvol=1.5,
            require_daily_trend=True,
            min_risk_reward=0.0,
            allowed_entry_start=time(9, 45),
            allowed_entry_end=time(13, 30),
            max_trades_per_day=999,
            use_trailing_breakeven=False
        ),
        # 4. Filter 3: Minimum 1:2 R:R Ratio
        FilterConfig(
            name="4_Filter_Min_RR_2.0",
            min_rvol=1.5,
            require_daily_trend=False,
            min_risk_reward=2.0,
            allowed_entry_start=time(9, 45),
            allowed_entry_end=time(13, 30),
            max_trades_per_day=999,
            use_trailing_breakeven=False
        ),
        # 5. Filter 4: High-Probability Time Window (09:45 - 11:30 IST)
        FilterConfig(
            name="5_Filter_Time_0945_1130",
            min_rvol=1.5,
            require_daily_trend=False,
            min_risk_reward=0.0,
            allowed_entry_start=time(9, 45),
            allowed_entry_end=time(11, 30),
            max_trades_per_day=999,
            use_trailing_breakeven=False
        ),
        # 6. Filter 5: Max 2 Trades / Day Circuit Breaker
        FilterConfig(
            name="6_Filter_Max_2_Trades_Day",
            min_rvol=1.5,
            require_daily_trend=False,
            min_risk_reward=0.0,
            allowed_entry_start=time(9, 45),
            allowed_entry_end=time(13, 30),
            max_trades_per_day=2,
            use_trailing_breakeven=False
        ),
        # 7. Combined Improved System (Vikram Prabhu Best-Practice Rule Pack)
        FilterConfig(
            name="7_Combined_Vikram_Prabhu_System",
            min_rvol=2.0,
            require_daily_trend=True,
            min_risk_reward=2.0,
            allowed_entry_start=time(9, 45),
            allowed_entry_end=time(11, 30),
            max_trades_per_day=2,
            use_trailing_breakeven=True
        ),
    ]

    all_results = []
    improved_trades_log = []

    print("\n" + "=" * 90)
    print("🔬 RUNNING SCIENTIFIC FILTER ABLATION & OUT-OF-SAMPLE VALIDATION")
    print("=" * 90)

    for cfg in configurations:
        print(f"\nEvaluating: {cfg.name}...")
        sim = HardenedIntradaySimulator(
            symbol_data=symbol_5m,
            daily_trends=daily_trends,
            initial_capital=100000.0,
            risk_per_trade_pct=0.010,
            filter_config=cfg
        )

        # In-Sample Run
        trades_is, sum_is = sim.run(start_date=in_sample_start, end_date=in_sample_end)
        # Out-of-Sample Run
        trades_oos, sum_oos = sim.run(start_date=oos_start, end_date=oos_end)
        # Full Horizon Run
        trades_full, sum_full = sim.run()

        if cfg.name == "7_Combined_Vikram_Prabhu_System":
            improved_trades_log = [t.__dict__ for t in trades_full]

        record = {
            "config": cfg.name,
            # In-Sample
            "is_trades": sum_is["total_trades"],
            "is_win_rate": sum_is["win_rate_pct"],
            "is_gross_pnl": sum_is["gross_pnl"],
            "is_friction": sum_is["total_friction"],
            "is_net_pnl": sum_is["net_pnl"],
            "is_pf": sum_is["profit_factor"],
            "is_max_dd": sum_is["max_drawdown"],
            # Out-of-Sample
            "oos_trades": sum_oos["total_trades"],
            "oos_win_rate": sum_oos["win_rate_pct"],
            "oos_gross_pnl": sum_oos["gross_pnl"],
            "oos_friction": sum_oos["total_friction"],
            "oos_net_pnl": sum_oos["net_pnl"],
            "oos_pf": sum_oos["profit_factor"],
            "oos_max_dd": sum_oos["max_drawdown"],
            # Full Horizon
            "full_trades": sum_full["total_trades"],
            "full_win_rate": sum_full["win_rate_pct"],
            "full_gross_pnl": sum_full["gross_pnl"],
            "full_friction": sum_full["total_friction"],
            "full_net_pnl": sum_full["net_pnl"],
            "full_pf": sum_full["profit_factor"],
            "full_max_dd": sum_full["max_drawdown"],
            "full_max_dd_pct": sum_full["max_drawdown_pct"],
            "full_expectancy": sum_full["expectancy"],
        }
        all_results.append(record)

        print(f"  [In-Sample]  Trades: {sum_is['total_trades']:4d} | Win: {sum_is['win_rate_pct']:5.1f}% | Net: ₹{sum_is['net_pnl']:9.2f} | PF: {sum_is['profit_factor']:.2f}")
        print(f"  [Out-Sample] Trades: {sum_oos['total_trades']:4d} | Win: {sum_oos['win_rate_pct']:5.1f}% | Net: ₹{sum_oos['net_pnl']:9.2f} | PF: {sum_oos['profit_factor']:.2f}")
        print(f"  [Full]       Trades: {sum_full['total_trades']:4d} | Win: {sum_full['win_rate_pct']:5.1f}% | Net: ₹{sum_full['net_pnl']:9.2f} | PF: {sum_full['profit_factor']:.2f} | DD: ₹{sum_full['max_drawdown']:,.2f}")

    df_results = pd.DataFrame(all_results)
    df_results.to_csv(ARTIFACTS_DIR / "scanner_ablation_results.csv", index=False)
    with open(ARTIFACTS_DIR / "scanner_ablation_results.json", "w") as f:
        json.dump(all_results, f, indent=2)

    # Save Improved Trade Logs
    df_improved = pd.DataFrame(improved_trades_log)
    df_improved.to_csv(ARTIFACTS_DIR / "improved_trades.csv", index=False)
    with open(ARTIFACTS_DIR / "improved_trades.json", "w") as f:
        json.dump(improved_trades_log, f, indent=2, default=str)

    print("\n" + "=" * 90)
    print("✅ ABLATION STUDY COMPLETE. SAVED TO artifacts/scanner_ablation_results.csv")
    print("=" * 90)

    return df_results


if __name__ == "__main__":
    run_ablation_and_validation()
