#!/usr/bin/env python3
"""
Reproducible Baseline Intraday Pivot Breakout Backtest Engine (Phase B)
Strictly Paper-Trading Simulation Only.

Safety Assertions:
ALLOW_LIVE_TRADING = False
ALLOW_REAL_BROKER_EXECUTION = False
REAL_MONEY_RISK_PAISE = 0
PAPER_BROKER_ONLY = True
"""

import sys
import os
import json
from pathlib import Path
from decimal import Decimal
from datetime import datetime, time, timedelta
import pandas as pd
import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Mandatory safety enforcement
ALLOW_LIVE_TRADING = False
ALLOW_REAL_BROKER_EXECUTION = False
REAL_MONEY_RISK_PAISE = 0
PAPER_BROKER_ONLY = True

from services.backtest_engine.statutory_cost_model import (
    IndianStatutoryCostModel,
    OrderLeg,
    ProductType,
)
from services.scanner.universe_manager import Nifty50UniverseManager

CACHE_DIR = BASE_DIR / "data" / "cache_intraday_5m"
ARTIFACTS_DIR = BASE_DIR / "artifacts"
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)


def calculate_daily_pivots(df: pd.DataFrame) -> pd.DataFrame:
    """Calculates Daily Classical Floor Pivots (P, R1, R2, S1, S2) and prior day HLC."""
    df['Date'] = pd.to_datetime(df['Datetime']).dt.date
    daily = df.groupby('Date').agg(
        day_high=('High', 'max'),
        day_low=('Low', 'min'),
        day_close=('Close', 'last')
    ).reset_index()
    
    daily['prev_high'] = daily['day_high'].shift(1)
    daily['prev_low'] = daily['day_low'].shift(1)
    daily['prev_close'] = daily['day_close'].shift(1)
    
    daily['P'] = (daily['prev_high'] + daily['prev_low'] + daily['prev_close']) / 3.0
    daily['R1'] = 2.0 * daily['P'] - daily['prev_low']
    daily['R2'] = daily['P'] + (daily['prev_high'] - daily['prev_low'])
    daily['S1'] = 2.0 * daily['P'] - daily['prev_high']
    daily['S2'] = daily['P'] - (daily['prev_high'] - daily['prev_low'])
    
    return pd.merge(
        df,
        daily[['Date', 'P', 'R1', 'R2', 'S1', 'S2', 'prev_high', 'prev_low', 'prev_close']],
        on='Date',
        how='left'
    )


