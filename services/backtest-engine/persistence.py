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
    CostModelConfig,
    SlippageModelConfig,
    ExperimentDefinition,
    ExperimentRun,
    ExperimentStatus,
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
            CREATE TABLE IF NOT EXISTS experiments (
                experiment_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                strategy_id TEXT NOT NULL,
                strategy_version TEXT NOT NULL,
                dataset_id TEXT NOT NULL,
                dataset_version TEXT NOT NULL,
                dataset_checksum TEXT NOT NULL,
                universe TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                parameters TEXT NOT NULL,
                risk_policy_version TEXT NOT NULL,
                cost_model TEXT NOT NULL,
                slippage_model TEXT NOT NULL,
                initial_capital REAL NOT NULL,
                seed INTEGER NOT NULL DEFAULT 42,
                code_revision TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'CREATED',
                created_at TEXT NOT NULL
            )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_exp_fingerprint ON experiments(fingerprint)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_exp_strategy ON experiments(strategy_id)")
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

    def _experiment_from_row(self, row: sqlite3.Row) -> ExperimentDefinition:
        cost_cfg = json.loads(row["cost_model"])
        slip_cfg = json.loads(row["slippage_model"])
        return ExperimentDefinition(
            experiment_id=row["experiment_id"],
            name=row["name"],
            description=row["description"] or "",
            strategy_id=row["strategy_id"],
            strategy_version=row["strategy_version"],
            dataset_id=row["dataset_id"],
            dataset_version=row["dataset_version"],
            dataset_checksum=row["dataset_checksum"],
            universe=json.loads(row["universe"]),
            timeframe=row["timeframe"],
            start_date=datetime.fromisoformat(row["start_date"]),
            end_date=datetime.fromisoformat(row["end_date"]),
            parameters=json.loads(row["parameters"]),
            risk_policy_version=row["risk_policy_version"],
            cost_model=CostModelConfig(**cost_cfg),
            slippage_model=SlippageModelConfig(**slip_cfg),
            initial_capital=float(row["initial_capital"]),
            seed=int(row["seed"]),
            code_revision=row["code_revision"],
            fingerprint=row["fingerprint"],
            status=ExperimentStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def save_experiment(self, exp: ExperimentDefinition) -> None:
        """Saves or updates an experiment definition."""
        conn = self._get_connection()
        cost_json = exp.cost_model.model_dump_json() if hasattr(exp.cost_model, "model_dump_json") else json.dumps(exp.cost_model.dict())
        slip_json = exp.slippage_model.model_dump_json() if hasattr(exp.slippage_model, "model_dump_json") else json.dumps(exp.slippage_model.dict())
        with conn:
            conn.execute("""
            INSERT OR REPLACE INTO experiments (
                experiment_id, name, description, strategy_id, strategy_version,
                dataset_id, dataset_version, dataset_checksum, universe, timeframe,
                start_date, end_date, parameters, risk_policy_version,
                cost_model, slippage_model, initial_capital, seed,
                code_revision, fingerprint, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                exp.experiment_id,
                exp.name,
                exp.description,
                exp.strategy_id,
                exp.strategy_version,
                exp.dataset_id,
                exp.dataset_version,
                exp.dataset_checksum,
                json.dumps(exp.universe),
                exp.timeframe,
                exp.start_date.isoformat(),
                exp.end_date.isoformat(),
                json.dumps(exp.parameters),
                exp.risk_policy_version,
                cost_json,
                slip_json,
                exp.initial_capital,
                exp.seed,
                exp.code_revision,
                exp.fingerprint,
                exp.status.value,
                exp.created_at.isoformat(),
            ))

    def get_experiment(self, experiment_id: str) -> Optional[ExperimentDefinition]:
        """Retrieves experiment definition by experiment_id."""
        conn = self._get_connection()
        cur = conn.execute("SELECT * FROM experiments WHERE experiment_id = ?", (experiment_id,))
        row = cur.fetchone()
        return self._experiment_from_row(row) if row else None

    def get_experiment_by_fingerprint(self, fingerprint: str) -> Optional[ExperimentDefinition]:
        """Retrieves experiment definition by deterministic fingerprint for idempotency."""
        conn = self._get_connection()
        cur = conn.execute("SELECT * FROM experiments WHERE fingerprint = ? ORDER BY created_at DESC LIMIT 1", (fingerprint,))
        row = cur.fetchone()
        return self._experiment_from_row(row) if row else None

    def list_experiments(
        self,
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None,
        strategy_id: Optional[str] = None,
    ) -> List[ExperimentDefinition]:
        """Lists experiments with optional filtering and pagination."""
        conn = self._get_connection()
        query = "SELECT * FROM experiments WHERE 1=1"
        params: List[Any] = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if strategy_id:
            query += " AND strategy_id = ?"
            params.append(strategy_id)
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cur = conn.execute(query, tuple(params))
        return [self._experiment_from_row(r) for r in cur.fetchall()]
