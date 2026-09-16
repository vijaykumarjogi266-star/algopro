"""Algo Lab Backtest Persistence & Audit Store.

Adheres to Non-Negotiable Principles:
- Principle 7: Every backtest must be reproducible.
- Principle 8: Every strategy must be versioned.
- Principle 9: Every dataset must be versioned.
- Principle 10: Every experiment must be auditable.
"""

import sqlite3
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from services.backtest_engine.contracts import (
    BacktestResult,
    ReproducibilityRecord,
    BacktestMetrics,
    TradeRecord,
)


class PersistenceError(Exception):
    """Raised on persistence failures."""
    pass


class BacktestRunStore:
    """Thread-safe SQLite store for backtest experiments, metrics, and audit records."""

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        if db_path == ":memory:":
            self._persistent_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._persistent_conn.row_factory = sqlite3.Row
            self._persistent_conn.execute("PRAGMA foreign_keys = ON")
        else:
            self._persistent_conn = None
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if self._persistent_conn is not None:
            return self._persistent_conn
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self):
        conn = self._get_connection()
        with conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("""
            CREATE TABLE IF NOT EXISTS backtest_runs (
                experiment_id TEXT PRIMARY KEY,
                reproducibility_hash TEXT NOT NULL,
                git_commit TEXT NOT NULL,
                dataset_version TEXT NOT NULL,
                strategy_version TEXT NOT NULL,
                universe TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                initial_capital REAL NOT NULL,
                status TEXT NOT NULL,
                metrics_json TEXT,
                reproducibility_json TEXT NOT NULL,
                trades_count INTEGER DEFAULT 0,
                rejected_trades_count INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """)
            conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                FOREIGN KEY (experiment_id) REFERENCES backtest_runs(experiment_id) ON DELETE CASCADE
            )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_exp ON audit_events(experiment_id)")

    def save_run(
        self,
        experiment_id: str,
        reproducibility: ReproducibilityRecord,
        status: str = "PENDING",
        metrics: Optional[BacktestMetrics] = None,
        trades_count: int = 0,
        rejected_trades_count: int = 0,
    ) -> None:
        """Saves or updates a backtest run entity."""
        metrics_json = metrics.model_dump_json() if metrics and hasattr(metrics, "model_dump_json") else (json.dumps(metrics.dict(), default=str) if metrics else None)
        repro_json = reproducibility.model_dump_json() if hasattr(reproducibility, "model_dump_json") else json.dumps(reproducibility.dict(), default=str)

        conn = self._get_connection()
        with conn:
            conn.execute("""
            INSERT OR REPLACE INTO backtest_runs (
                experiment_id, reproducibility_hash, git_commit, dataset_version,
                strategy_version, universe, timeframe, start_date, end_date,
                initial_capital, status, metrics_json, reproducibility_json,
                trades_count, rejected_trades_count, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                experiment_id,
                reproducibility.reproducibility_hash,
                reproducibility.git_commit,
                reproducibility.dataset_version,
                reproducibility.strategy_version,
                json.dumps(reproducibility.universe),
                reproducibility.timeframe,
                reproducibility.start_date.isoformat(),
                reproducibility.end_date.isoformat(),
                reproducibility.initial_capital,
                status,
                metrics_json,
                repro_json,
                trades_count,
                rejected_trades_count,
                datetime.now(timezone.utc).isoformat(),
            ))

    def update_status(
        self,
        experiment_id: str,
        status: str,
        metrics: Optional[BacktestMetrics] = None
    ) -> None:
        """Updates status and final metrics of a backtest run."""
        conn = self._get_connection()
        with conn:
            m_json = metrics.model_dump_json() if metrics and hasattr(metrics, "model_dump_json") else (json.dumps(metrics.dict(), default=str) if metrics else None)
            cur = conn.execute("""
            UPDATE backtest_runs
            SET status = ?, metrics_json = coalesce(?, metrics_json)
            WHERE experiment_id = ?
            """, (status, m_json, experiment_id))
            if cur.rowcount == 0:
                raise PersistenceError(f"Experiment '{experiment_id}' not found")

    def append_audit_event(self, experiment_id: str, event_type: str, payload: Dict[str, Any]) -> None:
        """Records an immutable audit event for an experiment."""
        conn = self._get_connection()
        with conn:
            conn.execute("""
            INSERT INTO audit_events (experiment_id, timestamp, event_type, payload_json)
            VALUES (?, ?, ?, ?)
            """, (
                experiment_id,
                datetime.now(timezone.utc).isoformat(),
                event_type,
                json.dumps(payload, default=str),
            ))

    def get_audit_trail(self, experiment_id: str) -> List[Dict[str, Any]]:
        """Retrieves strictly ordered audit trail for an experiment."""
        conn = self._get_connection()
        cur = conn.execute(
            "SELECT timestamp, event_type, payload_json FROM audit_events WHERE experiment_id = ? ORDER BY id ASC",
            (experiment_id,)
        )
        return [
            {
                "timestamp": r["timestamp"],
                "event_type": r["event_type"],
                "payload": json.loads(r["payload_json"])
            }
            for r in cur.fetchall()
        ]

    def get_run(self, experiment_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves raw run details by experiment ID."""
        conn = self._get_connection()
        cur = conn.execute("SELECT * FROM backtest_runs WHERE experiment_id = ?", (experiment_id,))
        row = cur.fetchone()
        return dict(row) if row else None
