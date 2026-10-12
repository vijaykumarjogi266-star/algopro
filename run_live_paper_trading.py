#!/usr/bin/env python3
"""
Algo Lab — Live Paper Trading Session & Market Scanner
Configured with:
- Initial Capital: INR 10,000
- Leverage: 5x (Effective Buying Power: INR 50,000)
- Multi-Symbol NSE Universe
- Risk Engine & Continuous Risk Auditor Guardrails
- Paper Portfolio Accounting & Mark-to-Market
"""

import sys
import os
from datetime import datetime, timezone
import pandas as pd
import numpy as np

# Ensure path resolution
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

try:
    import yfinance as yf
except ImportError:
    print("Error: yfinance is required. Run in container or install yfinance.")
    sys.exit(1)

from data.schemas.contracts import Exchange, TimeFrame
from services.risk_engine.engine import RiskEngine
from services.risk_engine.contracts import HardRiskLimits
from services.risk_engine.audit import ContinuousRiskAuditor, AuditComplianceStatus
from services.risk_engine.hooks import ValueAtRiskFilter
from services.paper_engine.session import PaperTradingEngine, SessionStatus
from services.backtest_engine.contracts import OrderSide, OrderType
from services.backtest_engine.execution_lifecycle import ExecutionLifecycleManager


# Configuration Parameters
INITIAL_CAPITAL = 10_000.0  # INR
LEVERAGE = 5.0             # 5x Intraday / MIS Margin Leverage
BUYING_POWER = INITIAL_CAPITAL * LEVERAGE  # INR 50,000
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


