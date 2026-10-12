#!/usr/bin/env python3
"""
Algo Lab — Continuous Live Paper Trading Daemon
Runs a persistent real-time loop:
- Scans NSE universe at regular intervals
- Evaluates trailing stops, targets, and exits
- Enters new high-conviction setups under 5x leverage & RiskEngine limits
- Persists state in SQLite database: data/paper_trading.db
- Logs status to data/paper_trading_live.log
"""

import sys
import os
import time
from datetime import datetime, timezone
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

try:
    import yfinance as yf
except ImportError:
    print("Error: yfinance is required.")
    sys.exit(1)

from data.schemas.contracts import Exchange, TimeFrame
from services.risk_engine.engine import RiskEngine
from services.risk_engine.contracts import HardRiskLimits
from services.risk_engine.audit import ContinuousRiskAuditor
from services.risk_engine.hooks import ValueAtRiskFilter
from services.paper_engine.session import PaperTradingEngine, SessionStatus
from services.backtest_engine.contracts import OrderSide, OrderType
from services.backtest_engine.execution_lifecycle import ExecutionLifecycleManager

# Configuration Parameters
INITIAL_CAPITAL = 10_000.0  # INR Base Capital
LEVERAGE = 5.0             # 5x Leverage
BUYING_POWER = INITIAL_CAPITAL * LEVERAGE  # INR 50,000
SCAN_INTERVAL_SECONDS = 60  # Scan every 60 seconds
DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "data", "paper_trading.db"))
LOG_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "data", "paper_trading_live.log"))

UNIVERSE = [
    "RELIANCE.NS",
    "TCS.NS",
    "INFY.NS",
    "HDFCBANK.NS",
    "ICICIBANK.NS",
    "SBIN.NS",
    "BHARTIARTL.NS",
    "ITC.NS"
]


def log_msg(msg: str):
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{timestamp}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


def scan_symbol(symbol: str) -> dict:
    try:
        df = yf.download(symbol, period="5d", interval="1h", progress=False)
        if hasattr(df.columns, "levels") and len(df.columns.levels) > 1:
            df.columns = df.columns.get_level_values(0)

        if df.empty or len(df) < 15:
            return {"symbol": symbol, "status": "INSUFFICIENT_DATA"}

        closes = df['Close'].values.astype(float)
        highs = df['High'].values.astype(float)
        lows = df['Low'].values.astype(float)
        volumes = df['Volume'].values.astype(float)

        latest_close = float(closes[-1])
        latest_high = float(highs[-1])
        latest_low = float(lows[-1])

        sma9 = float(pd.Series(closes).rolling(9).mean().iloc[-1])
        sma21 = float(pd.Series(closes).rolling(min(21, len(closes))).mean().iloc[-1])

        delta = pd.Series(closes).diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / (loss + 1e-9)
        rsi = 100 - (100 / (1 + rs))
        latest_rsi = float(rsi.iloc[-1]) if not np.isnan(rsi.iloc[-1]) else 50.0

        tr1 = highs[1:] - lows[1:]
        tr2 = np.abs(highs[1:] - closes[:-1])
        tr3 = np.abs(lows[1:] - closes[:-1])
        true_range = np.maximum(tr1, np.maximum(tr2, tr3))
        atr14 = float(pd.Series(true_range).rolling(min(14, len(true_range))).mean().iloc[-1])
        if np.isnan(atr14) or atr14 <= 0:
            atr14 = latest_close * 0.01

        typical_price = (highs + lows + closes) / 3.0
        cum_vol = np.cumsum(volumes)
        cum_tp_vol = np.cumsum(typical_price * volumes)
        vwap = float(cum_tp_vol[-1] / (cum_vol[-1] + 1e-9))
        std20 = float(np.std(closes[-min(20, len(closes)):]))

        signal = "WAIT"
        stop_loss = None
        target_price = None

        if sma9 > sma21 and latest_rsi < 65:
            signal = "BUY"
            stop_loss = round(latest_close - (1.5 * atr14), 2)
            target_price = round(latest_close + (3.0 * atr14), 2)
        elif latest_close < (vwap - (1.5 * std20)) and latest_rsi < 35:
            signal = "BUY"
            stop_loss = round(latest_close - (2.0 * atr14), 2)
            target_price = round(vwap, 2)

        return {
            "symbol": symbol,
            "status": "OK",
            "price": latest_close,
            "high": latest_high,
            "low": latest_low,
            "rsi": latest_rsi,
            "atr": atr14,
            "signal": signal,
            "stop_loss": stop_loss,
            "target": target_price,
            "historical_returns": list(pd.Series(closes).pct_change().dropna().iloc[-25:])
        }
    except Exception as e:
        return {"symbol": symbol, "status": "ERROR", "error": str(e)}


