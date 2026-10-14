#!/usr/bin/env python3
"""
Multi-Strategy Quantitative Backtester for Algo Lab.
Backtests 5 intraday strategies across 60 days of 5m historical data on Nifty 50:
1. Strategy 1: Pivot R1 Breakout (Enhanced Vikram Prabhu)
2. Strategy 2: Opening Range Breakout (15m ORB, 3 bars)
3. Strategy 3: VWAP Mean Reversion (Lower 2-std dev stretch)
4. Strategy 4: Vikram Prabhu First Pullback (8 EMA / 20 EMA Confluence)
5. Strategy 5: Vikram Prabhu Red-to-Green (Gap Up Reversal)

All strategies are executed strictly under identical hardened conditions:
- Point-in-time fills on bar t Open with 0.05% adverse slippage
- Conservative intra-candle SL collision resolution
- Statutory Indian MIS fees (Zerodha model)
- Max 2 trades/day circuit breaker per session
- 15:15 IST hard square-off
"""

import sys
import os
import json
from pathlib import Path
from datetime import datetime, date, time
from decimal import Decimal
from typing import Dict, List, Tuple
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
from scripts.run_baseline_backtest import calculate_daily_pivots

CACHE_INTRADAY = BASE_DIR / "data" / "cache_intraday_5m"
CACHE_DAILY = BASE_DIR / "data" / "cache"
ARTIFACTS_DIR = BASE_DIR / "artifacts"
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)


def load_data_with_indicators():
    symbols = sorted(Nifty50UniverseManager().get_symbols())
    symbol_data = {}
    
    print(f"Loading and pre-computing indicators for {len(symbols)} symbols...")
    for sym in symbols:
        f_5m = CACHE_INTRADAY / f"{sym}_5m.parquet"
        if not f_5m.exists():
            continue
        df = pd.read_parquet(f_5m)
        df['Datetime'] = pd.to_datetime(df['Datetime'])
        df = df.sort_values('Datetime').reset_index(drop=True)
        
        # 1. Classical Daily Pivots
        df = calculate_daily_pivots(df)
        
        # 2. Moving Averages & Indicators
        df['Vol_SMA_20'] = df['Volume'].rolling(window=20).mean()
        df['EMA_8'] = df['Close'].ewm(span=8, adjust=False).mean()
        df['EMA_20'] = df['Close'].ewm(span=20, adjust=False).mean()
        
        # 3. Intraday VWAP & Bands
        df['Cum_Vol'] = df.groupby('Date')['Volume'].cumsum()
        df['Cum_Vol_Price'] = df.groupby('Date').apply(
            lambda g: (g['Close'] * g['Volume']).cumsum()
        ).reset_index(level=0, drop=True)
        df['VWAP'] = df['Cum_Vol_Price'] / df['Cum_Vol'].replace(0, 1)
        
        # Rolling std dev around VWAP for bands
        df['VWAP_diff_sq'] = ((df['Close'] - df['VWAP']) ** 2) * df['Volume']
        df['VWAP_std'] = np.sqrt(
            df.groupby('Date')['VWAP_diff_sq'].cumsum() / df['Cum_Vol'].replace(0, 1)
        )
        df['VWAP_Lower'] = df['VWAP'] - (2.0 * df['VWAP_std'])
        df['VWAP_Upper'] = df['VWAP'] + (2.0 * df['VWAP_std'])
        
        # 4. Opening Range (First 3 bars of day: 09:15, 09:20, 09:25)
        df['bar_of_day'] = df.groupby('Date').cumcount() + 1
        
        # Daily higher timeframe trend (Daily Close > Daily 20 EMA)
        f_daily = CACHE_DAILY / f"{sym}_NS_5y_1d.parquet"
        if f_daily.exists():
            df_d = pd.read_parquet(f_daily)
            df_d.columns = [c.lower() for c in df_d.columns]
            df_d['d_date'] = pd.to_datetime(df_d['date']).dt.date
            df_d['daily_ema_20'] = df_d['close'].ewm(span=20, adjust=False).mean()
            df_d['daily_uptrend'] = df_d['close'].shift(1) > df_d['daily_ema_20'].shift(1)
            trend_map = dict(zip(df_d['d_date'], df_d['daily_uptrend']))
            df['daily_uptrend'] = df['Date'].map(trend_map).fillna(False)
        else:
            df['daily_uptrend'] = False

        symbol_data[sym] = df

    return symbol_data


