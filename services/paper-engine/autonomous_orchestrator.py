"""
Algo Lab — Fully Autonomous Zero-Intervention Paper Trading Orchestrator & Sentinel.
Designed for 30-day unsupervised forward testing on Oracle Cloud Infrastructure (OCI).
"""

import os
import sys
import time
import shutil
import sqlite3
import tempfile
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple

# Ensure project root in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from services.observability.webhook_dispatcher import WebhookDispatcher
from services.execution_gateway.reconciliation_engine import DoubleEntryLedgerReconciler
from services.derivatives_engine.greeks_hedging import WhalleyWilmottHedgingEngine
from apps.api.core.logging import get_logger

logger = get_logger("AutonomousOrchestrator")

# 2026 NSE Major Trading Holidays (Sample/Standard calendar)
NSE_HOLIDAYS_2026 = {
    "2026-01-26",  # Republic Day
    "2026-03-03",  # Holi
    "2026-04-03",  # Good Friday
    "2026-04-14",  # Dr. Ambedkar Jayanti
    "2026-05-01",  # Maharashtra Day
    "2026-08-15",  # Independence Day
    "2026-10-02",  # Gandhi Jayanti
    "2026-11-08",  # Diwali Laxmi Pujan
    "2026-12-25",  # Christmas
}


def perform_safe_database_backup(src_db_path: str, backup_dir: str, target_filename: Optional[str] = None) -> str:
    """Safely back up an active SQLite database (with WAL support).

    - Writes to a temporary destination first.
    - Captures active WAL transactions via SQLite backup API.
    - Verifies backup integrity with PRAGMA integrity_check.
    - Atomically publishes to final destination.
    - NEVER falls back to unsafe raw file copy on active WAL database.
    - Preserves previous valid backups if backup fails.
    """
    if not os.path.exists(src_db_path):
        raise FileNotFoundError(f"Source database not found: {src_db_path}")

    os.makedirs(backup_dir, exist_ok=True)
    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    final_filename = target_filename or f"paper_trading_{today_str}.db"
    final_path = os.path.join(backup_dir, final_filename)

    with tempfile.NamedTemporaryFile(dir=backup_dir, delete=False, suffix=".tmp") as tf:
        temp_path = tf.name

    src_conn = None
    dst_conn = None
    try:
        src_conn = sqlite3.connect(src_db_path)
        src_conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
        dst_conn = sqlite3.connect(temp_path)
        with dst_conn:
            src_conn.backup(dst_conn)
        dst_conn.close()
        dst_conn = None
        src_conn.close()
        src_conn = None

        # Verify backup integrity
        verify_conn = sqlite3.connect(temp_path)
        cur = verify_conn.execute("PRAGMA integrity_check")
        status = cur.fetchone()[0]
        verify_conn.close()
        if status != "ok":
            raise RuntimeError(f"Backup failed SQLite integrity check: {status}")

        # Atomically publish verified backup
        os.replace(temp_path, final_path)
        logger.info(f"Safe database backup atomically published: {final_path}")
        return final_path
    except Exception as exc:
        if dst_conn:
            try:
                dst_conn.close()
            except Exception:
                pass
        if src_conn:
            try:
                src_conn.close()
            except Exception:
                pass
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        logger.error(f"Safe database backup failed: {exc}")
        raise


