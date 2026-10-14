#!/usr/bin/env python3
"""
Downloads and caches 5-minute historical data for Nifty 50 over max available period (60 days)
Ensures reproducible offline backtesting without network jitter or API rate-limit drift.
"""

import os
import sys
from pathlib import Path
import pandas as pd
import yfinance as yf

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from services.scanner.universe_manager import Nifty50UniverseManager

CACHE_DIR = BASE_DIR / "data" / "cache_intraday_5m"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

def cache_all_5m():
    symbols = Nifty50UniverseManager().get_symbols()
    print(f"Caching 5m data for {len(symbols)} symbols into {CACHE_DIR}...")
    
    tickers = [f"{sym}.NS" for sym in symbols]
    data = yf.download(tickers, period="60d", interval="5m", group_by="ticker", threads=True, progress=False)
    
    summary = []
    
    for sym in symbols:
        ticker = f"{sym}.NS"
        if ticker in data.columns.levels[0]:
            df = data[ticker].dropna(how="all").reset_index()
            # Standardize Datetime column
            if "Datetime" not in df.columns and "Date" in df.columns:
                df.rename(columns={"Date": "Datetime"}, inplace=True)
            if "index" in df.columns and "Datetime" not in df.columns:
                df.rename(columns={"index": "Datetime"}, inplace=True)
                
            if not df.empty and "Datetime" in df.columns:
                out_path = CACHE_DIR / f"{sym}_5m.parquet"
                df.to_parquet(out_path, index=False)
                summary.append({
                    "symbol": sym,
                    "bars": len(df),
                    "start": str(df["Datetime"].iloc[0]),
                    "end": str(df["Datetime"].iloc[-1])
                })
            else:
                print(f"Warning: No valid data for {sym}")
        else:
            print(f"Warning: Ticker {ticker} missing from download response")

    df_summary = pd.DataFrame(summary)
    summary_path = CACHE_DIR / "dataset_summary.csv"
    df_summary.to_csv(summary_path, index=False)
    print(f"Successfully cached {len(summary)} symbols.")
    if not df_summary.empty:
        print(f"Date range: {df_summary['start'].min()} to {df_summary['end'].max()}")
        print(f"Average bars per symbol: {df_summary['bars'].mean():.1f}")

if __name__ == "__main__":
    cache_all_5m()