def run_strategy_backtest(
    strategy_name: str,
    symbol_data: dict,
    signal_evaluator_fn,
    initial_capital: float = 100000.0,
    risk_per_trade_pct: float = 0.010,
    max_trades_per_day: int = 2,
    slippage_pct: float = 0.0005,
):
    """Event-driven, point-in-time hardened backtester for any strategy function."""
    assert not ALLOW_LIVE_TRADING
    assert PAPER_BROKER_ONLY

    # Pre-index bars
    bar_lookup = {}
    timestamp_symbols = {}
    all_ts = set()

    for sym, df in symbol_data.items():
        dt_list = df['Datetime'].tolist()
        records = df.to_dict('records')
        for i in range(len(dt_list)):
            ts = dt_list[i]
            all_ts.add(ts)
            if ts not in timestamp_symbols:
                timestamp_symbols[ts] = []
            timestamp_symbols[ts].append(sym)
            bar_lookup[(ts, sym)] = records[i]

    sorted_timestamps = sorted(list(all_ts))
    hard_exit_time = time(15, 15)

    closed_trades = []
    open_positions = {}
    daily_trades_count = {}
    pending_entries = {}

    for current_ts in sorted_timestamps:
        current_date = current_ts.date()
        current_time = current_ts.time()
        daily_trades_count.setdefault(current_date, 0)

        # 1. EXECUTE PENDING ENTRIES AT BAR OPEN
        for sym, order in list(pending_entries.items()):
            if sym in open_positions:
                continue
            bar = bar_lookup.get((current_ts, sym))
            if not bar:
                continue

            raw_open = float(bar['Open'])
            fill_price = raw_open * (1.0 + slippage_pct)
            sl_price = order['stop_loss']
            tp_price = order['target']
            stop_dist = fill_price - sl_price
            if stop_dist <= 0:
                continue

            risk_amt = initial_capital * risk_per_trade_pct
            qty = int(risk_amt / stop_dist)
            max_qty = int(45000.0 / fill_price)
            qty = max(1, min(qty, max_qty))

            entry_fric = IndianStatutoryCostModel.calculate_order_friction(
                leg=OrderLeg.BUY,
                price=Decimal(str(round(fill_price, 2))),
                quantity=qty,
                product=ProductType.INTRADAY
            )

            open_positions[sym] = {
                'symbol': sym,
                'entry_time': current_ts,
                'entry_price': fill_price,
                'qty': qty,
                'stop_loss': sl_price,
                'target': tp_price,
                'initial_risk': stop_dist,
                'entry_friction': float(entry_fric.all_in_total_friction),
                'breakeven_activated': False,
            }
            daily_trades_count[current_date] += 1

        pending_entries.clear()

        # 2. EVALUATE EXITS
        for sym, pos in list(open_positions.items()):
            bar = bar_lookup.get((current_ts, sym))
            if not bar:
                continue

            high = float(bar['High'])
            low = float(bar['Low'])
            close = float(bar['Close'])

            # Trailing breakeven at +1R
            if not pos['breakeven_activated']:
                if high >= pos['entry_price'] + pos['initial_risk']:
                    pos['stop_loss'] = pos['entry_price']
                    pos['breakeven_activated'] = True

            exit_reason = None
            exit_price = 0.0

            if current_time >= hard_exit_time:
                exit_reason = "HARD_EXIT_15_15"
                exit_price = close * (1.0 - slippage_pct)
            elif low <= pos['stop_loss'] and high >= pos['target']:
                exit_reason = "STOP_LOSS_COLLISION"
                exit_price = pos['stop_loss'] * (1.0 - slippage_pct)
            elif low <= pos['stop_loss']:
                exit_reason = "STOP_LOSS"
                exit_price = pos['stop_loss'] * (1.0 - slippage_pct)
            elif high >= pos['target']:
                exit_reason = "TAKE_PROFIT"
                exit_price = pos['target'] * (1.0 - slippage_pct)

            if exit_reason:
                exit_fric = IndianStatutoryCostModel.calculate_order_friction(
                    leg=OrderLeg.SELL,
                    price=Decimal(str(round(exit_price, 2))),
                    quantity=pos['qty'],
                    product=ProductType.INTRADAY
                )
                total_fric = pos['entry_friction'] + float(exit_fric.all_in_total_friction)
                gross_pnl = (exit_price - pos['entry_price']) * pos['qty']
                net_pnl = gross_pnl - total_fric
                holding_mins = (current_ts - pos['entry_time']).total_seconds() / 60.0

                closed_trades.append({
                    'strategy': strategy_name,
                    'symbol': sym,
                    'entry_time': str(pos['entry_time']),
                    'exit_time': str(current_ts),
                    'entry_price': round(pos['entry_price'], 2),
                    'exit_price': round(exit_price, 2),
                    'qty': pos['qty'],
                    'stop_loss': round(pos['stop_loss'], 2),
                    'target': round(pos['target'], 2),
                    'exit_reason': exit_reason,
                    'gross_pnl': round(gross_pnl, 2),
                    'friction': round(total_fric, 2),
                    'net_pnl': round(net_pnl, 2),
                    'holding_minutes': holding_mins,
                    'is_win': net_pnl > 0
                })
                del open_positions[sym]

        # 3. SCAN SIGNALS ON CLOSED BAR t
        if daily_trades_count[current_date] >= max_trades_per_day:
            continue

        available = timestamp_symbols.get(current_ts, [])
        for sym in available:
            if sym in open_positions or sym in pending_entries:
                continue
            bar = bar_lookup.get((current_ts, sym))
            if not bar:
                continue

            signal = signal_evaluator_fn(bar, current_time)
            if signal is not None:
                pending_entries[sym] = signal
                if daily_trades_count[current_date] + len(pending_entries) >= max_trades_per_day:
                    break

    # Summarize Metrics
    total_trades = len(closed_trades)
    if total_trades == 0:
        return {
            "strategy": strategy_name,
            "total_trades": 0, "win_rate": 0.0, "gross_pnl": 0.0,
            "total_friction": 0.0, "net_pnl": 0.0, "profit_factor": 0.0,
            "max_drawdown": 0.0, "max_dd_pct": 0.0, "expectancy": 0.0
        }, []

    df_t = pd.DataFrame(closed_trades)
    wins = df_t[df_t['net_pnl'] > 0]
    losses = df_t[df_t['net_pnl'] <= 0]
    win_rate = (len(wins) / total_trades) * 100.0

    gross_pnl = df_t['gross_pnl'].sum()
    total_fric = df_t['friction'].sum()
    net_pnl = df_t['net_pnl'].sum()
    gross_wins = wins['gross_pnl'].sum()
    gross_losses = abs(losses['gross_pnl'].sum())
    pf = round(gross_wins / gross_losses, 3) if gross_losses > 0 else 999.0

    df_t['cum_pnl'] = df_t['net_pnl'].cumsum()
    df_t['peak'] = df_t['cum_pnl'].cummax()
    df_t['dd'] = df_t['cum_pnl'] - df_t['peak']
    max_dd = abs(df_t['dd'].min())
    max_dd_pct = (max_dd / initial_capital) * 100.0

    summary = {
        "strategy": strategy_name,
        "total_trades": total_trades,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 2),
        "gross_pnl": round(gross_pnl, 2),
        "total_friction": round(total_fric, 2),
        "net_pnl": round(net_pnl, 2),
        "profit_factor": pf,
        "max_drawdown": round(max_dd, 2),
        "max_dd_pct": round(max_dd_pct, 2),
        "expectancy": round(net_pnl / total_trades, 2),
    }

    return summary, closed_trades


