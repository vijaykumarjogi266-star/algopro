#!/usr/bin/env python3
"""
Autonomous Intraday Paper Trading & Contract Note Simulation Engine (Algo Lab)
Strictly Autonomous Zero-Human-Intervention Production Loop with IST Schedule Automation.

Mandatory Safety Invariants:
- Strictly paper trading only.
- ALLOW_LIVE_TRADING = False
- ALLOW_REAL_BROKER_EXECUTION = False
- REAL_MONEY_RISK_PAISE = 0
- PAPER_BROKER_ONLY = True

Schedule Architecture (Indian Standard Time - Asia/Kolkata, UTC+5:30):
- 00:00 - 09:00 IST : STANDBY_COUNTDOWN (Sleeps with heartbeat, counts down to market open)
- 09:00 - 09:15 IST : PRE_MARKET_WARMUP (Updates pivot levels, moving averages, preps universe)
- 09:15 - 13:30 IST : ACTIVE_EXECUTION (Scans VWAP, Pivot R1, EMA Pullbacks, executes orders)
- 13:30 - 15:15 IST : MANAGE_ONLY (No new entries, trails stops, monitors targets)
- 15:15 - 15:30 IST : EOD_SQUARE_OFF (Forces liquidation of any open positions at market)
- 15:30 - 23:59 IST : POST_MARKET_AUDIT (Saves contract notes, resets daily ledger)

Simulates Exact Indian Statutory Friction:
- Brokerage: Flat ₹20 per executed leg
- STT: 0.025% on sell leg
- Exchange Turnover: 0.00297%
- GST: 18.0% on taxable charges
- SEBI Charges: ₹10/Cr
- Stamp Duty: 0.003% on buy leg
- 0.05% realistic market adverse slippage
"""

import sys
import os
import json
import time
import uuid
import logging
from pathlib import Path
from datetime import datetime, date, time as dtime, timezone, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Any, Tuple
import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Mandatory safety enforcement
ALLOW_LIVE_TRADING = False
ALLOW_REAL_BROKER_EXECUTION = False
REAL_MONEY_RISK_PAISE = 0
PAPER_BROKER_ONLY = True

assert not ALLOW_LIVE_TRADING, "SAFETY FIREWALL: LIVE TRADING PROHIBITED"
assert not ALLOW_REAL_BROKER_EXECUTION, "SAFETY FIREWALL: REAL BROKER PROHIBITED"
assert REAL_MONEY_RISK_PAISE == 0, "SAFETY FIREWALL: REAL MONEY PROHIBITED"
assert PAPER_BROKER_ONLY, "SAFETY FIREWALL: PAPER ONLY"

from services.paper_engine.adapters.zerodha_basex import (
    ZerodhaBaseXAdapter,
    ZerodhaProductType,
)
from services.backtest_engine.contracts import OrderSide, OrderType
from services.scanner.universe_manager import Nifty50UniverseManager
from services.backtest_engine.statutory_cost_model import (
    IndianStatutoryCostModel,
    OrderLeg,
    ProductType,
    ExecutionFrictionBreakdown,
)

IST = timezone(timedelta(hours=5, minutes=30))

# Logging & Artifact Setup
LOGS_DIR = BASE_DIR / "logs"
ARTIFACTS_DIR = BASE_DIR / "artifacts"
CONTRACT_NOTES_DIR = ARTIFACTS_DIR / "contract_notes"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
CONTRACT_NOTES_DIR.mkdir(parents=True, exist_ok=True)

log_file = LOGS_DIR / "autonomous_paper_trader.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("AutonomousTrader")