def run_baseline_backtest():
    assert not ALLOW_LIVE_TRADING, "SAFETY VIOLATION: LIVE TRADING PROHIBITED"
    assert not ALLOW_REAL_BROKER_EXECUTION, "SAFETY VIOLATION: REAL BROKER PROHIBITED"
    assert REAL_MONEY_RISK_PAISE == 0, "SAFETY VIOLATION: REAL MONEY RISK PROHIBITED"
    assert PAPER_BROKER_ONLY, "SAFETY VIOLATION: MUST BE PAPER BROKER ONLY"

    universe_mgr = Nifty50UniverseManager()
    symbols = sorted(universe_mgr.get_symbols())
    
    print("=" * 80)
    print("🔬 ESTABLISHING REPRODUCIBLE BASELINE BACKTEST (MIS)")
    print("=" * 80)
    print(f"Safety Mode: Strictly Paper Trading Only (Zero Real Money Risk)")
    print(f"Universe: Nifty 50 ({len(symbols)} symbols)")
    print(f"Data Cache: {CACHE_DIR}")

    initial_capital = 100000.0
    risk_per_trade_pct = 0.010
    
    data_quality_report = {}
    scanner_rejections = []
    trades = []
    
    start_time = time(9, 45)
    end_time = time(13, 30)
    hard_exit_time = time(15, 15)
    
    for sym in symbols:
        file_path = CACHE_DIR / f"{sym}_5m.parquet"
        if not file_path.exists():
            data_quality_report[sym] = {"status": "MISSING_FILE", "bars": 0}
            continue
            
        df = pd.read_parquet(file_path)
        if df.empty or len(df) < 50:
            data_quality_report[sym] = {"status": "INSUFFICIENT_BARS", "bars": len(df)}
            continue
            
        df['Datetime'] = pd.to_datetime(df['Datetime'])
        df = df.sort_values('Datetime').reset_index(drop=True)
        
        # Missing data & quality audit
        zero_vol_bars = int((df['Volume'] == 0).sum())
        nan_bars = int(df[['Open', 'High', 'Low', 'Close']].isna().sum().sum())
        data_quality_report[sym] = {
            "status": "VALID",
            "total_bars": len(df),
            "zero_volume_bars": zero_vol_bars,
            "nan_price_bars": nan_bars,
            "start": str(df['Datetime'].iloc[0]),
            "end": str(df['Datetime'].iloc[-1]),
        }
        
        df = calculate_daily_pivots(df)
        df['Vol_SMA_20'] = df['Volume'].rolling(window=20).mean()
        df['time_obj'] = df['Datetime'].dt.time
        
        in_position = False
        entry_price = 0.0
        sl_price = 0.0
        tp_price = 0.0
        entry_qty = 0
        entry_time = None
        entry_friction_val = 0.0
        entry_bar_idx = 0
        
        for idx in range(len(df)):
            row = df.iloc[idx]
            t = row['time_obj']
            close = float(row['Close'])
            high = float(row['High'])
            low = float(row['Low'])
            open_p = float(row['Open'])
            vol = float(row['Volume'])
            r1 = float(row['R1']) if not pd.isna(row['R1']) else np.nan
            r2 = float(row['R2']) if not pd.isna(row['R2']) else np.nan
            vol_sma = float(row['Vol_SMA_20']) if not pd.isna(row['Vol_SMA_20']) else np.nan
            
            if np.isnan(r1) or np.isnan(vol_sma) or vol_sma == 0:
                continue
                
            if not in_position:
                if start_time <= t <= end_time:
                    # Baseline condition: Close > R1 and Volume > 1.5 * Vol_SMA_20
                    is_breakout = (close > r1)
                    has_volume = (vol > 1.5 * vol_sma)
                    
                    if not is_breakout or not has_volume:
                        # Log scanner rejection reason periodically or on test candidate
                        if is_breakout and not has_volume:
                            scanner_rejections.append({
                                "symbol": sym,
                                "timestamp": str(row['Datetime']),
                                "reason": "PRICE_BREAKOUT_WITHOUT_VOLUME_EXPANSION",
                                "r1": r1,
                                "close": close,
                                "vol": vol,
                                "vol_sma": vol_sma
                            })
                        elif has_volume and not is_breakout:
                            scanner_rejections.append({
                                "symbol": sym,
                                "timestamp": str(row['Datetime']),
                                "reason": "VOLUME_SPIKE_BELOW_R1_RESISTANCE",
                                "r1": r1,
                                "close": close,
                                "vol": vol,
                                "vol_sma": vol_sma
                            })
                        continue
                    
                    # Entry execution (baseline used bar Close)
                    entry_price = close
                    sl_price = low
                    tp_price = r2
                    
                    if sl_price >= entry_price:
                        sl_price = entry_price * 0.99
                    if tp_price <= entry_price:
                        tp_price = entry_price * 1.01
                        
                    risk_amt = initial_capital * risk_per_trade_pct
                    stop_dist = entry_price - sl_price
                    qty = int(risk_amt / stop_dist) if stop_dist > 0 else 1
                    max_qty = int(45000 / entry_price)
                    entry_qty = max(1, min(qty, max_qty))
                    
                    entry_fric = IndianStatutoryCostModel.calculate_order_friction(
                        leg=OrderLeg.BUY,
                        price=Decimal(str(round(entry_price, 2))),
                        quantity=entry_qty,
                        product=ProductType.INTRADAY
                    )
                    
                    entry_friction_val = float(entry_fric.all_in_total_friction)
                    entry_time = row['Datetime']
                    entry_bar_idx = idx
                    in_position = True
                    
            else:
                # Do not exit on the same bar as entry in baseline
                if idx == entry_bar_idx:
                    continue
                    
                exit_reason = None
                exit_price = 0.0
                
                # Check Hard Exit at 15:15 IST
                if t >= hard_exit_time:
                    exit_reason = "HARD_EXIT_15_15"
                    exit_price = close
                elif high >= tp_price:
                    exit_reason = "TAKE_PROFIT"
                    exit_price = tp_price
                elif low <= sl_price:
                    exit_reason = "STOP_LOSS"
                    exit_price = sl_price
                    
                if exit_reason:
                    exit_fric = IndianStatutoryCostModel.calculate_order_friction(
                        leg=OrderLeg.SELL,
                        price=Decimal(str(round(exit_price, 2))),
                        quantity=entry_qty,
                        product=ProductType.INTRADAY
                    )
                    exit_friction_val = float(exit_fric.all_in_total_friction)
                    total_friction = entry_friction_val + exit_friction_val
                    
                    gross_pnl = (exit_price - entry_price) * entry_qty
                    net_pnl = gross_pnl - total_friction
                    holding_mins = (row['Datetime'] - entry_time).total_seconds() / 60.0
                    
                    trades.append({
                        "symbol": sym,
                        "date": str(entry_time.date()),
                        "day_of_week": entry_time.strftime("%A"),
                        "entry_time": str(entry_time),
                        "exit_time": str(row['Datetime']),
                        "time_of_day_bucket": (
                            "09:45-10:30" if entry_time.time() < time(10, 30) else
                            "10:30-11:30" if entry_time.time() < time(11, 30) else
                            "11:30-12:30" if entry_time.time() < time(12, 30) else
                            "12:30-13:30"
                        ),
                        "entry_price": round(entry_price, 2),
                        "exit_price": round(exit_price, 2),
                        "stop_loss": round(sl_price, 2),
                        "target": round(tp_price, 2),
                        "qty": entry_qty,
                        "holding_minutes": holding_mins,
                        "exit_reason": exit_reason,
                        "gross_pnl": round(gross_pnl, 2),
                        "friction": round(total_friction, 2),
                        "net_pnl": round(net_pnl, 2),
                        "return_pct": round((exit_price - entry_price) / entry_price * 100, 3),
                    })
                    
                    in_position = False

    # Analysis & Reporting
    total_trades = len(trades)
    df_trades = pd.DataFrame(trades)
    
    if total_trades > 0:
        winning_trades = df_trades[df_trades['net_pnl'] > 0]
        losing_trades = df_trades[df_trades['net_pnl'] <= 0]
        
        win_rate = (len(winning_trades) / total_trades) * 100.0
        gross_pnl = df_trades['gross_pnl'].sum()
        total_friction = df_trades['friction'].sum()
        net_pnl = df_trades['net_pnl'].sum()
        
        gross_wins = winning_trades['gross_pnl'].sum()
        gross_losses = abs(losing_trades['gross_pnl'].sum())
        profit_factor = round(gross_wins / gross_losses, 3) if gross_losses > 0 else 0.0
        
        avg_trade_pnl = round(net_pnl / total_trades, 2)
        avg_win = round(winning_trades['net_pnl'].mean(), 2) if len(winning_trades) > 0 else 0.0
        avg_loss = round(losing_trades['net_pnl'].mean(), 2) if len(losing_trades) > 0 else 0.0
        
        # Max Drawdown calculation
        df_trades['cum_net_pnl'] = df_trades['net_pnl'].cumsum()
        df_trades['peak'] = df_trades['cum_net_pnl'].cummax()
        df_trades['drawdown'] = df_trades['cum_net_pnl'] - df_trades['peak']
        max_drawdown = round(abs(df_trades['drawdown'].min()), 2)
        max_dd_pct = round((max_drawdown / initial_capital) * 100, 2)
        
        avg_holding_time = round(df_trades['holding_minutes'].mean(), 1)
        
        # Symbol breakdown
        sym_perf = df_trades.groupby('symbol').agg(
            trades=('net_pnl', 'count'),
            win_rate=('net_pnl', lambda x: round((x > 0).mean() * 100, 1)),
            net_pnl=('net_pnl', 'sum'),
            total_friction=('friction', 'sum')
        ).reset_index().sort_values('net_pnl', ascending=False)
        
        # Day of week breakdown
        dow_perf = df_trades.groupby('day_of_week').agg(
            trades=('net_pnl', 'count'),
            win_rate=('net_pnl', lambda x: round((x > 0).mean() * 100, 1)),
            net_pnl=('net_pnl', 'sum')
        ).reindex(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]).fillna(0).reset_index()
        
        # Time of day breakdown
        tod_perf = df_trades.groupby('time_of_day_bucket').agg(
            trades=('net_pnl', 'count'),
            win_rate=('net_pnl', lambda x: round((x > 0).mean() * 100, 1)),
            net_pnl=('net_pnl', 'sum')
        ).reset_index()
        
        metrics = {
            "initial_capital": initial_capital,
            "total_trades": total_trades,
            "wins": len(winning_trades),
            "losses": len(losing_trades),
            "win_rate_pct": round(win_rate, 2),
            "gross_pnl": round(gross_pnl, 2),
            "total_friction": round(total_friction, 2),
            "net_pnl": round(net_pnl, 2),
            "total_return_pct": round((net_pnl / initial_capital) * 100, 2),
            "profit_factor": profit_factor,
            "net_expectancy_per_trade": avg_trade_pnl,
            "average_win": avg_win,
            "average_loss": avg_loss,
            "win_loss_ratio": round(abs(avg_win / avg_loss), 2) if avg_loss != 0 else 0,
            "max_drawdown_inr": max_drawdown,
            "max_drawdown_pct": max_dd_pct,
            "avg_holding_minutes": avg_holding_time,
            "symbol_count_scanned": len(symbols),
        }
    else:
        metrics = {"total_trades": 0, "net_pnl": 0.0}
        sym_perf = pd.DataFrame()
        dow_perf = pd.DataFrame()
        tod_perf = pd.DataFrame()

    # Save machine-readable outputs
    with open(ARTIFACTS_DIR / "baseline_metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)
        
    df_trades.to_csv(ARTIFACTS_DIR / "baseline_trades.csv", index=False)
    with open(ARTIFACTS_DIR / "baseline_trades.json", "w") as f:
        json.dump(trades, f, indent=2)
        
    with open(ARTIFACTS_DIR / "baseline_scanner_rejections.json", "w") as f:
        # Sample top 1000 rejections to keep size reasonable
        json.dump(scanner_rejections[:1000], f, indent=2)

    with open(ARTIFACTS_DIR / "data_quality_report.json", "w") as f:
        json.dump(data_quality_report, f, indent=2)

    print("\n" + "=" * 80)
    print("📊 BASELINE PERFORMANCE SUMMARY")
    print("=" * 80)
    print(f"Total Trades Executed   : {metrics.get('total_trades')}")
    print(f"Win Rate                : {metrics.get('win_rate_pct')}% ({metrics.get('wins')} Wins / {metrics.get('losses')} Losses)")
    print(f"Gross PnL               : ₹{metrics.get('gross_pnl'):,.2f}")
    print(f"Total Friction Paid     : ₹{metrics.get('total_friction'):,.2f}")
    print(f"Net PnL                 : ₹{metrics.get('net_pnl'):,.2f}")
    print(f"Total Net Return        : {metrics.get('total_return_pct')}%")
    print(f"Profit Factor           : {metrics.get('profit_factor')}")
    print(f"Net Expectancy / Trade  : ₹{metrics.get('net_expectancy_per_trade'):,.2f}")
    print(f"Max Drawdown            : ₹{metrics.get('max_drawdown_inr'):,.2f} ({metrics.get('max_drawdown_pct')}%)")
    print(f"Avg Holding Duration    : {metrics.get('avg_holding_minutes')} mins")
    print("=" * 80)
    
    return metrics, sym_perf, dow_perf, tod_perf, data_quality_report


if __name__ == "__main__":
    run_baseline_backtest()