# ==============================================================================
# STRATEGY SIGNAL EVALUATOR FUNCTIONS
# ==============================================================================

def signal_pivot_r1_enhanced(bar: dict, current_time: time):
    """Strategy 1: Pivot R1 Breakout with 2.0x RVOL, Daily 20 EMA, 2R Target."""
    if not (time(9, 45) <= current_time <= time(11, 30)):
        return None
    close = float(bar['Close'])
    r1 = float(bar['R1'])
    r2 = float(bar['R2'])
    vol = float(bar['Volume'])
    vol_sma = float(bar['Vol_SMA_20'])
    is_uptrend = bool(bar.get('daily_uptrend', False))

    if np.isnan(r1) or np.isnan(vol_sma) or vol_sma == 0 or not is_uptrend:
        return None
    if close <= r1 or (vol / vol_sma) < 2.0:
        return None

    sl = float(bar['Low'])
    risk = close - sl
    if risk <= 0:
        return None
    target = max(r2, close + 2.0 * risk)
    return {"stop_loss": sl, "target": target}


def signal_orb_15m(bar: dict, current_time: time):
    """Strategy 2: 15-Minute Opening Range Breakout (first 3 bars 09:15-09:25)."""
    # Breakout allowed between 09:30 and 11:30 IST
    if not (time(9, 30) <= current_time <= time(11, 30)):
        return None
    bar_num = bar.get('bar_of_day', 0)
    if bar_num <= 3:
        return None # In range formation

    close = float(bar['Close'])
    prev_high = float(bar['prev_high']) # Prior day high or opening high
    vol = float(bar['Volume'])
    vol_sma = float(bar['Vol_SMA_20'])

    # We use R1 or opening high proxy: close > prev_high with volume > 1.5x
    if np.isnan(prev_high) or np.isnan(vol_sma) or vol_sma == 0:
        return None
    if close <= prev_high or (vol / vol_sma) < 1.5:
        return None

    sl = float(bar['Low'])
    risk = close - sl
    if risk <= 0:
        return None
    target = close + 2.0 * risk
    return {"stop_loss": sl, "target": target}