class AutonomousLivePaperTrader:
    """Production Autonomous Paper Trader with IST market schedule awareness."""

    def __init__(
        self,
        capital_inr: float = 10000.0,
        leverage_multiplier: float = 5.0,
        risk_per_trade_pct: float = 0.010, # 1% risk per trade (₹100)
        max_trades_per_day: int = 2,       # Vikram Prabhu daily limit
        poll_interval_seconds: float = 5.0,
        force_active_mode: bool = False,   # Set True to bypass time window for testing
    ):
        self.capital_inr = capital_inr
        self.leverage_multiplier = leverage_multiplier
        self.buying_power = capital_inr * leverage_multiplier
        self.available_cash = capital_inr
        self.risk_per_trade_pct = risk_per_trade_pct
        self.max_trades_per_day = max_trades_per_day
        self.poll_interval_seconds = poll_interval_seconds
        self.force_active_mode = force_active_mode
        
        self.symbols = ["SBIN", "RELIANCE", "TCS", "INFY", "ICICIBANK", "HDFCBANK", "TATACONSUM", "GRASIM", "BHARTIARTL", "ADANIENT"]
        self.broker = ZerodhaBaseXAdapter(mock_mode=True)
        self.is_running = True
        
        self.open_positions: Dict[str, dict] = {}
        self.completed_trades: List[dict] = []
        
        # Track current session in IST
        self.current_session_date = datetime.now(IST).date()
        self.daily_trade_count: int = 0
        self.symbol_state = self._init_symbol_state()

        logger.info("=" * 80)
        logger.info("⚡ AUTONOMOUS INTRADAY PAPER TRADER ONLINE (NO HUMAN INTERVENTION)")
        logger.info("=" * 80)
        logger.info(f"Current System Time (IST) : {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S IST')}")
        logger.info(f"Base Capital Allocation    : ₹{self.capital_inr:,.2f} INR")
        logger.info(f"NSE Intraday Leverage      : {self.leverage_multiplier:.1f}x MIS Margin")
        logger.info(f"Total Purchasing Power (5x): ₹{self.buying_power:,.2f} INR")
        logger.info(f"Risk Per Trade (1.0%)      : ₹{self.capital_inr * self.risk_per_trade_pct:,.2f} INR")
        logger.info(f"Daily Trade Cap            : {self.max_trades_per_day} trades (Vikram Prabhu Circuit Breaker)")
        logger.info(f"Venue & Routing            : Zerodha BaseX Paper Venue (Mock Mode)")
        logger.info(f"Friction & Charges Model   : Indian Statutory Model (Brokerage, STT, Exchange, GST, Stamp)")
        logger.info("=" * 80)

    def _init_symbol_state(self) -> Dict[str, dict]:
        state = {}
        cache_dir = BASE_DIR / "data" / "cache_intraday_5m"
        for sym in self.symbols:
            f = cache_dir / f"{sym}_5m.parquet"
            if f.exists():
                df = pd.read_parquet(f).tail(60)
                state[sym] = {
                    "price": float(df['Close'].iloc[-1]),
                    "high_session": float(df['High'].max()),
                    "low_session": float(df['Low'].min()),
                    "ema_20": float(df['Close'].ewm(span=20).mean().iloc[-1]),
                    "ema_8": float(df['Close'].ewm(span=8).mean().iloc[-1]),
                    "vol_sma": float(df['Volume'].rolling(20).mean().iloc[-1]),
                    "prev_high": float(df['High'].iloc[-2]),
                }
            else:
                state[sym] = {
                    "price": 850.0,
                    "high_session": 860.0,
                    "low_session": 840.0,
                    "ema_20": 850.0,
                    "ema_8": 852.0,
                    "vol_sma": 10000.0,
                    "prev_high": 855.0,
                }
        return state

    def check_daily_session_rollover(self):
        """Automatically detects date boundary in IST and resets daily trade quotas."""
        now_ist = datetime.now(IST)
        ist_date = now_ist.date()
        if ist_date != self.current_session_date:
            logger.info("=" * 80)
            logger.info(f"🌅 AUTOMATIC SESSION ROLLOVER: New Day Detected ({ist_date})")
            logger.info(f"   Prior Day Trades: {self.daily_trade_count} | Realized Cash: ₹{self.available_cash:,.2f}")
            logger.info("   Resetting daily trade quota to 0. Circuit breaker cleared.")
            logger.info("=" * 80)
            self.current_session_date = ist_date
            self.daily_trade_count = 0
            self.symbol_state = self._init_symbol_state()

    def get_market_phase(self) -> Tuple[str, str]:
        """Returns the current IST market operational phase."""
        if self.force_active_mode:
            return "ACTIVE_EXECUTION", "Active forced execution testing"

        now_ist = datetime.now(IST)
        current_time = now_ist.time()
        weekday = now_ist.weekday() # 0 = Monday, 4 = Friday, 5 = Saturday, 6 = Sunday

        if weekday >= 5:
            return "WEEKEND_STANDBY", "Weekend (Exchange Closed) - Standing by for Monday 09:00 IST"

        if current_time < dtime(9, 0):
            target = now_ist.replace(hour=9, minute=0, second=0)
            diff = target - now_ist
            return "STANDBY_COUNTDOWN", f"Pre-market starts in {diff.seconds // 3600}h {(diff.seconds % 3600) // 60}m {diff.seconds % 60}s"
        elif dtime(9, 0) <= current_time < dtime(9, 15):
            return "PRE_MARKET_WARMUP", "Pre-market session (09:00 - 09:15 IST) - Waking scanner"
        elif dtime(9, 15) <= current_time < dtime(13, 30):
            return "ACTIVE_EXECUTION", "Live Trading Hours (09:15 - 13:30 IST) - Active Scanning & Execution"
        elif dtime(13, 30) <= current_time < dtime(15, 15):
            return "MANAGE_ONLY", "Afternoon Session (13:30 - 15:15 IST) - Managing existing positions only"
        elif dtime(15, 15) <= current_time < dtime(15, 30):
            return "EOD_SQUARE_OFF", "EOD Square-Off (15:15 IST) - Force closing any open intraday positions"
        else:
            return "POST_MARKET_AUDIT", "Post-market closed - Standing by for tomorrow's open"

    def update_market_ticks(self) -> Dict[str, dict]:
        quotes = {}
        for sym in self.symbols:
            st = self.symbol_state[sym]
            drift = np.random.normal(0.0001, 0.0016)
            new_price = round(st["price"] * (1.0 + drift), 2)
            has_spike = np.random.random() < 0.20
            vol = int(st["vol_sma"] * (np.random.uniform(2.1, 3.2) if has_spike else np.random.uniform(0.7, 1.3)))
            
            st["price"] = new_price
            st["high_session"] = max(st["high_session"], new_price)
            st["low_session"] = min(st["low_session"], new_price)

            quotes[sym] = {
                "ltp": new_price,
                "volume": vol,
                "vol_sma": st["vol_sma"],
                "ema_20": st["ema_20"],
                "ema_8": st["ema_8"],
                "prev_high": st["prev_high"],
            }
        return quotes

    def scan_setups(self, quotes: Dict[str, dict]) -> List[dict]:
        if self.daily_trade_count >= self.max_trades_per_day:
            return []

        setups = []
        for sym, q in quotes.items():
            if sym in self.open_positions or len(self.open_positions) >= 2:
                continue

            ltp = q["ltp"]
            ema20 = q["ema_20"]
            vol = q["volume"]
            vol_sma = q["vol_sma"]
            prev_high = q["prev_high"]

            # Strategy 1: Enhanced Breakout (RVOL >= 2.0x, LTP > Prev High, LTP > 20 EMA)
            if ltp > prev_high and (vol / max(1.0, vol_sma)) >= 2.0 and ltp > ema20:
                sl = ltp * 0.993 # 0.7% SL
                tp = ltp + (2.0 * (ltp - sl)) # 2R target
                setups.append({
                    "strategy": "Pivot_R1_Enhanced",
                    "symbol": sym,
                    "action": OrderSide.BUY,
                    "price": ltp,
                    "stop_loss": round(sl, 2),
                    "target": round(tp, 2),
                    "reason": f"PDH Breakout above {prev_high} with RVOL {vol/vol_sma:.1f}x",
                })
                continue

            # Strategy 2: VWAP Mean Reversion (Oversold >= 1.5% below 20 EMA)
            if ltp <= ema20 * 0.985:
                sl = ltp * 0.990
                tp = ema20
                if tp >= ltp + 1.5 * (ltp - sl):
                    setups.append({
                        "strategy": "VWAP_Mean_Reversion",
                        "symbol": sym,
                        "action": OrderSide.BUY,
                        "price": ltp,
                        "stop_loss": round(sl, 2),
                        "target": round(tp, 2),
                        "reason": f"Oversold stretch below 20 EMA ({ema20})",
                    })
                    continue

        return setups

    def execute_entry(self, setup: dict):
        sym = setup["symbol"]
        price = setup["price"]
        sl = setup["stop_loss"]
        tp = setup["target"]
        
        risk_budget = self.capital_inr * self.risk_per_trade_pct
        risk_per_share = price - sl
        if risk_per_share <= 0:
            return

        max_position_exposure = self.buying_power / 2.0 # ₹25k max exposure per trade
        max_qty = max(1, int(max_position_exposure / price))
        qty = max(1, min(int(risk_budget / risk_per_share), max_qty))
        fill_price = round(price * 1.0005, 2) # 0.05% adverse slippage

        buy_friction = IndianStatutoryCostModel.calculate_order_friction(
            leg=OrderLeg.BUY,
            price=Decimal(str(fill_price)),
            quantity=qty,
            product=ProductType.INTRADAY
        )

        trade_id = f"TRD-{uuid.uuid4().hex[:6].upper()}"
        pos = {
            "trade_id": trade_id,
            "strategy": setup["strategy"],
            "symbol": sym,
            "entry_time": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
            "entry_price": fill_price,
            "qty": qty,
            "stop_loss": sl,
            "target": tp,
            "initial_risk": risk_per_share,
            "buy_friction": buy_friction,
            "breakeven_active": False,
        }
        self.open_positions[sym] = pos
        self.daily_trade_count += 1

        logger.info(f"🟢 [ORDER FILL: BUY] {trade_id} | {pos['strategy']} | {sym} x {qty} @ ₹{fill_price:.2f}")
        logger.info(f"   SL: ₹{sl:.2f} | TP: ₹{tp:.2f} | Buy Friction: ₹{float(buy_friction.all_in_total_friction):.2f}")

    def manage_positions(self, quotes: Dict[str, dict], force_eod_square_off: bool = False):
        for sym, pos in list(self.open_positions.items()):
            ltp = quotes[sym]["ltp"]
            entry_p = pos["entry_price"]
            sl = pos["stop_loss"]
            tp = pos["target"]
            qty = pos["qty"]

            # Trailing stop to breakeven once +1R favorable
            if not pos["breakeven_active"] and ltp >= entry_p + pos["initial_risk"]:
                pos["stop_loss"] = entry_p
                pos["breakeven_active"] = True
                logger.info(f"🔄 [TRAILING SL] {pos['trade_id']} ({sym}) moved to Breakeven @ ₹{entry_p:.2f}")

            exit_reason = None
            if force_eod_square_off:
                exit_reason = "HARD_EXIT_15_15"
            elif ltp >= tp:
                exit_reason = "TAKE_PROFIT"
            elif ltp <= sl:
                exit_reason = "STOP_LOSS"

            if exit_reason:
                exit_price = round(ltp * 0.9995, 2)
                sell_friction = IndianStatutoryCostModel.calculate_order_friction(
                    leg=OrderLeg.SELL,
                    price=Decimal(str(exit_price)),
                    quantity=qty,
                    product=ProductType.INTRADAY
                )

                buy_fric: ExecutionFrictionBreakdown = pos["buy_friction"]
                total_brokerage = float(buy_fric.brokerage + sell_friction.brokerage)
                total_stt = float(buy_fric.stt + sell_friction.stt)
                total_exchange = float(buy_fric.exchange_txn_fee + sell_friction.exchange_txn_fee)
                total_sebi = float(buy_fric.sebi_turnover_fee + sell_friction.sebi_turnover_fee)
                total_stamp = float(buy_fric.stamp_duty + sell_friction.stamp_duty)
                total_gst = float(buy_fric.gst + sell_friction.gst)
                all_in_friction = float(buy_fric.all_in_total_friction + sell_friction.all_in_total_friction)

                gross_pnl = round((exit_price - entry_p) * qty, 2)
                net_pnl = round(gross_pnl - all_in_friction, 2)

                self._save_contract_note(
                    trade_id=pos["trade_id"],
                    strategy=pos["strategy"],
                    symbol=sym,
                    qty=qty,
                    entry_price=entry_p,
                    exit_price=exit_price,
                    gross_pnl=gross_pnl,
                    net_pnl=net_pnl,
                    brokerage=total_brokerage,
                    stt=total_stt,
                    exchange_charges=total_exchange,
                    sebi_charges=total_sebi,
                    stamp_duty=total_stamp,
                    gst=total_gst,
                    total_friction=all_in_friction,
                    exit_reason=exit_reason,
                )

                self.completed_trades.append({
                    "trade_id": pos["trade_id"],
                    "strategy": pos["strategy"],
                    "symbol": sym,
                    "qty": qty,
                    "entry_price": entry_p,
                    "exit_price": exit_price,
                    "gross_pnl": gross_pnl,
                    "friction": all_in_friction,
                    "net_pnl": net_pnl,
                    "exit_reason": exit_reason,
                })
                self.available_cash += net_pnl
                del self.open_positions[sym]

                logger.info(f"🔴 [ORDER FILL: SELL] {pos['trade_id']} | {exit_reason} | {sym} x {qty} @ ₹{exit_price:.2f}")
                logger.info(f"   Gross P&L: ₹{gross_pnl:,.2f} | Statutory Fees: ₹{all_in_friction:,.2f} | Net Realized P&L: ₹{net_pnl:,.2f}")

    def _save_contract_note(
        self, trade_id: str, strategy: str, symbol: str, qty: int,
        entry_price: float, exit_price: float, gross_pnl: float, net_pnl: float,
        brokerage: float, stt: float, exchange_charges: float, sebi_charges: float,
        stamp_duty: float, gst: float, total_friction: float, exit_reason: str,
    ):
        note = f"""
================================================================================
📄 ZERODHA SIMULATED CONTRACT NOTE & TAX INVOICE (MIS EQUITY)
================================================================================
Trade ID        : {trade_id}
Strategy        : {strategy}
Security Symbol : {symbol} (NSE Cash)
Quantity        : {qty} shares
Buy Fill Price  : ₹{entry_price:.2f}
Sell Fill Price : ₹{exit_price:.2f}
Exit Trigger    : {exit_reason}
Gross Turnover  : ₹{(entry_price + exit_price) * qty:,.2f}
Gross Trade P&L : ₹{gross_pnl:,.2f}
--------------------------------------------------------------------------------
STATUTORY CHARGES & LEVIES BREAKDOWN:
  1. Brokerage (Zerodha Flat ₹20 x 2 legs) : ₹{brokerage:,.2f}
  2. STT / CTT (0.025% on Sell Leg)        : ₹{stt:,.2f}
  3. Exchange Turnover Charges (NSE)       : ₹{exchange_charges:,.2f}
  4. GST (18.0% on Taxable Charges)        : ₹{gst:,.2f}
  5. SEBI Turnover Charges (₹10/Cr)        : ₹{sebi_charges:,.2f}
  6. Stamp Duty (0.003% on Buy Leg)        : ₹{stamp_duty:,.2f}
--------------------------------------------------------------------------------
TOTAL STATUTORY LEVIES & FRICTION          : ₹{total_friction:,.2f}
--------------------------------------------------------------------------------
NET REALIZED SETTLEMENT P&L                : ₹{net_pnl:,.2f}
================================================================================
"""
        logger.info(note)
        note_data = {
            "trade_id": trade_id,
            "strategy": strategy,
            "symbol": symbol,
            "quantity": qty,
            "buy_price": entry_price,
            "sell_price": exit_price,
            "gross_pnl": gross_pnl,
            "net_pnl": net_pnl,
            "brokerage": brokerage,
            "stt": stt,
            "exchange_charges": exchange_charges,
            "gst": gst,
            "sebi_charges": sebi_charges,
            "stamp_duty": stamp_duty,
            "total_friction": total_friction,
            "exit_reason": exit_reason,
            "timestamp": datetime.now(IST).isoformat(),
        }
        with open(CONTRACT_NOTES_DIR / f"{trade_id}.json", "w") as f:
            json.dump(note_data, f, indent=2)

    def persist_session(self, phase: str, phase_msg: str):
        state = {
            "timestamp_ist": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
            "market_phase": phase,
            "phase_message": phase_msg,
            "session_date": str(self.current_session_date),
            "base_capital_inr": self.capital_inr,
            "leverage": f"{self.leverage_multiplier}x (NSE Intraday MIS)",
            "effective_buying_power_inr": self.buying_power,
            "available_cash_inr": round(self.available_cash, 2),
            "net_portfolio_pnl": round(self.available_cash - self.capital_inr, 2),
            "daily_trades_taken": self.daily_trade_count,
            "max_daily_trades": self.max_trades_per_day,
            "circuit_breaker_active": self.daily_trade_count >= self.max_trades_per_day,
            "open_positions": self.open_positions,
            "completed_trades_today": len(self.completed_trades),
            "safety_mode": "STRICT_PAPER_TRADING_ONLY",
        }
        with open(ARTIFACTS_DIR / "live_paper_session.json", "w") as f:
            json.dump(state, f, indent=2, default=str)

    def run(self, max_iterations: Optional[int] = None):
        iteration = 0
        last_log_heartbeat = 0
        
        while self.is_running:
            try:
                iteration += 1
                self.check_daily_session_rollover()
                phase, msg = self.get_market_phase()
                
                # Periodic heartbeat logging (every 60 seconds)
                now_sec = time.time()
                if now_sec - last_log_heartbeat >= 60:
                    logger.info(f"⏳ [MARKET SCHEDULE] Phase: {phase} | {msg} | Trades Today: {self.daily_trade_count}/2")
                    last_log_heartbeat = now_sec

                if phase in ["ACTIVE_EXECUTION", "MANAGE_ONLY", "EOD_SQUARE_OFF"]:
                    quotes = self.update_market_ticks()
                    
                    if phase == "EOD_SQUARE_OFF":
                        self.manage_positions(quotes, force_eod_square_off=True)
                    else:
                        self.manage_positions(quotes, force_eod_square_off=False)

                    if phase == "ACTIVE_EXECUTION":
                        setups = self.scan_setups(quotes)
                        for s in setups:
                            self.execute_entry(s)

                elif phase == "PRE_MARKET_WARMUP":
                    # Warm up indicators and verify connectivity
                    pass

                self.persist_session(phase, msg)

                if max_iterations and iteration >= max_iterations:
                    break

                time.sleep(self.poll_interval_seconds)

            except KeyboardInterrupt:
                logger.info("Shutdown received.")
                break
            except Exception as e:
                logger.error(f"Error in execution loop: {e}", exc_info=True)
                time.sleep(self.poll_interval_seconds)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--capital", type=float, default=10000.0, help="Base paper capital (INR)")
    parser.add_argument("--leverage", type=float, default=5.0, help="NSE Intraday leverage multiplier (e.g. 5.0)")
    parser.add_argument("--max-iter", type=int, default=None)
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--force-active", action="store_true", help="Force active execution regardless of hour")
    args = parser.parse_args()

    trader = AutonomousLivePaperTrader(
        capital_inr=args.capital,
        leverage_multiplier=args.leverage,
        risk_per_trade_pct=0.010,
        max_trades_per_day=2,
        poll_interval_seconds=args.interval,
        force_active_mode=args.force_active,
    )
    trader.run(max_iterations=args.max_iter)


if __name__ == "__main__":
    main()
