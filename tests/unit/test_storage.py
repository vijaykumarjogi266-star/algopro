"""Unit tests for Parquet and DuckDB Market Data Storage."""

from datetime import datetime, timedelta, timezone
import pytest
from pathlib import Path
import tempfile

from data.schemas.contracts import Exchange, OHLCVBar, TimeFrame
from services.market_data.storage import ParquetMarketDataStorage


def test_parquet_storage_and_duckdb_point_in_time():
    with tempfile.TemporaryDirectory() as tmp_dir:
        storage = ParquetMarketDataStorage(base_dir=tmp_dir)

        # Generate 10 bars
        now = datetime(2024, 9, 2, 9, 15, tzinfo=timezone.utc)
        bars = []
        for i in range(10):
            bars.append(
                OHLCVBar(
                    symbol="RELIANCE",
                    exchange=Exchange.NSE,
                    timeframe=TimeFrame.M5,
                    market_timestamp=now + timedelta(minutes=5 * i),
                    open=2500.0 + i,
                    high=2505.0 + i,
                    low=2495.0 + i,
                    close=2502.0 + i,
                    volume=1000.0,
                )
            )

        # Save bars to partitioned Parquet
        manifest = storage.save_bars(bars, dataset_version="v1.0.0")
        assert manifest.bar_count == 10
        assert manifest.dataset_version == "v1.0.0"
        assert Path(manifest.storage_path).exists()
        assert len(manifest.sha256_checksum) == 64

        # Read back using Polars
        df = storage.load_bars_as_polars(Exchange.NSE, TimeFrame.M5, "RELIANCE", 2024)
        assert df is not None
        assert df.shape[0] == 10
        assert "close" in df.columns

        # Query point-in-time up to bar index 4 (5 bars total) using DuckDB
        cutoff_ts = now + timedelta(minutes=20)
        pit_df = storage.query_point_in_time_duckdb(
            Exchange.NSE, TimeFrame.M5, "RELIANCE", 2024, as_of_timestamp=cutoff_ts
        )
        # Should return exactly 5 bars (index 0, 1, 2, 3, 4)
        assert pit_df.shape[0] == 5
        # Ensure no future bars leaked
        max_ts_returned = pit_df["market_timestamp"].max()
        assert max_ts_returned <= cutoff_ts.isoformat()
