import sys
import os
import yfinance as yf

symbol = "RELIANCE.NS"
df = yf.download(symbol, period="1mo", interval="1h", progress=False)

if hasattr(df.columns, "levels") and len(df.columns.levels) > 1:
    df.columns = df.columns.get_level_values(0)

print(f"Loaded {len(df)} hourly bars for {symbol}. Running VWAP Mean Reversion Strategy...")

trades = []
position = None

for i in range(20, len(df)):
    window = df.iloc[i-20:i]
    close_prices = window['Close'].values.astype(float)
    mean_price = close_prices.mean()
    std_price = close_prices.std() if close_prices.std() > 0 else 1.0
    
    current_row = df.iloc[i]
    close = float(current_row['Close'])
    low = float(current_row['Low'])
    high = float(current_row['High'])
    
    vwap = (high + low + close) / 3.0
    # Entry condition: price drops below 0.5 standard deviations from VWAP
    lower_band = vwap - (0.5 * std_price)

    if position is None:
        if close <= lower_band:
            stop_loss = close - (2.0 * std_price)
            target = vwap
            position = {"entry": close, "stop": stop_loss, "target": target}
            print(f"[ENTRY LONG] Price: {close:.2f} | VWAP: {vwap:.2f} | Lower Band: {lower_band:.2f}")
    else:
        if low <= position["stop"]:
            pnl = position["stop"] - position["entry"]
            trades.append(pnl)
            print(f"[EXIT STOP LOSS] Exit: {position['stop']:.2f} | PnL: {pnl:.2f}")
            position = None
        elif high >= position["target"]:
            pnl = position["target"] - position["entry"]
            trades.append(pnl)
            print(f"[EXIT TARGET] Exit: {position['target']:.2f} | PnL: {pnl:.2f}")
            position = None

print("\n" + "=" * 50)
print("ALGO LAB — BACKTEST PERFORMANCE REPORT")
print(f"Strategy: VWAP Mean Reversion")
print(f"Instrument: {symbol} (NSE)")
print(f"Total Trades Executed: {len(trades)}")
if trades:
    wins = [t for t in trades if t > 0]
    win_rate = (len(wins) / len(trades)) * 100
    net_pnl = sum(trades)
    print(f"Win Rate: {win_rate:.2f}%")
    print(f"Net Cumulative PnL: INR {net_pnl:.2f}")
print("=" * 50)