def print_header():
    print("=" * 70)
    print("     ALGO LAB — LIVE MARKET SCANNER & PAPER TRADING ENGINE     ")
    print(f"  Initial Equity: INR {INITIAL_CAPITAL:,.2f} | Leverage: {LEVERAGE:.0f}x | Buying Power: INR {BUYING_POWER:,.2f}")
    print(f"  Target Market: NSE India (Simulated via Real-Time Feed Proxy)")
    print(f"  Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 70)


def scan_symbol(symbol: str) -> dict:
    """Fetches real market data and calculates quantitative signals."""
    try:
        df = yf.download(symbol, period="1mo", interval="1h", progress=False)
        if hasattr(df.columns, "levels") and len(df.columns.levels) > 1:
            df.columns = df.columns.get_level_values(0)

        if df.empty or len(df) < 25:
            return {"symbol": symbol, "status": "INSUFFICIENT_DATA"}

        closes = df['Close'].values.astype(float)
        highs = df['High'].values.astype(float)
        lows = df['Low'].values.astype(float)
        volumes = df['Volume'].values.astype(float)

        latest_close = float(closes[-1])
        latest_high = float(highs[-1])
        latest_low = float(lows[-1])

        # 1. Moving Averages (9 vs 21 EMA/SMA)
        sma9 = float(pd.Series(closes).rolling(9).mean().iloc[-1])
        sma21 = float(pd.Series(closes).rolling(21).mean().iloc[-1])

        # 2. RSI 14
        delta = pd.Series(closes).diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / (loss + 1e-9)
        rsi = 100 - (100 / (1 + rs))
        latest_rsi = float(rsi.iloc[-1])

        # 3. ATR 14 for Volatility & Dynamic Stop Loss
        tr1 = highs[1:] - lows[1:]
        tr2 = np.abs(highs[1:] - closes[:-1])
        tr3 = np.abs(lows[1:] - closes[:-1])
        true_range = np.maximum(tr1, np.maximum(tr2, tr3))
        atr14 = float(pd.Series(true_range).rolling(14).mean().iloc[-1])
        if np.isnan(atr14) or atr14 <= 0:
            atr14 = latest_close * 0.01

        # 4. VWAP & Bands
        typical_price = (highs + lows + closes) / 3.0
        cum_vol = np.cumsum(volumes)
        cum_tp_vol = np.cumsum(typical_price * volumes)
        vwap = float(cum_tp_vol[-1] / (cum_vol[-1] + 1e-9))
        std20 = float(np.std(closes[-20:]))

        # Signal Generation Logic (Non-Negotiable Principles: Never force trade)
        signal = "WAIT"
        reason = "No high-conviction alpha confluence"
        target_price = None
        stop_loss = None

        # Bullish Crossover + Oversold Rebound
        if sma9 > sma21 and latest_rsi < 62:
            signal = "BUY"
            reason = f"Bullish SMA(9/21) Cross | RSI={latest_rsi:.1f} | ATR={atr14:.2f}"
            stop_loss = round(latest_close - (1.5 * atr14), 2)
            target_price = round(latest_close + (3.0 * atr14), 2)
        elif latest_close < (vwap - (1.5 * std20)) and latest_rsi < 38:
            signal = "BUY"
            reason = f"Mean Reversion: Deep discount below VWAP-1.5σ | RSI={latest_rsi:.1f}"
            stop_loss = round(latest_close - (2.0 * atr14), 2)
            target_price = round(vwap, 2)
        elif latest_rsi > 72:
            signal = "OVERBOUGHT"
            reason = f"RSI={latest_rsi:.1f} > 70 — Wait for retracement"

        return {
            "symbol": symbol,
            "status": "OK",
            "price": latest_close,
            "rsi": latest_rsi,
            "sma9": sma9,
            "sma21": sma21,
            "vwap": vwap,
            "atr": atr14,
            "signal": signal,
            "reason": reason,
            "stop_loss": stop_loss,
            "target": target_price,
            "historical_returns": list(pd.Series(closes).pct_change().dropna().iloc[-30:])
        }
    except Exception as e:
        return {"symbol": symbol, "status": "ERROR", "error": str(e)}


def main():
    print_header()

    # 1. Initialize Independent Risk Engine with 5x Leverage Budgeting
    risk_limits = HardRiskLimits(
        max_daily_loss_pct=0.04,          # 4% Max Daily Loss
        max_portfolio_drawdown_pct=0.10,  # 10% Max Drawdown
        max_capital_per_trade_pct=0.20,   # Max 20% of buying power per position (Hard Invariant)
        max_open_positions=4,             # Max 4 concurrent positions
        enforce_mandatory_stop_loss=True,
    )
    var_filter = ValueAtRiskFilter(confidence_level=0.95, max_var_pct=0.035)
    risk_engine = RiskEngine(limits=risk_limits, hooks=[var_filter])
    risk_auditor = ContinuousRiskAuditor(limits=risk_limits)

    # 2. Initialize Paper Trading Engine with Risk Engine Gate
    lifecycle_manager = ExecutionLifecycleManager(risk_engine=risk_engine)
    paper_engine = PaperTradingEngine(":memory:", lifecycle_manager=lifecycle_manager)
    session = paper_engine.create_session(
        name="NSE 5x Leverage Alpha Session",
        strategy_id="strat_multialpha_5x",
        universe=UNIVERSE,
        initial_capital=BUYING_POWER,
    )
    paper_engine.start_session(session.session_id)

    print("\nScanning NSE Market Universe for Live Alpha Confluences...")
    print("-" * 70)
    print(f"{'SYMBOL':<14} | {'PRICE (INR)':<11} | {'RSI':<6} | {'SIGNAL':<12} | {'ACTION':<20}")
    print("-" * 70)

    scan_results = []
    executed_trades = []

    for sym in UNIVERSE:
        data = scan_symbol(sym)
        scan_results.append(data)
        if data["status"] != "OK":
            print(f"{sym:<14} | {'N/A':<11} | {'N/A':<6} | {'ERROR':<12} | {data.get('error', 'No data')[:20]}")
            continue

        sym_str = data["symbol"]
        price = data["price"]
        rsi = data["rsi"]
        sig = data["signal"]

        action_desc = "WAIT (Monitoring)"
        if sig == "BUY":
            # Position Sizing: Risk INR 500 per trade based on ATR distance
            risk_per_trade = INITIAL_CAPITAL * 0.05  # 5% of base capital = INR 500
            atr = data["atr"]
            stop_distance = max(price - data["stop_loss"], atr)
            shares = int(risk_per_trade / stop_distance)
            
            # Constrain by max capital per position (20% of buying power = INR 10,000)
            max_shares = int((BUYING_POWER * 0.20) / price)
            shares = max(1, min(shares, max_shares))
            position_value = shares * price

            # Pass through Risk Engine Gate
            eval_res = risk_engine.evaluate(
                symbol=sym_str,
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
                    symbol=sym_str,
                    side=OrderSide.BUY,
                    quantity=eval_res.approved_quantity,
                    price=price,
                    stop_loss=data["stop_loss"],
                )
                if fill is not None:
                    action_desc = f"FILLED {shares} shs @ {fill.fill_price:.2f}"
                    executed_trades.append({
                        "symbol": sym_str,
                        "quantity": shares,
                        "price": fill.fill_price,
                        "stop_loss": data["stop_loss"],
                        "target": data["target"],
                        "position_value": shares * fill.fill_price,
                        "margin_used": (shares * fill.fill_price) / LEVERAGE,
                    })
                else:
                    action_desc = f"ORDER {order.state.value}"
            else:
                action_desc = f"REJECTED: {eval_res.rejection_code.value}"

        print(f"{sym_str:<14} | {price:>11.2f} | {rsi:>6.1f} | {sig:<12} | {action_desc}")

    # Mark portfolio to current market prices
    market_prices = {r["symbol"]: r["price"] for r in scan_results if r["status"] == "OK"}
    session.portfolio.mark_to_market(market_prices)

    # 3. Continuous Risk Audit
    audit_report = risk_auditor.audit_portfolio(
        portfolio_equity=session.portfolio.total_equity,
        realized_daily_loss_pct=0.0,
        current_drawdown_pct=session.portfolio.max_drawdown_pct,
        open_positions=[
            {"symbol": p.symbol, "market_value": p.market_value}
            for p in session.portfolio.positions.values()
        ],
    )

    # 4. Display Session Summary
    print("\n" + "=" * 70)
    print("                  PAPER TRADING SESSION SUMMARY                 ")
    print("=" * 70)
    total_pos_value = session.portfolio.market_value_of_positions
    total_margin_used = total_pos_value / LEVERAGE
    available_margin = max(0.0, INITIAL_CAPITAL - total_margin_used)

    print(f"  Account Status:              {session.status.value}")
    print(f"  Initial Equity:              INR {INITIAL_CAPITAL:,.2f}")
    print(f"  Leverage Applied:            {LEVERAGE:.0f}x")
    print(f"  Max Purchasing Power:        INR {BUYING_POWER:,.2f}")
    print(f"  Total Position Value:        INR {total_pos_value:,.2f}")
    print(f"  Margin Utilized:             INR {total_margin_used:,.2f} ({(total_margin_used/INITIAL_CAPITAL)*100:.1f}%)")
    print(f"  Available Margin Remaining:  INR {available_margin:,.2f}")
    print(f"  Total Slippage & Fees Paid:  INR {session.portfolio.total_fees_paid + session.portfolio.total_slippage_paid:,.2f}")
    print(f"  Current Unrealized PnL:      INR {session.portfolio.total_unrealized_pnl:+,.2f}")
    print(f"  Audit Compliance Status:     {audit_report.status.value}")
    
    if executed_trades:
        print("\n  Active Paper Positions:")
        for t in executed_trades:
            print(f"    • {t['symbol']}: {t['quantity']} shares @ INR {t['price']:.2f} | SL: {t['stop_loss']} | Target: {t['target']} | Margin: INR {t['margin_used']:.2f}")
    else:
        print("\n  Active Paper Positions:      None (Waiting for favorable market setup)")

    print("=" * 70)


if __name__ == "__main__":
    main()
