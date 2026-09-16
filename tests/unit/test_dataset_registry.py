"""Unit tests for Dataset Registry & Checksum Validation (Stage 6)."""

from datetime import datetime, timezone, timedelta
import tempfile
import os
import pytest

from data.schemas.canonical_market_data import CanonicalMarketDataBar
from data.schemas.contracts import DataQualityStatus
from services.market_data.registry import (
    DatasetRecord,
    DatasetRegistryStore,
    compute_dataset_checksum,
    DatasetDriftError,
    DatasetIntegrityError,
    DatasetNotFoundError,
)


def _generate_sample_bars(symbol: str = "TCS", count: int = 5):
    bars = []
    base_ts = datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc)
    for i in range(count):
        bar = CanonicalMarketDataBar(
            timestamp=base_ts + timedelta(days=i),
            symbol=symbol,
            exchange="NSE",
            timeframe="1d",
            open=3000.0 + i * 10,
            high=3050.0 + i * 10,
            low=2980.0 + i * 10,
            close=3020.0 + i * 10,
            volume=10000.0 + i * 500,
            trade_count=500 + i * 20,
        )
        bars.append(bar)
    return bars


def test_deterministic_checksum():
    """Identical bars must produce the exact same SHA-256 hash."""
    bars1 = _generate_sample_bars("INFY", 5)
    bars2 = _generate_sample_bars("INFY", 5)
    c1 = compute_dataset_checksum(bars1)
    c2 = compute_dataset_checksum(bars2)
    assert c1 == c2
    assert len(c1) == 64  # SHA-256 length

    # Order of input bars must not alter checksum (since it sorts deterministically)
    c_reversed = compute_dataset_checksum(list(reversed(bars1)))
    assert c1 == c_reversed


def test_dataset_registration_and_retrieval():
    """Test registering and retrieving dataset records from DatasetRegistryStore."""
    store = DatasetRegistryStore(":memory:")
    bars = _generate_sample_bars("RELIANCE", 3)
    checksum = compute_dataset_checksum(bars)

    record = DatasetRecord(
        dataset_id="reliance_daily_v1",
        name="Reliance Daily 2025",
        version="v1.0.0",
        exchange="NSE",
        asset_class="EQUITY",
        timeframe="1d",
        symbols=["RELIANCE"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        bar_count=len(bars),
        sha256_checksum=checksum,
        quality_status=DataQualityStatus.VALID,
        metadata={"vendor": "NSE_HISTORICAL"},
    )

    saved = store.register_dataset(record)
    assert saved.dataset_id == "reliance_daily_v1"

    fetched = store.get_dataset("reliance_daily_v1")
    assert fetched is not None
    assert fetched.name == "Reliance Daily 2025"
    assert fetched.sha256_checksum == checksum
    assert fetched.symbols == ["RELIANCE"]
    assert fetched.bar_count == 3


def test_fail_closed_drift_detection():
    """Any modification in data must trigger fail-closed DatasetDriftError."""
    store = DatasetRegistryStore(":memory:")
    bars = _generate_sample_bars("SBIN", 4)
    checksum = compute_dataset_checksum(bars)

    record = DatasetRecord(
        dataset_id="sbin_daily_v1",
        name="State Bank of India Daily",
        version="v1.0.0",
        exchange="NSE",
        asset_class="EQUITY",
        timeframe="1d",
        symbols=["SBIN"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        bar_count=len(bars),
        sha256_checksum=checksum,
        quality_status=DataQualityStatus.VALID,
    )
    store.register_dataset(record)

    # Valid data passes verification
    assert store.verify_dataset_integrity("sbin_daily_v1", bars) is True

    # Mutated data: alter a single close price
    corrupted_bars = [b.model_copy() for b in bars]
    corrupted_bars[2].close += 0.50

    with pytest.raises(DatasetDriftError) as exc:
        store.verify_dataset_integrity("sbin_daily_v1", corrupted_bars)
    assert "Dataset drift detected" in str(exc.value)

    # Missing bar
    with pytest.raises(DatasetDriftError):
        store.verify_dataset_integrity("sbin_daily_v1", bars[:2])


def test_quarantine_dataset():
    """Quarantined datasets must fail closed upon integrity checks."""
    store = DatasetRegistryStore(":memory:")
    bars = _generate_sample_bars("HDFCBANK", 3)
    checksum = compute_dataset_checksum(bars)

    record = DatasetRecord(
        dataset_id="hdfc_v1",
        name="HDFC Bank Daily",
        version="v1.0.0",
        exchange="NSE",
        asset_class="EQUITY",
        timeframe="1d",
        symbols=["HDFCBANK"],
        start_date=bars[0].timestamp,
        end_date=bars[-1].timestamp,
        bar_count=len(bars),
        sha256_checksum=checksum,
        quality_status=DataQualityStatus.VALID,
    )
    store.register_dataset(record)

    # Quarantine dataset
    quarantined = store.quarantine_dataset("hdfc_v1", "Suspect split discrepancy detected")
    assert quarantined.quality_status == DataQualityStatus.CORRUPTED
    assert quarantined.metadata["quarantine_reason"] == "Suspect split discrepancy detected"

    # Verifying against quarantined dataset must fail closed
    with pytest.raises(DatasetIntegrityError) as exc:
        store.verify_dataset_integrity("hdfc_v1", bars)
    assert "quarantined" in str(exc.value)


def test_dataset_not_found_fail_closed():
    """Unregistered dataset verification must fail closed."""
    store = DatasetRegistryStore(":memory:")
    bars = _generate_sample_bars("INFY", 2)
    with pytest.raises(DatasetNotFoundError):
        store.verify_dataset_integrity("non_existent_dataset", bars)


def test_file_persistence():
    """Ensure DatasetRegistryStore persists across connections with file-based SQLite."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = tf.name

    try:
        store1 = DatasetRegistryStore(db_path)
        bars = _generate_sample_bars("WIPRO", 2)
        record = DatasetRecord(
            dataset_id="wipro_v1",
            name="Wipro",
            version="v1.0.0",
            exchange="NSE",
            asset_class="EQUITY",
            timeframe="1d",
            symbols=["WIPRO"],
            start_date=bars[0].timestamp,
            end_date=bars[-1].timestamp,
            bar_count=len(bars),
            sha256_checksum=compute_dataset_checksum(bars),
            quality_status=DataQualityStatus.VALID,
        )
        store1.register_dataset(record)

        # Open second store pointing to same file
        store2 = DatasetRegistryStore(db_path)
        fetched = store2.get_dataset("wipro_v1")
        assert fetched is not None
        assert fetched.name == "Wipro"
        assert len(store2.list_datasets()) == 1
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)