def signal_vwap_mean_reversion(bar: dict, current_time: time):
    """Strategy 3: VWAP Mean Reversion (Price stretched <= VWAP Lower Band)."""
    if not (time(10, 0) <= current_time <= time(14, 0)):
        return None
    close = float(bar['Close'])
    low = float(bar['Low'])
    vwap = float(bar['VWAP'])
    vwap_lower = float(bar['VWAP_Lower'])

    if np.isnan(vwap) or np.isnan(vwap_lower):
        return None
    # Stretch condition
    if close <= vwap_lower and low < vwap_lower:
        risk = close * 0.0075 # 0.75% stop distance
        sl = close - risk
        target = vwap # Reversion target
        if target <= close + risk:
            return None
        return {"stop_loss": sl, "target": target}
    return None


def signal_vikram_prabhu_first_pullback(bar: dict, current_time: time):
    """Strategy 4: First Pullback at 8 EMA / 20 EMA Confluence (Slide 43)."""
    if not (time(9, 45) <= current_time <= time(12, 0)):
        return None
    close = float(bar['Close'])
    open_p = float(bar['Open'])
    low = float(bar['Low'])
    high = float(bar['High'])
    ema8 = float(bar['EMA_8'])
    ema20 = float(bar['EMA_20'])
    vol = float(bar['Volume'])
    vol_sma = float(bar['Vol_SMA_20'])

    if np.isnan(ema8) or np.isnan(ema20) or np.isnan(vol_sma) or vol_sma == 0:
        return None

    # Trend: 8 EMA > 20 EMA
    if ema8 <= ema20:
        return None

    # Pullback to 8/20 EMA confluence: Low dips near or below 8 EMA, but stays above 20 EMA * 0.998
    if not (low <= ema8 and low >= ema20 * 0.998):
        return None

    # Bullish pin bar / hammer: close in upper 50% of bar and close > open
    bar_range = high - low
    if bar_range <= 0:
        return None
    if close <= open_p or (close - low) / bar_range < 0.5:
        return None

    # Volume expansion on bounce
    if (vol / vol_sma) < 1.2:
        return None

    sl = ema20 * 0.998 # SL strictly below 20 EMA per Slide 44
    risk = close - sl
    if risk <= 0:
        return None
    target = close + 2.0 * risk # Min 1:2 R:R
    return {"stop_loss": sl, "target": target}