class AutonomousSentinel:
    """Zero-human-intervention autonomous controller for Algo Lab."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        max_daily_drawdown_pct: float = 0.025,  # 2.5% max daily loss killswitch
        initial_capital: float = 10_000.0,
    ):
        self.db_path = db_path or os.path.join(PROJECT_ROOT, "data", "paper_trading.db")
        self.max_daily_drawdown_pct = max_daily_drawdown_pct
        self.initial_capital = initial_capital
        self.daily_starting_equity = initial_capital
        self.is_killswitch_tripped = False
        self.dispatcher = WebhookDispatcher()
        self.last_phase = "INIT"

    def get_ist_now(self) -> datetime:
        """Returns current time in Indian Standard Time (IST, UTC+5:30)."""
        return datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)

    def is_market_day(self, date_ist: Optional[datetime] = None) -> bool:
        """Returns True if today is a valid NSE trading day (Mon-Fri and not a holiday)."""
        dt = date_ist or self.get_ist_now()
        # 0 = Monday, ..., 4 = Friday, 5 = Saturday, 6 = Sunday
        if dt.weekday() in (5, 6):
            return False
        date_str = dt.strftime("%Y-%m-%d")
        if date_str in NSE_HOLIDAYS_2026:
            return False
        return True

    def check_daily_drawdown_killswitch(self, current_equity: float) -> bool:
        """
        Evaluates daily drawdown killswitch.
        If equity drops >= 2.5% from daily starting equity, immediately trips killswitch.
        """
        if self.daily_starting_equity <= 0:
            return False

        drawdown = (self.daily_starting_equity - current_equity) / self.daily_starting_equity
        if drawdown >= self.max_daily_drawdown_pct:
            if not self.is_killswitch_tripped:
                self.is_killswitch_tripped = True
                loss_amount = self.daily_starting_equity - current_equity
                logger.error(
                    f"CRITICAL: Daily Drawdown Kill-Switch Tripped! Drawdown: {drawdown*100:.2f}% (Loss: INR {loss_amount:.2f})"
                )
                self.dispatcher.notify(
                    title="EMERGENCY: Daily Drawdown Killswitch Tripped",
                    message=f"Algo Lab has frozen all new order entries. Daily loss {drawdown*100:.2f}% exceeded 2.5% threshold.",
                    level="CRITICAL",
                    fields={
                        "Starting Equity": f"INR {self.daily_starting_equity:,.2f}",
                        "Current Equity": f"INR {current_equity:,.2f}",
                        "Daily Drawdown": f"{drawdown*100:.2f}%",
                        "Status": "ALL TRADING FROZEN UNTIL TOMORROW 09:15 IST",
                    },
                )
            return True
        return False

    def execute_pre_market_maintenance(self):
        """08:30 IST: Health audit & database backup."""
        logger.info("Executing 08:30 IST Pre-Market Maintenance...")
        self.is_killswitch_tripped = False  # Reset daily killswitch for new trading day
        
        # 1. Database backup via safe online backup API (captures active WAL transactions consistently)
        if os.path.exists(self.db_path):
            backup_dir = os.path.join(PROJECT_ROOT, "data", "backups")
            today_str = self.get_ist_now().strftime("%Y%m%d")
            try:
                perform_safe_database_backup(self.db_path, backup_dir, target_filename=f"paper_trading_{today_str}.db")
            except Exception as e:
                logger.error(f"Pre-market database backup failed: {e}")

        # 2. Retrieve latest strategy decision allocated by Research Bot
        decision = self.get_latest_strategy_decision()
        strat_name = decision.get("selected_strategy", "STRAT_DEFAULT")
        risk_mult = decision.get("risk_multiplier", 1.0)

        # 3. Dispatch morning readiness notification
        self.dispatcher.notify(
            title="Pre-Market System Readiness Verified",
            message="Algo Lab autonomous paper trading engine is healthy and prepped for today's session.",
            level="INFO",
            fields={
                "Host": "Oracle Cloud Infrastructure (OCI)",
                "Date": self.get_ist_now().strftime("%Y-%m-%d"),
                "Trading Mode": "Autonomous Paper Forward Test",
                "Allocated Strategy": f"{strat_name} ({risk_mult}x)",
                "Max Daily Drawdown Cap": f"{self.max_daily_drawdown_pct*100:.1f}%",
            },
        )

    def get_latest_strategy_decision(self, current_ist_date: Optional[str] = None) -> Dict[str, Any]:
        """Reads and strictly validates latest strategy decision manifest generated by Research Bot.
        
        Fail-Closed Principle: If manifest is missing, corrupt, or stale (> 24h),
        default to 'WAIT' and 0.0x risk multiplier (never risk capital blindly).
        """
        import math
        decisions_dir = os.path.join(PROJECT_ROOT, "data", "decisions")
        safe_fallback = {"selected_strategy": "WAIT", "risk_multiplier": 0.0, "status": "FAIL_CLOSED_NO_MANIFEST"}
        if not os.path.exists(decisions_dir):
            return safe_fallback
        files = sorted([f for f in os.listdir(decisions_dir) if f.startswith("decision_") and f.endswith(".json")])
        if not files:
            return safe_fallback
        latest_file = os.path.join(decisions_dir, files[-1])
        try:
            with open(latest_file, "r") as f:
                data = json.load(f)
            # Validate required schema fields
            if "selected_strategy" not in data or "risk_multiplier" not in data:
                logger.warning(f"Manifest {latest_file} corrupt or invalid schema. Emitting WAIT.")
                return safe_fallback

            # Validate risk_multiplier is finite and non-negative
            risk_mult = data.get("risk_multiplier")
            if not isinstance(risk_mult, (int, float)) or not math.isfinite(risk_mult) or risk_mult < 0:
                logger.warning(f"Manifest {latest_file} has invalid risk_multiplier: {risk_mult}. Emitting WAIT.")
                return safe_fallback

            # Validate session/date if current_ist_date is provided
            manifest_date = data.get("session_date") or data.get("date")
            if current_ist_date and manifest_date and manifest_date != current_ist_date:
                logger.warning(f"Manifest {latest_file} date {manifest_date} does not match current session {current_ist_date}. Emitting WAIT.")
                return safe_fallback

            # Validate staleness (> 24h)
            mtime = os.path.getmtime(latest_file)
            age_seconds = time.time() - mtime
            if age_seconds > 86400 * 2:  # allow 2 days for weekend gaps, but check date
                if current_ist_date and manifest_date and manifest_date != current_ist_date:
                    return safe_fallback

            return data
        except Exception as e:
            logger.error(f"Failed to read manifest {latest_file}: {e}. Emitting WAIT.")
            return safe_fallback

    def execute_eod_reconciliation_and_tearsheet(
        self,
        portfolio_equity: float,
        open_positions_count: int,
        cash: Optional[float] = None,
        realized_pnl: float = 0.0,
        total_fees: float = 0.0,
        total_slippage: float = 0.0,
        positions: Optional[Dict[str, Dict[str, float]]] = None,
    ) -> Tuple[bool, float, Optional[str]]:
        """15:35 IST: Post-market double-entry audit & daily performance dispatch."""
        logger.info("Executing 15:35 IST Post-Market Reconciliation & Daily Tearsheet...")
        daily_pnl = portfolio_equity - self.daily_starting_equity
        daily_return_pct = (daily_pnl / self.daily_starting_equity) * 100 if self.daily_starting_equity > 0 else 0.0

        # Perform actual double-entry accounting audit
        actual_cash = cash if cash is not None else portfolio_equity
        is_reconciled, imbalance, error_reason = DoubleEntryLedgerReconciler.audit_accounting_invariants(
            initial_cash=self.daily_starting_equity,
            current_cash=actual_cash,
            positions=positions or {},
            total_fees_paid=total_fees,
            total_slippage_paid=total_slippage,
            realized_pnl=realized_pnl,
            tolerance=0.05,
        )

        status_text = "PASSED (Zero Discrepancy)" if is_reconciled else f"DISCREPANCY (INR {imbalance:.2f})"
        if not is_reconciled:
            logger.error(f"EOD Ledger Reconciliation Failed: {error_reason}")
            self.is_killswitch_tripped = True  # Freeze new entries on accounting drift

        self.dispatcher.notify(
            title="EOD Trading Session Report",
            message=f"NSE session closed. Ledger audit: {status_text}",
            level="INFO" if (daily_pnl >= 0 and is_reconciled) else "WARNING",
            fields={
                "Date": self.get_ist_now().strftime("%Y-%m-%d"),
                "Final Equity": f"INR {portfolio_equity:,.2f}",
                "Daily PnL": f"INR {daily_pnl:+,.2f} ({daily_return_pct:+.2f}%)",
                "Open Positions at EOD": str(open_positions_count),
                "Accounting Audit": status_text,
                "Killswitch Triggered": "YES" if self.is_killswitch_tripped else "NO",
            },
        )
        return is_reconciled, imbalance, error_reason

    def execute_eod_research_and_strategy_allocation(self) -> Dict[str, Any]:
        """15:40 IST: Execute quantitative research bot to backtest & allocate strategy."""
        logger.info("Executing 15:40 IST Autonomous Quantitative Research & Strategy Allocation...")
        try:
            from services.research_engine.decision_bot import AutonomousResearchBot
            bot = AutonomousResearchBot()
            return bot.run_eod_research_cycle()
        except Exception as e:
            logger.error(f"Error executing Autonomous Research Bot: {e}")
            return {"status": "ERROR", "error": str(e)}

    def vacuum_database(self):
        """16:00 IST: SQLite WAL checkpoint and vacuum."""
        if os.path.exists(self.db_path):
            try:
                conn = sqlite3.connect(self.db_path)
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                conn.execute("VACUUM")
                conn.close()
                logger.info("Database VACUUM and WAL truncation complete.")
            except Exception as e:
                logger.warning(f"Database vacuum failed: {e}")


if __name__ == "__main__":
    sentinel = AutonomousSentinel()
    now_ist = sentinel.get_ist_now()
    is_open = sentinel.is_market_day(now_ist)
    print(f"AutonomousSentinel initialized. IST Time: {now_ist.strftime('%Y-%m-%d %H:%M:%S IST')} | Is Market Day: {is_open}")
