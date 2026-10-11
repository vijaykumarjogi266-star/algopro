import sys
import os
import yfinance as yf
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

print("=" * 60)
print("ALGO LAB — MULTI-STRATEGY QUANTITATIVE BACKTESTER & LIVE SCANNER")
print("=" * 60)

symbols = ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS"]

def run_strategy_backtest(symbol):
    print(f"\nAnalyzing {symbol}...")
    df = yf.download(symbol, period="3mo", interval="1d", progress=False)
    if hasattr(df.columns, "levels") and len(df.columns.levels) > 1:
        df.columns = df.columns.get_level_values(0)

    if len(df) < 30:
        print(f"Insufficient data for {symbol}.")
        return

    closes = df['Close'].values.astype(float)
    highs = df['High'].values.astype(float)
    lows = df['Low'].values.astype(float)

    # 1. Moving Average Crossover Strategy (SMA 9 vs SMA 21)
    sma9 = pd.Series(closes).rolling(9).mean().values
    sma21 = pd.Series(closes).rolling(21).mean().values

    # 2. RSI Mean Reversion Strategy
    delta = pd.Series(closes).diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    rsi_vals = rsi.values

    position_sma = None
    pnl_sma = 0.0
    trades_sma = 0

    for i in range(21, len(closes)):
        if position_sma is None:
            if sma9[i] > sma21[i] and sma9[i-1] <= sma21[i-1]:
                position_sma = closes[i]
                trades_sma += 1
        else:
            if sma9[i] < sma21[i]:
                pnl_sma += (closes[i] - position_sma)
                position_sma = None

    print(f" -> SMA Crossover (9/21): Trades = {trades_sma}, Cumulative PnL = INR {pnl_sma:.2f}")

    # Simulated Live Market Scanner Signal Check
    latest_close = closes[-1]
    latest_rsi = rsi_vals[-1]
    latest_sma9 = sma9[-1]
    latest_sma21 = sma21[-1]

    signal = "WAIT (No Action)"
    if latest_sma9 > latest_sma21 and latest_rsi < 65:
        signal = "BUY (Bullish Crossover & Healthy RSI)"
    elif latest_sma9 < latest_sma21 and latest_rsi > 35:
        signal = "SELL / SHORT (Bearish Crossover)"

    print(f" -> [LIVE SCANNER ALERT] {symbol} | Price: INR {latest_close:.2f} | RSI: {latest_rsi:.1f} | Signal: {signal}")

for sym in symbols:
    run_strategy_backtest(sym)

print("\n" + "=" * 60)
print("Scan completed successfully under Algo Lab governance protocols.")
print("=" * 60)
