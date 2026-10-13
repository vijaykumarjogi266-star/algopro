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
import sqlite3
import time
import math
from enum import Enum
from datetime import datetime, timezone, timedelta, date
from typing import Dict, Optional, Tuple, Any
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Indian Standard Time (IST, UTC+5:30)
IST_TZ = timezone(timedelta(hours=5, minutes=30))


def get_ist_now(now_dt: Optional[datetime] = None) -> datetime:
    """Return datetime in Indian Standard Time (IST)."""
    if now_dt is None:
        now_dt = datetime.now(timezone.utc)
    elif now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)
    return now_dt.astimezone(IST_TZ)


def get_ist_session_date(now_dt: Optional[datetime] = None) -> str:
    """Return the current IST exchange trading session date formatted as YYYY-MM-DD."""
    return get_ist_now(now_dt).strftime("%Y-%m-%d")


class DaemonPhase(str, Enum):
    PREMARKET = "PREMARKET"
    REGULAR = "REGULAR"
    POST_MARKET_EOD = "POST_MARKET_EOD"
    MAINTENANCE = "MAINTENANCE"


def get_daemon_phase(
    dt_ist: Optional[datetime] = None,
    is_market_day: bool = True,
) -> DaemonPhase:
    """Return the scheduled daemon phase based on IST time.

    Phases:
      PREMARKET:       09:00 - 09:15 IST (on market day)
      REGULAR:         09:15 - 15:15 IST (on market day)
      POST_MARKET_EOD: 15:15 - 15:30 IST (on market day)
      MAINTENANCE:     All other times, weekends, and holidays
    """
    if not is_market_day:
        return DaemonPhase.MAINTENANCE
    ist_dt = get_ist_now(dt_ist)
    minutes = ist_dt.hour * 60 + ist_dt.minute
    if 9 * 60 <= minutes < 9 * 60 + 15:
        return DaemonPhase.PREMARKET
    elif 9 * 60 + 15 <= minutes < 15 * 60 + 15:
        return DaemonPhase.REGULAR
    elif 15 * 60 + 15 <= minutes < 15 * 60 + 30:
        return DaemonPhase.POST_MARKET_EOD
    else:
        return DaemonPhase.MAINTENANCE


def validate_manifest(
    manifest: Optional[dict],
    current_session_date: str,
) -> Tuple[bool, Optional[str]]:
    """Validate Strategy Allocation Manifest.

    Checks:
    1. Manifest is present and selected_strategy != 'WAIT'.
    2. risk_multiplier is finite and > 0.
    3. Target session date matches current trading session date exactly.
    """
    if not manifest or not isinstance(manifest, dict):
        return False, "Missing or non-dict manifest"
    strat = manifest.get("selected_strategy")
    if not strat or strat == "WAIT":
        return False, f"Strategy is WAIT or empty: {strat}"
    rm = manifest.get("risk_multiplier")
    if not isinstance(rm, (int, float)) or not math.isfinite(rm) or rm <= 0:
        return False, f"Invalid risk multiplier: {rm}"
    target_date = manifest.get("target_session_date") or manifest.get("session_date") or manifest.get("date")
    if not target_date or target_date != current_session_date:
        return False, f"Target session date '{target_date}' does not match current session '{current_session_date}'"
    return True, None


# Lazy yfinance import helper to prevent import-time failure
def _get_yf():
    try:
        import yfinance as yf
        return yf
    except ImportError:
        return None


from data.schemas.contracts import Exchange, TimeFrame
from services.risk_engine.engine import RiskEngine
from services.risk_engine.contracts import HardRiskLimits
from services.risk_engine.audit import ContinuousRiskAuditor
from services.risk_engine.hooks import ValueAtRiskFilter
from services.paper_engine.session import PaperTradingEngine, SessionStatus
from services.paper_engine.autonomous_orchestrator import AutonomousSentinel
from services.observability.network_guard import NetworkConnectivityGuard
from services.backtest_engine.contracts import OrderSide, OrderType
from services.backtest_engine.execution_lifecycle import ExecutionLifecycleManager


