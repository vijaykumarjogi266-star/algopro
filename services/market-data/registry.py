"""Algo Lab Dataset Registry & Checksum Validation (Stage 6).

Adheres to Non-Negotiable Principles:
- Principle 3: Bad or uncertain data must not produce a trading decision.
- Principle 7: Every backtest must be reproducible.
- Principle 9: Every dataset must be versioned.
- Principle 10: Every experiment must be auditable.
- Principle 13: Data validation must fail closed.
"""

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from data.schemas.contracts import (
    AssetClass,
    DataQualityStatus,
    Exchange,
    TimeFrame,
)
from data.schemas.canonical_market_data import (
    CanonicalMarketDataBar,
    CanonicalMarketDataValidator,
)
from apps.api.core.logging import get_logger

logger = get_logger(__name__)


class DatasetDriftError(Exception):
    """Raised when dataset content drifts from its registered cryptographic checksum."""
    pass


class DatasetIntegrityError(Exception):
    """Raised on dataset validation or consistency failure."""
    pass


class DatasetNotFoundError(Exception):
    """Raised when a dataset cannot be found in the registry."""
    pass


class DatasetRecord(BaseModel):
    """Schema representing an immutable, registered dataset partition or universe."""

    dataset_id: str = Field(description="Unique identifier (slug or UUID)")
    name: str = Field(description="Human-readable name")
    version: str = Field(default="v1.0.0", description="Dataset semantic version")
    exchange: str = Field(default="NSE", description="Exchange identifier")
    asset_class: str = Field(default="EQUITY", description="Asset class")
    timeframe: str = Field(default="1d", description="Timeframe")
    symbols: List[str] = Field(description="List of symbols in dataset universe")
    start_date: datetime = Field(description="Start UTC timestamp")
    end_date: datetime = Field(description="End UTC timestamp")
    bar_count: int = Field(ge=0, description="Total number of bars")
    sha256_checksum: str = Field(description="Deterministic SHA-256 digest of canonical bar series")
    quality_status: DataQualityStatus = Field(default=DataQualityStatus.VALID)
    storage_path: Optional[str] = Field(default=None, description="Physical storage path or URI")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary dataset metadata")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def compute_dataset_checksum(bars: List[CanonicalMarketDataBar]) -> str:
    """Deterministically computes a SHA-256 cryptographic digest of canonical bars.
    
    Bars are sorted by (symbol, timestamp) to ensure invariant hashing regardless
    of initial retrieval or ingestion ordering.
    """
    if not bars:
        return hashlib.sha256(b"").hexdigest()

    sorted_bars = sorted(bars, key=lambda b: (b.symbol, b.timestamp))
    hasher = hashlib.sha256()

    for b in sorted_bars:
        # Construct deterministic binary representation of each canonical bar
        bar_line = (
            f"{b.symbol}|{b.exchange}|{b.timeframe}|"
            f"{b.timestamp.astimezone(timezone.utc).isoformat()}|"
            f"{b.open:.6f}|{b.high:.6f}|{b.low:.6f}|{b.close:.6f}|{b.volume:.6f}|"
            f"{b.open_interest if b.open_interest is not None else -1:.6f}|"
            f"{b.trade_count if b.trade_count is not None else -1}|"
            f"{b.turnover if b.turnover is not None else -1:.6f}|"
            f"{b.vwap if b.vwap is not None else -1:.6f}\n"
        )
        hasher.update(bar_line.encode("utf-8"))

    return hasher.hexdigest()