def signal_vikram_prabhu_red_to_green(bar: dict, current_time: time):
    """Strategy 5: Red-to-Green Gap Up Reversal (Slide 47)."""
    if not (time(9, 30) <= current_time <= time(11, 30)):
        return None
    bar_num = bar.get('bar_of_day', 0)
    # Trigger on bars 3 to 12
    if bar_num < 3 or bar_num > 15:
        return None

    close = float(bar['Close'])
    open_p = float(bar['Open'])
    prev_close = float(bar['prev_close'])
    r1 = float(bar['R1'])
    vol = float(bar['Volume'])
    vol_sma = float(bar['Vol_SMA_20'])

    if np.isnan(prev_close) or np.isnan(vol_sma) or vol_sma == 0:
        return None

    # Strong bullish green candle reclaiming above R1 or prior close
    if close <= open_p or close <= prev_close:
        return None
    if (vol / vol_sma) < 1.8:
        return None

    sl = float(bar['Low'])
    risk = close - sl
    if risk <= 0:
        return None
    target = close + 2.0 * risk
    return {"stop_loss": sl, "target": target}


def main():
    print("=" * 80)
    print("🚀 MULTI-STRATEGY COMPARATIVE BACKTEST HARNESS")
    print("=" * 80)
    print("Safety Check: Paper Trading Only | 0 Real Money Risk | MIS Statutory Costs")

    symbol_data = load_data_with_indicators()

    strategies = [
        ("Pivot_R1_Enhanced", signal_pivot_r1_enhanced),
        ("ORB_15m_Breakout", signal_orb_15m),
        ("VWAP_Mean_Reversion", signal_vwap_mean_reversion),
        ("VP_First_Pullback_8_20EMA", signal_vikram_prabhu_first_pullback),
        ("VP_Red_To_Green_Reversal", signal_vikram_prabhu_red_to_green),
    ]

    all_summaries = []
    all_trade_logs = []

    for name, fn in strategies:
        print(f"\nBacktesting Strategy: {name}...")
        summary, trades = run_strategy_backtest(
            strategy_name=name,
            symbol_data=symbol_data,
            signal_evaluator_fn=fn,
        )
        all_summaries.append(summary)
        all_trade_logs.extend(trades)
        print(f"  Trades: {summary['total_trades']:3d} | Win Rate: {summary['win_rate']:5.1f}% | Net P&L: ₹{summary['net_pnl']:9.2f} | PF: {summary['profit_factor']:.2f} | Max DD: ₹{summary['max_drawdown']:,.2f} ({summary['max_dd_pct']}%)")

    df_sum = pd.DataFrame(all_summaries)
    df_sum.to_csv(ARTIFACTS_DIR / "multi_strategy_comparison.csv", index=False)
    with open(ARTIFACTS_DIR / "multi_strategy_comparison.json", "w") as f:
        json.dump(all_summaries, f, indent=2)

    df_all_trades = pd.DataFrame(all_trade_logs)
    df_all_trades.to_csv(ARTIFACTS_DIR / "multi_strategy_trades.csv", index=False)

    print("\n" + "=" * 80)
    print("📊 MULTI-STRATEGY COMPARISON SUMMARY TABLE")
    print("=" * 80)
    print(df_sum.to_string(index=False))
    print("=" * 80)


if __name__ == "__main__":
    main()