# ---------------------------------------------------------------------------
# Risk-state computation (pure function — fully unit-testable)
# ---------------------------------------------------------------------------

def compute_risk_state(
    day_start_equity: float,
    high_water_mark: float,
    current_equity: float,
) -> Dict[str, float]:
    """Compute authoritative portfolio risk state.

    Args:
        day_start_equity: Equity at the beginning of the trading session.
        high_water_mark: Highest equity seen since strategy inception/restart.
        current_equity: Current mark-to-market portfolio value.

    Returns:
        dict with keys:
            daily_loss_pct  — fraction of day-start equity lost today (0.0 = no loss).
            drawdown_pct    — fraction below high-water mark.
            new_high_water_mark — updated HWM (monotonically non-decreasing).
    """
    new_hwm = max(high_water_mark, current_equity)
    daily_loss_pct = (
        (day_start_equity - current_equity) / day_start_equity
        if day_start_equity > 0 else 0.0
    )
    drawdown_pct = (
        (new_hwm - current_equity) / new_hwm
        if new_hwm > 0 else 0.0
    )
    return {
        "daily_loss_pct": max(0.0, daily_loss_pct),
        "drawdown_pct": max(0.0, drawdown_pct),
        "new_high_water_mark": new_hwm,
    }


# ---------------------------------------------------------------------------
# Sentinel-state SQLite persistence (survives process restarts)
# ---------------------------------------------------------------------------

def load_sentinel_state(db_path: str) -> Dict[str, dict]:
    """Load persisted sentinel state from SQLite."""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sentinel_state (
            key TEXT PRIMARY KEY,
            value REAL NOT NULL,
            updated_at TEXT NOT NULL,
            session_date TEXT,
            text_value TEXT
        )
    """)
    cursor = conn.execute("PRAGMA table_info(sentinel_state)")
    cols = [r[1] for r in cursor.fetchall()]
    if "session_date" not in cols:
        conn.execute("ALTER TABLE sentinel_state ADD COLUMN session_date TEXT")
    if "text_value" not in cols:
        conn.execute("ALTER TABLE sentinel_state ADD COLUMN text_value TEXT")
    conn.commit()

    cursor = conn.execute("SELECT key, value, updated_at, session_date, text_value FROM sentinel_state")
    rows = {}
    for r in cursor.fetchall():
        s_date = r[3] if r[3] else (r[2][:10] if r[2] else "")
        rows[r[0]] = {"value": r[1], "date": r[2][:10] if r[2] else "", "session_date": s_date, "text_value": r[4]}
    conn.close()
    return rows

_load_sentinel_state = load_sentinel_state


def save_sentinel_state(
    db_path: str,
    key: str,
    value: float,
    session_date: Optional[str] = None,
    text_value: Optional[str] = None,
) -> None:
    """Persist a sentinel state value to SQLite. Raises on database failure."""
    now_iso = datetime.now(timezone.utc).isoformat()
    if session_date is None:
        session_date = get_ist_session_date()
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sentinel_state (
            key TEXT PRIMARY KEY,
            value REAL NOT NULL,
            updated_at TEXT NOT NULL,
            session_date TEXT,
            text_value TEXT
        )
    """)
    cursor = conn.execute("PRAGMA table_info(sentinel_state)")
    cols = [r[1] for r in cursor.fetchall()]
    if "session_date" not in cols:
        conn.execute("ALTER TABLE sentinel_state ADD COLUMN session_date TEXT")
    if "text_value" not in cols:
        conn.execute("ALTER TABLE sentinel_state ADD COLUMN text_value TEXT")

    conn.execute(
        "INSERT INTO sentinel_state(key, value, updated_at, session_date, text_value) VALUES(?,?,?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at, session_date=excluded.session_date, text_value=excluded.text_value",
        (key, value, now_iso, session_date, text_value),
    )
    conn.commit()
    conn.close()