class DatasetRegistryStore:
    """Thread-safe SQLite store for dataset registry, versioning, and drift detection."""

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self._lock = threading.RLock()
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
        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.execute("""
                CREATE TABLE IF NOT EXISTS datasets (
                    dataset_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    version TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    asset_class TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    symbols TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    bar_count INTEGER NOT NULL,
                    sha256_checksum TEXT NOT NULL,
                    quality_status TEXT NOT NULL,
                    storage_path TEXT,
                    metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_datasets_version ON datasets(name, version)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_datasets_checksum ON datasets(sha256_checksum)")

    def register_dataset(self, record: DatasetRecord) -> DatasetRecord:
        """Registers a new dataset record or updates metadata if not drifted."""
        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.execute("""
                INSERT INTO datasets (
                    dataset_id, name, version, exchange, asset_class, timeframe,
                    symbols, start_date, end_date, bar_count, sha256_checksum,
                    quality_status, storage_path, metadata, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dataset_id) DO UPDATE SET
                    name = excluded.name,
                    version = excluded.version,
                    exchange = excluded.exchange,
                    asset_class = excluded.asset_class,
                    timeframe = excluded.timeframe,
                    symbols = excluded.symbols,
                    start_date = excluded.start_date,
                    end_date = excluded.end_date,
                    bar_count = excluded.bar_count,
                    sha256_checksum = excluded.sha256_checksum,
                    quality_status = excluded.quality_status,
                    storage_path = excluded.storage_path,
                    metadata = excluded.metadata,
                    updated_at = excluded.updated_at
                """, (
                    record.dataset_id,
                    record.name,
                    record.version,
                    record.exchange,
                    record.asset_class,
                    record.timeframe,
                    json.dumps(record.symbols),
                    record.start_date.isoformat(),
                    record.end_date.isoformat(),
                    record.bar_count,
                    record.sha256_checksum,
                    record.quality_status.value if hasattr(record.quality_status, "value") else str(record.quality_status),
                    record.storage_path,
                    json.dumps(record.metadata),
                    record.created_at.isoformat(),
                    record.updated_at.isoformat(),
                ))
            return record

    def get_dataset(self, dataset_id: str) -> Optional[DatasetRecord]:
        """Retrieves a dataset record by ID."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute("SELECT * FROM datasets WHERE dataset_id = ?", (dataset_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_record(row)

    def list_datasets(self) -> List[DatasetRecord]:
        """Lists all registered datasets."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute("SELECT * FROM datasets ORDER BY created_at DESC")
            return [self._row_to_record(row) for row in cursor.fetchall()]

    def verify_dataset_integrity(
        self,
        dataset_id: str,
        bars: List[CanonicalMarketDataBar],
        fail_closed: bool = True,
    ) -> bool:
        """Verifies market data bars against registered cryptographic checksum.
        
        If fail_closed is True, raises DatasetDriftError or DatasetIntegrityError on mismatch.
        """
        record = self.get_dataset(dataset_id)
        if not record:
            if fail_closed:
                raise DatasetNotFoundError(f"Dataset '{dataset_id}' not found in registry")
            return False

        if record.quality_status in (DataQualityStatus.CORRUPTED, DataQualityStatus.REJECTED):
            if fail_closed:
                raise DatasetIntegrityError(
                    f"Dataset '{dataset_id}' is quarantined with status {record.quality_status}"
                )
            return False

        current_checksum = compute_dataset_checksum(bars)
        if current_checksum != record.sha256_checksum:
            if fail_closed:
                raise DatasetDriftError(
                    f"Dataset drift detected for '{dataset_id}'! Registered: {record.sha256_checksum}, "
                    f"Calculated: {current_checksum}. Bar count: {len(bars)} vs registered {record.bar_count}."
                )
            return False

        return True

    def quarantine_dataset(self, dataset_id: str, reason: str) -> DatasetRecord:
        """Marks a dataset as CORRUPTED/REJECTED, preventing any future trading decision."""
        with self._lock:
            record = self.get_dataset(dataset_id)
            if not record:
                raise DatasetNotFoundError(f"Dataset '{dataset_id}' not found in registry")

            record.quality_status = DataQualityStatus.CORRUPTED
            record.metadata["quarantine_reason"] = reason
            record.metadata["quarantined_at"] = datetime.now(timezone.utc).isoformat()
            record.updated_at = datetime.now(timezone.utc)
            self.register_dataset(record)
            logger.warning(f"Quarantined dataset {dataset_id}: {reason}")
            return record

    def _row_to_record(self, row: sqlite3.Row) -> DatasetRecord:
        raw_status = row["quality_status"]
        status = DataQualityStatus(raw_status) if raw_status in DataQualityStatus._value2member_map_ else DataQualityStatus.VALID
        return DatasetRecord(
            dataset_id=row["dataset_id"],
            name=row["name"],
            version=row["version"],
            exchange=row["exchange"],
            asset_class=row["asset_class"],
            timeframe=row["timeframe"],
            symbols=json.loads(row["symbols"]),
            start_date=datetime.fromisoformat(row["start_date"]),
            end_date=datetime.fromisoformat(row["end_date"]),
            bar_count=row["bar_count"],
            sha256_checksum=row["sha256_checksum"],
            quality_status=status,
            storage_path=row["storage_path"],
            metadata=json.loads(row["metadata"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
