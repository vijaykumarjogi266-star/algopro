"""
Algo Lab — Professional Backtest Runner using yfinance data and VWAP Mean Reversion Strategy.
"""

import sys
import os
from datetime import datetime, timezone
import pandas as pd

repo_root = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, repo_root)
sys.path.insert(0, os.path.abspath(os.path.join(repo_root, "..")))

from quant.strategies.vwap_reversion import VWAPReversion
from data.schemas.contracts import OHLCVBar, TimeFrame, Exchange

def run_yfinance_backtest():
    print("=" * 60)
    print("Algo Lab Backtest Runner — VWAP Mean Reversion Strategy")
    print("Market: NSE India (Simulated via yfinance historical proxy)")
    print("=" * 60)

    try:
        import yfinance as yf
    except ImportError:
        print("yfinance is not installed. Please install via: pip install yfinance")
        return

    symbol = "RELIANCE.NS"
    print(f"Fetching 30-day 1-hour historical data for {symbol}...")
    df = yf.download(symbol, period="1mo", interval="1h", progress=False)

    if df.empty:
        print("No data fetched from yfinance. Aborting.")
        return

    # Handle multi-index columns if present in newer yfinance versions
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    bars = []
    for idx, row in df.iterrows():
        ts = idx.to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        
        bar = OHLCVBar(
            symbol=symbol,
            timeframe=TimeFrame.ONE_HOUR,
            market_timestamp=ts,
            open=float(row['Open']),
            high=float(row['High']),
            low=float(row['Low']),
            close=float(row['Close']),
            volume=int(row['Volume']),
            vwap=float((row['High'] + row['Low'] + row['Close']) / 3.0),
            exchange=Exchange.NSE,
            is_verified=True
        )
        bars.append(bar)

    print(f"Loaded {len(bars)} verified OHLCV bars.")

    strategy = VWAPReversion(std_dev_threshold=2.0, stop_loss_atr_mult=1.5)
    
    trades = []
    open_position = None

    for i in range(20, len(bars)):
        bar = bars[i]
        history = bars[i-20:i]
        
        # Simple rolling VWAP calculation over history
        prices = [b.close for b in history]
        mean_price = sum(prices) / len(prices)
        variance = sum((p - mean_price) ** 2 for p in prices) / len(prices)
        std_dev = variance ** 0.5 if variance > 0 else 1.0
        
        vwap_val = bar.vwap or mean_price
        vwap_lower = vwap_val - (2.0 * std_dev)
        atr_val = 5.0  # proxy ATR

        indicators = {
            "vwap": vwap_val,
            "vwap_lower": vwap_lower,
            "atr_14": atr_val,
            "rsi_14": 45.0
        }

        if open_position is None:
            candidate = strategy.on_bar(bar, history, indicators, has_open_position=False)
            if candidate and candidate.action.value == "ENTER_LONG":
                open_position = {
                    "entry_price": bar.close,
                    "stop_loss": candidate.suggested_stop_loss,
                    "target": candidate.suggested_target_price,
                    "time": bar.market_timestamp
                }
                print(f"[SIGNAL] Long Entry at {bar.close:.2f} on {bar.market_timestamp} | Reason: {candidate.reason}")
        else:
            # Check exit conditions (Stop loss or Target)
            if bar.low <= open_position["stop_loss"]:
                pnl = open_position["stop_loss"] - open_position["entry_price"]
                trades.append({"pnl": pnl, "type": "STOP_LOSS", "exit_time": bar.market_timestamp})
                print(f"[EXIT] Stop Loss Hit at {open_position['stop_loss']:.2f} | PnL: {pnl:.2f}")
                open_position = None
            elif bar.high >= open_position["target"]:
                pnl = open_position["target"] - open_position["entry_price"]
                trades.append({"pnl": pnl, "type": "TARGET", "exit_time": bar.market_timestamp})
                print(f"[EXIT] Target Reached at {open_position['target']:.2f} | PnL: {pnl:.2f}")
                open_position = None

    print("\n" + "=" * 60)
    print("BACKTEST SUMMARY REPORT")
    print(f"Total Trades Executed: {len(trades)}")
    if trades:
        wins = [t for t in trades if t["pnl"] > 0]
        total_pnl = sum(t["pnl"] for t in trades)
        win_rate = (len(wins) / len(trades)) * 100
        print(f"Win Rate: {win_rate:.2f}%")
        print(f"Total Cumulative PnL: INR {total_pnl:.2f}")
    print("=" * 60)

if __name__ == "__main__":
    run_yfinance_backtest()