_save_sentinel_state = save_sentinel_state


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
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def scan_symbol(symbol: str) -> dict:
    yf = _get_yf()
    if yf is None:
        return {"symbol": symbol, "status": "ERROR", "error": "yfinance not installed"}
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
        bar_ts = df.index[-1]
        if hasattr(bar_ts, "to_pydatetime"):
            bar_ts = bar_ts.to_pydatetime()
        if bar_ts.tzinfo is None:
            bar_ts = bar_ts.replace(tzinfo=IST_TZ)

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
            "bar_timestamp": bar_ts,
            "rsi": latest_rsi,
            "atr": atr14,
            "signal": signal,
            "stop_loss": stop_loss,
            "target": target_price,
            "historical_returns": list(pd.Series(closes).pct_change().dropna().iloc[-25:]),
        }
    except Exception as e:
        return {"symbol": symbol, "status": "ERROR", "error": str(e)}


# ---------------------------------------------------------------------------
# Daemon Controller (encapsulates cycle state and execution)
# ---------------------------------------------------------------------------

class DaemonController:
    """Manages paper-trading daemon sessions, risk wiring, and cycle execution."""

    def __init__(
        self,
        db_path: str,
        initial_capital: float = INITIAL_CAPITAL,
        leverage: float = LEVERAGE,
        universe: Optional[list] = None,
        risk_limits: Optional[HardRiskLimits] = None,
        sentinel: Optional[AutonomousSentinel] = None,
        circuit_breaker: Optional[Any] = None,
    ):
        self.db_path = db_path
        self.initial_capital = initial_capital
        self.leverage = leverage
        self.buying_power = initial_capital * leverage
        self.universe = universe or UNIVERSE

        self.risk_limits = risk_limits or HardRiskLimits(
            max_daily_loss_pct=0.04,
            max_portfolio_drawdown_pct=0.10,
            max_capital_per_trade_pct=0.20,
            max_open_positions=4,
            enforce_mandatory_stop_loss=True,
        )
        self.var_filter = ValueAtRiskFilter(confidence_level=0.95, max_var_pct=0.035)
        self.risk_engine = RiskEngine(limits=self.risk_limits, hooks=[self.var_filter])
        self.risk_auditor = ContinuousRiskAuditor(limits=self.risk_limits)

        self.lifecycle_manager = ExecutionLifecycleManager(risk_engine=self.risk_engine)
        self.circuit_breaker = circuit_breaker
        self.paper_engine = PaperTradingEngine(
            self.db_path,
            lifecycle_manager=self.lifecycle_manager,
            circuit_breaker=self.circuit_breaker,
        )

        self.sentinel = sentinel or AutonomousSentinel(
            db_path=self.db_path,
            max_daily_drawdown_pct=0.025,
            initial_capital=self.buying_power,
        )

        self.session = None
        self.day_start_equity = self.buying_power
        self.high_water_mark = self.buying_power
        self.current_session_date = None
        self.trade_stops = {}
        self.trade_targets = {}
        self.trade_entry_times = {}
        self.last_valid_quotes: Dict[str, float] = {}

        self._is_emergency_halted = False
        self._emergency_halt_reason: Optional[str] = None

    @property
    def is_halted(self) -> bool:
        if self.circuit_breaker is not None and getattr(self.circuit_breaker, "is_halted", False):
            return True
        return self._is_emergency_halted

    @property
    def halt_reason(self) -> Optional[str]:
        if self.circuit_breaker is not None and getattr(self.circuit_breaker, "is_halted", False):
            reasons = getattr(self.circuit_breaker, "trip_reasons", [])
            return ", ".join(reasons) if reasons else "CIRCUIT_BREAKER_EMERGENCY_HALT"
        return self._emergency_halt_reason

    def trigger_emergency_halt(self, reason: str = "MANUAL_EMERGENCY_HALT") -> None:
        self._is_emergency_halted = True
        self._emergency_halt_reason = reason
        if self.circuit_breaker is not None:
            self.circuit_breaker.trigger_emergency_halt(reason)
        save_sentinel_state(self.db_path, "emergency_halt", 1.0, session_date=self.current_session_date, text_value=reason)

    def admin_rearm(self, auth_token: str) -> bool:
        cb_ok = True
        if self.circuit_breaker is not None:
            cb_ok = self.circuit_breaker.admin_rearm(auth_token)
        if cb_ok:
            self._is_emergency_halted = False
            self._emergency_halt_reason = None
            self.sentinel.is_killswitch_tripped = False
            save_sentinel_state(self.db_path, "emergency_halt", 0.0, session_date=self.current_session_date, text_value="")
            return True
        return False

    def get_phase(self, current_time: Optional[datetime] = None) -> DaemonPhase:
        ist_now = get_ist_now(current_time)
        is_mkt = self.sentinel.is_market_day(ist_now)
        return get_daemon_phase(ist_now, is_mkt)

    def square_off_open_positions(
        self,
        market_prices: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """Square off open intraday paper positions using last available valid quotes.

        Principle: If market closed or no valid quote exists, log error rather than inventing synthetic quotes.
        """
        prices = market_prices or {}
        squared_off = []
        errors = []

        if not self.session or not self.session.portfolio.positions:
            return {"squared_off": squared_off, "errors": errors, "remaining": 0}

        for sym, pos in list(self.session.portfolio.positions.items()):
            if pos.quantity <= 0:
                continue

            sym_key = sym.upper()
            quote_price = (
                prices.get(sym)
                or prices.get(sym_key)
                or self.last_valid_quotes.get(sym)
                or self.last_valid_quotes.get(sym_key)
            )

            if (
                quote_price is None
                or not isinstance(quote_price, (int, float))
                or not math.isfinite(quote_price)
                or quote_price <= 0
            ):
                err_msg = f"Cannot square off {sym}: no valid quote available. Refusing to invent synthetic quote."
                log_msg(f"[ERROR] {err_msg}")
                errors.append({"symbol": sym, "error": err_msg})
                continue

            try:
                order, fill = self.paper_engine.submit_manual_order(
                    session_id=self.session.session_id,
                    symbol=sym,
                    side=OrderSide.SELL,
                    quantity=pos.quantity,
                    price=float(quote_price),
                )
                self.session = self.paper_engine.get_session(self.session.session_id)
                self.trade_stops.pop(sym_key, None)
                self.trade_targets.pop(sym_key, None)
                self.trade_entry_times.pop(sym_key, None)
                squared_off.append({
                    "symbol": sym,
                    "quantity": pos.quantity,
                    "price": float(quote_price),
                    "fill": fill is not None,
                })
                log_msg(f"[SQUARE-OFF] Squared off {pos.quantity} of {sym} at valid quote INR {quote_price:.2f}.")
            except Exception as e:
                err_msg = f"Failed to submit square-off order for {sym}: {e}"
                log_msg(f"[ERROR] {err_msg}")
                errors.append({"symbol": sym, "error": err_msg})

        return {
            "squared_off": squared_off,
            "errors": errors,
            "remaining": len(self.session.portfolio.positions),
        }

    def initialize_session(
        self,
        current_time: Optional[datetime] = None,
        current_equity: Optional[float] = None,
    ) -> None:
        """Initialize or resume trading session, restoring authoritative baselines."""
        ist_now = get_ist_now(current_time)
        self.current_session_date = ist_now.strftime("%Y-%m-%d")

        sessions = self.paper_engine.list_sessions()
        for s in sessions:
            if s.status == SessionStatus.RUNNING:
                self.session = self.paper_engine.get_session(s.session_id)
                break

        if not self.session:
            self.session = self.paper_engine.create_session(
                name="Persistent Live Paper Session",
                strategy_id="strat_daemon_5x",
                universe=self.universe,
                initial_capital=self.buying_power,
            )
            self.paper_engine.start_session(self.session.session_id)

        eq = current_equity if current_equity is not None else self.session.portfolio.total_equity

        # Load persisted sentinel state
        state = load_sentinel_state(self.db_path)
        if "day_start_equity" in state and state["day_start_equity"].get("session_date") == self.current_session_date:
            self.day_start_equity = float(state["day_start_equity"]["value"])
        else:
            self.day_start_equity = eq
            save_sentinel_state(self.db_path, "day_start_equity", self.day_start_equity, session_date=self.current_session_date)

        self.sentinel.daily_starting_equity = self.day_start_equity

        if "high_water_mark" in state:
            self.high_water_mark = max(float(state["high_water_mark"]["value"]), eq)
        else:
            self.high_water_mark = eq
        save_sentinel_state(self.db_path, "high_water_mark", self.high_water_mark, session_date=self.current_session_date)

        # Restore emergency halt if persisted
        if "emergency_halt" in state and float(state["emergency_halt"]["value"]) > 0:
            self._is_emergency_halted = True
            self._emergency_halt_reason = state["emergency_halt"].get("text_value") or "PERSISTED_EMERGENCY_HALT"

    def on_session_check(
        self,
        current_time: Optional[datetime] = None,
        current_equity: Optional[float] = None,
    ) -> None:
        """Check for IST session rollover and reset daily baseline once."""
        ist_now = get_ist_now(current_time)
        session_date = ist_now.strftime("%Y-%m-%d")
        eq = (
            current_equity
            if current_equity is not None
            else (self.session.portfolio.total_equity if self.session else self.buying_power)
        )

        if self.current_session_date != session_date:
            # Session rollover
            self.current_session_date = session_date
            self.day_start_equity = eq
            self.sentinel.daily_starting_equity = eq
            if self.session:
                self.session.portfolio.reset_daily_metrics(eq)
                self.paper_engine._persist_session(self.session)

            # Emergency halts persist across daily rollover until explicit admin rearm!
            if not self.is_halted and not self._is_emergency_halted:
                self.sentinel.is_killswitch_tripped = False
            else:
                log_msg(f"[ROLLOVER] Emergency halt persists across rollover: {self.halt_reason}")

            save_sentinel_state(self.db_path, "day_start_equity", self.day_start_equity, session_date=self.current_session_date)
            # High-water mark is NOT reset
            self.high_water_mark = max(self.high_water_mark, eq)
            save_sentinel_state(self.db_path, "high_water_mark", self.high_water_mark, session_date=self.current_session_date)

    def run_cycle(
        self,
        scan_results: Optional[Dict[str, dict]] = None,
        current_time: Optional[datetime] = None,
    ) -> dict:
        """Execute a single scan-risk-trade cycle deterministically."""
        if self.session is None:
            self.initialize_session(current_time=current_time)

        ist_now = get_ist_now(current_time)
        self.on_session_check(current_time=current_time)
        phase = self.get_phase(ist_now)

        # Check circuit breaker / emergency halt FIRST
        if self.is_halted:
            log_msg(f"[HALTED] Daemon trading is paused due to emergency halt: {self.halt_reason}")
            return {
                "status": "HALTED",
                "phase": phase.value,
                "reason": self.halt_reason,
                "current_equity": self.session.portfolio.total_equity,
                "open_positions": len(self.session.portfolio.positions),
            }

        results = scan_results or {}
        if scan_results is None:
            for sym in self.universe:
                results[sym] = scan_symbol(sym)

        market_prices = {}
        for sym, data in results.items():
            if data.get("status") == "OK" and "price" in data:
                price_val = data["price"]
                market_prices[sym] = price_val
                self.last_valid_quotes[sym] = price_val
                self.last_valid_quotes[sym.upper()] = price_val

        # STEP 1: Mark-to-market EXISTING POSITIONS FIRST with validated fresh data
        if market_prices:
            self.session.portfolio.mark_to_market(market_prices)

        current_equity = self.session.portfolio.total_equity

        # STEP 2: Compute authoritative risk state
        risk_state = compute_risk_state(
            day_start_equity=self.day_start_equity,
            high_water_mark=self.high_water_mark,
            current_equity=current_equity,
        )
        self.high_water_mark = risk_state["new_high_water_mark"]

        # STEP 3: Persist HWM on EVERY valid cycle, including WAIT-only cycles!
        try:
            save_sentinel_state(
                self.db_path,
                "high_water_mark",
                self.high_water_mark,
                session_date=self.current_session_date,
            )
        except Exception as exc:
            # Fail closed on state storage failure
            self.sentinel.is_killswitch_tripped = True
            log_msg(f"[ERROR] State storage failure: {exc}. Trips killswitch.")
            return {
                "status": "STORAGE_FAILURE",
                "storage_error": str(exc),
                "current_equity": current_equity,
                "daily_loss_pct": risk_state["daily_loss_pct"],
                "drawdown_pct": risk_state["drawdown_pct"],
            }

        # STEP 4: Check Sentinel daily drawdown killswitch
        self.sentinel.check_daily_drawdown_killswitch(current_equity)

        # MANDATORY 15:15 IST SQUARE-OFF
        is_market_day = self.sentinel.is_market_day(ist_now)
        time_minutes = ist_now.hour * 60 + ist_now.minute
        is_square_off_time = is_market_day and time_minutes >= (15 * 60 + 15)

        if is_square_off_time:
            log_msg(f"[EOD] Mandatory 15:15 IST square-off active (IST {ist_now.strftime('%H:%M')}).")
            square_off_res = self.square_off_open_positions(market_prices=market_prices)
            return {
                "status": "SQUARE_OFF_COMPLETED" if not square_off_res["errors"] else "SQUARE_OFF_PARTIAL",
                "phase": phase.value,
                "current_equity": self.session.portfolio.total_equity,
                "daily_loss_pct": risk_state["daily_loss_pct"],
                "drawdown_pct": risk_state["drawdown_pct"],
                "high_water_mark": self.high_water_mark,
                "open_positions": len(self.session.portfolio.positions),
                "squared_off": square_off_res["squared_off"],
                "square_off_errors": square_off_res["errors"],
            }

        # If not regular trading phase (e.g. PREMARKET or MAINTENANCE), do not enter trades
        if phase != DaemonPhase.REGULAR:
            return {
                "status": f"PHASE_{phase.value}",
                "phase": phase.value,
                "current_equity": current_equity,
                "daily_loss_pct": risk_state["daily_loss_pct"],
                "drawdown_pct": risk_state["drawdown_pct"],
                "high_water_mark": self.high_water_mark,
                "open_positions": len(self.session.portfolio.positions),
            }

        # STEP 5: Manage active positions (protective exits: SL / TP) during regular trading
        for sym, data in results.items():
            if data.get("status") != "OK":
                continue
            sym_key = sym.upper()
            pos = self.session.portfolio.positions.get(sym_key)
            if pos and pos.quantity > 0:
                current_sl = self.trade_stops.get(sym_key, pos.average_entry_price * 0.98)
                current_tp = self.trade_targets.get(sym_key, pos.average_entry_price * 1.03)

                bar_ts = data.get("bar_timestamp")
                entry_ts = self.trade_entry_times.get(sym_key)

                # Pre-entry hourly extreme cannot trigger exit if bar started before or at entry
                if bar_ts and entry_ts and bar_ts <= entry_ts:
                    low_eval = data["price"]
                    high_eval = data["price"]
                else:
                    low_eval = data.get("low", data["price"])
                    high_eval = data.get("high", data["price"])

                if low_eval <= current_sl:
                    order, fill = self.paper_engine.submit_manual_order(
                        session_id=self.session.session_id,
                        symbol=sym,
                        side=OrderSide.SELL,
                        quantity=pos.quantity,
                        price=current_sl,
                    )
                    self.session = self.paper_engine.get_session(self.session.session_id)
                    self.trade_stops.pop(sym_key, None)
                    self.trade_targets.pop(sym_key, None)
                    self.trade_entry_times.pop(sym_key, None)
                elif high_eval >= current_tp:
                    order, fill = self.paper_engine.submit_manual_order(
                        session_id=self.session.session_id,
                        symbol=sym,
                        side=OrderSide.SELL,
                        quantity=pos.quantity,
                        price=current_tp,
                    )
                    self.session = self.paper_engine.get_session(self.session.session_id)
                    self.trade_stops.pop(sym_key, None)
                    self.trade_targets.pop(sym_key, None)
                    self.trade_entry_times.pop(sym_key, None)

        # STEP 6: Check Strategy Allocation Manifest before admitting any BUY orders
        manifest = self.sentinel.get_latest_strategy_decision(current_ist_date=self.current_session_date)
        is_manifest_valid, _ = validate_manifest(manifest, self.current_session_date)

        # STEP 7: Process BUY signals
        for sym, data in results.items():
            if data.get("status") != "OK" or data.get("signal") != "BUY":
                continue
            sym_key = sym.upper()
            price = data["price"]

            if not is_manifest_valid:
                continue
            if self.sentinel.is_killswitch_tripped:
                continue
            if self.is_halted:
                continue
            if len(self.session.portfolio.positions) >= self.risk_limits.max_open_positions:
                continue

            risk_mult = manifest.get("risk_multiplier", 1.0)
            risk_per_trade = self.initial_capital * 0.05 * risk_mult
            stop_dist = max(price - data.get("stop_loss", price * 0.98), data.get("atr", price * 0.01))
            shares = int(risk_per_trade / stop_dist) if stop_dist > 0 else 1
            max_shares = int((min(current_equity, self.buying_power) * 0.19) / price)
            shares = max(1, min(shares, max_shares))

            eval_res = self.risk_engine.evaluate(
                symbol=sym,
                price=price,
                proposed_quantity=shares,
                stop_loss=data.get("stop_loss"),
                current_portfolio_value=current_equity,
                current_daily_loss_pct=risk_state["daily_loss_pct"],
                current_drawdown_pct=risk_state["drawdown_pct"],
                current_open_positions_count=len(self.session.portfolio.positions),
                context={"historical_returns": data.get("historical_returns", [0.01] * 25)},
            )

            if eval_res.is_approved:
                order, fill = self.paper_engine.submit_manual_order(
                    session_id=self.session.session_id,
                    symbol=sym,
                    side=OrderSide.BUY,
                    quantity=eval_res.approved_quantity,
                    price=price,
                    stop_loss=data.get("stop_loss"),
                )
                self.session = self.paper_engine.get_session(self.session.session_id)
                if fill:
                    self.trade_stops[sym_key] = data.get("stop_loss")
                    self.trade_targets[sym_key] = data.get("target")
                    self.trade_entry_times[sym_key] = ist_now

        return {
            "status": "OK",
            "phase": phase.value,
            "current_equity": current_equity,
            "daily_loss_pct": risk_state["daily_loss_pct"],
            "drawdown_pct": risk_state["drawdown_pct"],
            "high_water_mark": self.high_water_mark,
            "open_positions": len(self.session.portfolio.positions),
        }


# ---------------------------------------------------------------------------
# Daemon Entry Point
# ---------------------------------------------------------------------------

running = True


def handle_shutdown(signum, frame):
    global running
    print(f"\n[DAEMON] Received signal {signum}. Initiating graceful shutdown...", flush=True)
    running = False


def main():
    import signal
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

    log_msg("=" * 65)
    log_msg("ALGO LAB — PERSISTENT LIVE PAPER TRADING DAEMON STARTED")
    log_msg(f"Base Capital: INR {INITIAL_CAPITAL:,.2f} | Leverage: {LEVERAGE:.0f}x | Buying Power: INR {BUYING_POWER:,.2f}")
    log_msg(f"Database: {DB_PATH}")
    log_msg(f"Scan Interval: {SCAN_INTERVAL_SECONDS} seconds")
    log_msg("=" * 65)

    controller = DaemonController(db_path=DB_PATH, initial_capital=INITIAL_CAPITAL, leverage=LEVERAGE)
    controller.initialize_session()

    net_guard = NetworkConnectivityGuard()
    cycle = 0

    while running:
        cycle += 1

        is_online, net_changed, outage_dur = net_guard.probe()
        if net_changed and not is_online:
            log_msg("[NETWORK ALERT] WAN connection lost. Freezing trade proposals.")
        elif net_changed and is_online:
            log_msg(f"[NETWORK RECOVERED] WAN connectivity restored after {outage_dur:.1f}s.")

        if not is_online:
            for _ in range(SCAN_INTERVAL_SECONDS):
                if not running:
                    break
                time.sleep(1)
            continue

        now_ist = get_ist_now()
        ist_hour = now_ist.hour
        ist_minute = now_ist.minute
        phase = controller.get_phase(now_ist)
        is_market_day = controller.sentinel.is_market_day(now_ist)
        is_market_open = is_market_day and (phase == DaemonPhase.REGULAR or phase == DaemonPhase.POST_MARKET_EOD)

        if controller.is_halted:
            if cycle % 10 == 1:
                log_msg(f"[HALTED] Daemon trading paused due to emergency halt: {controller.halt_reason}")
            for _ in range(SCAN_INTERVAL_SECONDS):
                if not running:
                    break
                time.sleep(1)
            continue

        # Scheduled pre-market maintenance
        if ist_hour == 8 and 30 <= ist_minute <= 35:
            if not getattr(controller.sentinel, "_premarket_executed_today", False):
                controller.sentinel.execute_pre_market_maintenance()
                controller.sentinel._premarket_executed_today = True
        elif ist_hour != 8:
            controller.sentinel._premarket_executed_today = False

        # Scheduled post-market EOD audit
        if ist_hour == 15 and 35 <= ist_minute < 40:
            if not getattr(controller.sentinel, "_eod_dispatched_today", False):
                pos_dict = {
                    sym: {
                        "quantity": pos.quantity,
                        "avg_price": pos.average_entry_price,
                        "current_price": pos.current_price,
                        "cost_basis": pos.cost_basis,
                    }
                    for sym, pos in controller.session.portfolio.positions.items()
                }
                controller.sentinel.execute_eod_reconciliation_and_tearsheet(
                    portfolio_equity=controller.session.portfolio.total_equity,
                    open_positions_count=len(controller.session.portfolio.positions),
                    cash=controller.session.portfolio.cash,
                    realized_pnl=controller.session.portfolio.total_realized_pnl,
                    total_fees=controller.session.portfolio.total_fees_paid,
                    total_slippage=controller.session.portfolio.total_slippage_paid,
                    positions=pos_dict,
                )
                controller.sentinel._eod_dispatched_today = True
        elif ist_hour != 15:
            controller.sentinel._eod_dispatched_today = False

        # Standby mode outside market hours
        if not is_market_open:
            if cycle % 10 == 1:
                status_str = "NSE market closed" if is_market_day else "Weekend / NSE holiday"
                log_msg(f"[STANDBY] {status_str} (IST {ist_hour:02d}:{ist_minute:02d}).")
            for _ in range(SCAN_INTERVAL_SECONDS):
                if not running:
                    break
                time.sleep(1)
            continue

        # Execute cycle
        log_msg(f"--- Cycle #{cycle}: Active Market Scan (IST {ist_hour:02d}:{ist_minute:02d}) ---")
        summary = controller.run_cycle(current_time=now_ist)
        log_msg(f"Portfolio Status: Equity=INR {summary.get('current_equity', 0):,.2f} | Open Positions={summary.get('open_positions', 0)}")

        for _ in range(SCAN_INTERVAL_SECONDS):
            if not running:
                break
            time.sleep(1)

    log_msg("[SHUTDOWN] Paper trading daemon exiting gracefully.")


if __name__ == "__main__":
    main()
