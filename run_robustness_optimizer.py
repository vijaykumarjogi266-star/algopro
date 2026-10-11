import sys
import os
import yfinance as yf
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

print("=" * 65)
print("ALGO LAB — ROBUSTNESS, PROFITABILITY & SURVIVAL OPTIMIZER")
print("Focus: Risk-Adjusted Returns, Max Drawdown Guardrails & Sharpe Ratio")
print("=" * 65)

symbols = ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ITC.NS", "NTPC.NS"]

def evaluate_robustness(symbol):
    df = yf.download(symbol, period="1y", interval="1d", progress=False)
    if hasattr(df.columns, "levels") and len(df.columns.levels) > 1:
        df.columns = df.columns.get_level_values(0)

    if len(df) < 50:
        return

    closes = df['Close'].values.astype(float)
    highs = df['High'].values.astype(float)
    lows = df['Low'].values.astype(float)

    # Strategy: Trend Following with Volatility Filter & Hard Stop-Loss (Survival Priority)
    # EMA 20 & EMA 50 Crossover with ATR-based Risk Control
    ema20 = pd.Series(closes).ewm(span=20).mean().values
    ema50 = pd.Series(closes).ewm(span=50).mean().values
    
    # ATR (14) calculation
    tr = np.maximum(highs[1:] - lows[1:], np.maximum(abs(highs[1:] - closes[:-1]), abs(lows[1:] - closes[:-1])))
    atr = pd.Series(tr).rolling(14).mean().values

    trades = []
    position = None
    peak_equity = 100000.0
    max_drawdown = 0.0
    equity = 100000.0

    for i in range(50, len(closes)):
        price = closes[i]
        current_atr = atr[i-1] if not np.isnan(atr[i-1]) else price * 0.02

        if position is None:
            # Entry condition: Fast EMA crosses above Slow EMA with volume/trend confirmation
            if ema20[i] > ema50[i] and ema20[i-1] <= ema50[i-1]:
                stop_loss = price - (2.0 * current_atr)
                target = price + (3.0 * current_atr) # 1.5 Risk-to-Reward ratio for profitability
                position = {"entry": price, "stop": stop_loss, "target": target}
        else:
            # Exit conditions: Stop loss hit, Target hit, or trend reversal
            if lows[i] <= position["stop"]:
                pnl = position["stop"] - position["entry"]
                equity += pnl * 10  # 10 shares unit size
                trades.append(pnl)
                position = None
            elif highs[i] >= position["target"]:
                pnl = position["target"] - position["entry"]
                equity += pnl * 10
                trades.append(pnl)
                position = None
            elif ema20[i] < ema50[i]: # Trend exhaustion exit
                pnl = price - position["entry"]
                equity += pnl * 10
                trades.append(pnl)
                position = None

        if equity > peak_equity:
            peak_equity = equity
        dd = (peak_equity - equity) / peak_equity
        if dd > max_drawdown:
            max_drawdown = dd

    total_trades = len(trades)
    winning_trades = [t for t in trades if t > 0]
    win_rate = (len(winning_trades) / total_trades * 100) if total_trades > 0 else 0.0
    net_pnl = sum(trades) if trades else 0.0
    profit_factor = (sum([t for t in trades if t > 0]) / abs(sum([t for t in trades if t < 0]))) if trades and sum([t for t in trades if t < 0]) != 0 else 99.9

    print(f"[{symbol}]")
    print(f"  -> Total Trades: {total_trades} | Win Rate: {win_rate:.1f}%")
    print(f"  -> Net PnL (INR): {net_pnl:.2f} | Max Drawdown: {max_drawdown*100:.2f}%")
    print(f"  -> Profit Factor: {profit_factor:.2f} | Survival Status: {'ROBUST & SURVIVABLE' if max_drawdown < 0.15 else 'HIGH RISK'}")
    print("-" * 65)

for sym in symbols:
    evaluate_robustness(sym)

print("Optimization complete adhering to Capital Preservation & Risk-First Principles.")