def main():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

    log_msg("=" * 65)
    log_msg("ALGO LAB — PERSISTENT LIVE PAPER TRADING DAEMON STARTED")
    log_msg(f"Base Capital: INR {INITIAL_CAPITAL:,.2f} | Leverage: {LEVERAGE:.0f}x | Buying Power: INR {BUYING_POWER:,.2f}")
    log_msg(f"Database: {DB_PATH}")
    log_msg(f"Scan Interval: {SCAN_INTERVAL_SECONDS} seconds")
    log_msg("=" * 65)

    risk_limits = HardRiskLimits(
        max_daily_loss_pct=0.04,
        max_portfolio_drawdown_pct=0.10,
        max_capital_per_trade_pct=0.20,
        max_open_positions=4,
        enforce_mandatory_stop_loss=True,
    )
    var_filter = ValueAtRiskFilter(confidence_level=0.95, max_var_pct=0.035)
    risk_engine = RiskEngine(limits=risk_limits, hooks=[var_filter])
    risk_auditor = ContinuousRiskAuditor(limits=risk_limits)

    lifecycle_manager = ExecutionLifecycleManager(risk_engine=risk_engine)
    paper_engine = PaperTradingEngine(DB_PATH, lifecycle_manager=lifecycle_manager)

    # Resume existing session or create fresh
    sessions = paper_engine.list_sessions()
    session = None
    for s in sessions:
        if s.status == SessionStatus.RUNNING:
            session = s
            break

    if not session:
        session = paper_engine.create_session(
            name="Persistent Live Paper Session",
            strategy_id="strat_daemon_5x",
            universe=UNIVERSE,
            initial_capital=BUYING_POWER,
        )
        paper_engine.start_session(session.session_id)
        log_msg(f"Created fresh paper session ID: {session.session_id}")
    else:
        log_msg(f"Resumed active paper session ID: {session.session_id}")

    cycle = 0
    trade_targets = {}  # {symbol: target_price}
    trade_stops = {}    # {symbol: stop_loss}

    while True:
        cycle += 1
        log_msg(f"--- Cycle #{cycle}: Scanning Market ---")
        market_prices = {}

        for sym in UNIVERSE:
            data = scan_symbol(sym)
            if data["status"] != "OK":
                continue

            price = data["price"]
            market_prices[sym] = price
            sym_key = sym.upper()

            # 1. Manage Active Positions (Check SL & Target Exits)
            current_pos = session.portfolio.positions.get(sym_key)
            if current_pos and current_pos.quantity > 0:
                current_sl = trade_stops.get(sym_key, current_pos.average_entry_price * 0.98)
                current_tp = trade_targets.get(sym_key, current_pos.average_entry_price * 1.03)

                if data["low"] <= current_sl:
                    log_msg(f"[EXIT TRIGGER] {sym} hit STOP LOSS @ {current_sl:.2f} (Entry: {current_pos.average_entry_price:.2f})")
                    order, fill = paper_engine.submit_manual_order(
                        session_id=session.session_id,
                        symbol=sym,
                        side=OrderSide.SELL,
                        quantity=current_pos.quantity,
                        price=current_sl,
                    )
                    trade_stops.pop(sym_key, None)
                    trade_targets.pop(sym_key, None)
                elif data["high"] >= current_tp:
                    log_msg(f"[EXIT TRIGGER] {sym} hit TARGET PROFIT @ {current_tp:.2f} (Entry: {current_pos.average_entry_price:.2f})")
                    order, fill = paper_engine.submit_manual_order(
                        session_id=session.session_id,
                        symbol=sym,
                        side=OrderSide.SELL,
                        quantity=current_pos.quantity,
                        price=current_tp,
                    )
                    trade_stops.pop(sym_key, None)
                    trade_targets.pop(sym_key, None)
                continue

            # 2. Check New Entry Signals
            if data["signal"] == "BUY":
                if len(session.portfolio.positions) >= risk_limits.max_open_positions:
                    log_msg(f"[SIGNAL IGNORED] {sym}: Max open positions ({risk_limits.max_open_positions}) reached.")
                    continue

                risk_per_trade = INITIAL_CAPITAL * 0.05
                stop_dist = max(price - data["stop_loss"], data["atr"])
                shares = int(risk_per_trade / stop_dist)
                max_shares = int((BUYING_POWER * 0.20) / price)
                shares = max(1, min(shares, max_shares))

                eval_res = risk_engine.evaluate(
                    symbol=sym,
                    price=price,
                    proposed_quantity=shares,
                    stop_loss=data["stop_loss"],
                    current_portfolio_value=session.portfolio.total_equity,
                    current_daily_loss_pct=0.0,
                    current_drawdown_pct=session.portfolio.max_drawdown_pct,
                    current_open_positions_count=len(session.portfolio.positions),
                    context={"historical_returns": data["historical_returns"]}
                )

                if eval_res.is_approved:
                    order, fill = paper_engine.submit_manual_order(
                        session_id=session.session_id,
                        symbol=sym,
                        side=OrderSide.BUY,
                        quantity=eval_res.approved_quantity,
                        price=price,
                        stop_loss=data["stop_loss"],
                    )
                    if fill:
                        trade_stops[sym_key] = data["stop_loss"]
                        trade_targets[sym_key] = data["target"]
                        log_msg(f"[BUY EXECUTED] {shares} shs {sym} @ {fill.fill_price:.2f} | SL: {data['stop_loss']} | Target: {data['target']}")
                else:
                    log_msg(f"[RISK REJECTED] {sym}: {eval_res.rejection_reason}")

        # Mark-to-market portfolio valuation
        session.portfolio.mark_to_market(market_prices)

        pos_val = session.portfolio.market_value_of_positions
        margin_used = pos_val / LEVERAGE
        free_margin = max(0.0, INITIAL_CAPITAL - margin_used)

        log_msg(f"Portfolio Status: Equity=INR {session.portfolio.total_equity:,.2f} | Margin Used=INR {margin_used:,.2f} ({(margin_used/INITIAL_CAPITAL)*100:.1f}%) | Free Margin=INR {free_margin:,.2f} | Unrealized PnL=INR {session.portfolio.total_unrealized_pnl:+,.2f} | Open Positions={len(session.portfolio.positions)}")

        time.sleep(SCAN_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
