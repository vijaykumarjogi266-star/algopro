"""Algo Lab Parquet & DuckDB Market Data Storage Layer.

High-performance columnar storage partitioned by:
data/processed/{exchange}/{timeframe}/{symbol}/{year}.parquet

Uses Polars for fast vector operations and DuckDB for in-memory analytical point-in-time SQL.
Enforces Principle 9: Every dataset must be versioned.
"""

import hashlib
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
import duckdb
import polars as pl
from pydantic import BaseModel, Field

from data.schemas.contracts import (
    AssetClass,
    DataQualityStatus,
    Exchange,
    OHLCVBar,
    TimeFrame,
)
from apps.api.core.logging import get_logger

logger = get_logger(__name__)


class DatasetManifest(BaseModel):
    """Immutable metadata manifest for versioned dataset partitions."""

    manifest_id: str
    dataset_version: str
    symbol: str
    exchange: Exchange
    timeframe: TimeFrame
    start_timestamp: datetime
    end_timestamp: datetime
    bar_count: int
    sha256_checksum: str
    quality_status: DataQualityStatus
    storage_path: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ParquetMarketDataStorage:
    """Manages Parquet storage partitions and DuckDB point-in-time query engine."""

    def __init__(self, base_dir: str = "data/processed"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._duckdb_con = duckdb.connect(database=":memory:")

    def get_partition_path(
        self, exchange: Exchange, timeframe: TimeFrame, symbol: str, year: int
    ) -> Path:
        """Determines the standard partitioned file path."""
        path = (
            self.base_dir
            / exchange.value.upper()
            / timeframe.value.lower()
            / symbol.upper()
            / f"{year}.parquet"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def save_bars(
        self,
        bars: List[OHLCVBar],
        dataset_version: str = "v1.0.0",
    ) -> DatasetManifest:
        """Converts OHLCVBar objects to a Polars DataFrame and persists to versioned Parquet."""
        if not bars:
            raise ValueError("Cannot persist empty bar sequence.")

        first_bar = bars[0]
        symbol = first_bar.symbol.upper()
        exchange = first_bar.exchange
        timeframe = first_bar.timeframe

        # Convert to dictionary representation for Polars
        records = []
        for b in bars:
            records.append({
                "symbol": b.symbol,
                "exchange": b.exchange.value,
                "timeframe": b.timeframe.value,
                "market_timestamp": b.market_timestamp.isoformat(),
                "ingestion_timestamp": b.ingestion_timestamp.isoformat(),
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume,
                "turnover": b.turnover or 0.0,
                "vwap": b.vwap or 0.0,
                "open_interest": b.open_interest or 0.0,
                "quality_status": b.quality_status.value,
            })

        df = pl.DataFrame(records)

        # Sort strictly by timestamp to guarantee ascending order
        df = df.sort("market_timestamp")

        # Partition by year of first bar for now
        year = bars[0].market_timestamp.year
        parquet_path = self.get_partition_path(exchange, timeframe, symbol, year)

        df.write_parquet(parquet_path, compression="zstd")

        # Compute SHA-256 for auditability (Principle 7 & 10)
        with open(parquet_path, "rb") as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()

        start_ts = bars[0].market_timestamp
        end_ts = bars[-1].market_timestamp

        manifest = DatasetManifest(
            manifest_id=f"{symbol}_{timeframe.value}_{year}_{dataset_version}",
            dataset_version=dataset_version,
            symbol=symbol,
            exchange=exchange,
            timeframe=timeframe,
            start_timestamp=start_ts,
            end_timestamp=end_ts,
            bar_count=len(bars),
            sha256_checksum=file_hash,
            quality_status=first_bar.quality_status,
            storage_path=str(parquet_path),
        )

        # Write sidecar JSON manifest
        manifest_path = parquet_path.with_suffix(".manifest.json")
        with open(manifest_path, "w") as f:
            f.write(manifest.model_dump_json(indent=2))

        logger.info(
            "Persisted market data partition",
            extra={
                "symbol": symbol,
                "bars": len(bars),
                "checksum": file_hash[:12],
                "path": str(parquet_path),
            },
        )

        return manifest

    def load_bars_as_polars(
        self, exchange: Exchange, timeframe: TimeFrame, symbol: str, year: int
    ) -> Optional[pl.DataFrame]:
        """Loads a Parquet partition into a Polars DataFrame."""
        path = self.get_partition_path(exchange, timeframe, symbol, year)
        if not path.exists():
            return None
        return pl.read_parquet(path)

    def query_point_in_time_duckdb(
        self,
        exchange: Exchange,
        timeframe: TimeFrame,
        symbol: str,
        year: int,
        as_of_timestamp: datetime,
    ) -> pl.DataFrame:
        """Executes a DuckDB SQL query enforcing strict Point-in-Time access (No look-ahead)."""
        path = self.get_partition_path(exchange, timeframe, symbol, year)
        if not path.exists():
            raise FileNotFoundError(f"Parquet file not found at {path}")

        query = f"""
            SELECT *
            FROM read_parquet('{path}')
            WHERE market_timestamp <= '{as_of_timestamp.isoformat()}'
            ORDER BY market_timestamp ASC
        """
        arrow_table = self._duckdb_con.execute(query).arrow()
        return pl.from_arrow(arrow_table)
