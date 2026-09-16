"""Unit tests for Canonical Market Data Contracts (Stage 6)."""

from datetime import datetime, timezone, timedelta
import pytest
from pydantic import ValidationError

from data.schemas.canonical_market_data import (
    CanonicalMarketDataBar,
    CanonicalMarketDataValidator,
    MarketDataBatchValidationResult,
)
from data.schemas.contracts import OHLCVBar, Exchange, TimeFrame, DataQualityStatus


def test_canonical_bar_creation_and_utc_normalization():
    """Test standard valid bar creation and UTC normalization."""
    now_utc = datetime.now(timezone.utc)
    bar = CanonicalMarketDataBar(
        timestamp=now_utc,
        symbol="infy",
        exchange="NSE",
        timeframe="1d",
        open=1500.0,
        high=1520.0,
        low=1490.0,
        close=1510.0,
        volume=100000.0,
        open_interest=5000.0,
        trade_count=1200,
        turnover=151000000.0,
        vwap=1505.0,
    )
    assert bar.symbol == "INFY"
    assert bar.timestamp.tzinfo == timezone.utc
    assert bar.trade_count == 1200
    assert bar.volume == 100000.0


def test_canonical_bar_naive_datetime_rejection():
    """Naive datetime must be rejected (Principle 13: fail closed)."""
    naive_dt = datetime(2025, 1, 1, 9, 15, 0)
    with pytest.raises(ValidationError) as exc_info:
        CanonicalMarketDataBar(
            timestamp=naive_dt,
            symbol="RELIANCE",
            exchange="NSE",
            open=2500.0,
            high=2550.0,
            low=2480.0,
            close=2520.0,
            volume=50000.0,
        )
    assert "Timestamp must be timezone-aware" in str(exc_info.value)


def test_canonical_bar_ohlc_consistency():
    """OHLC consistency: high >= max(open, close), low <= min(open, close)."""
    ts = datetime(2025, 1, 1, 9, 15, 0, tzinfo=timezone.utc)

    # High lower than open
    with pytest.raises(ValidationError) as exc:
        CanonicalMarketDataBar(
            timestamp=ts,
            symbol="TCS",
            open=3500.0,
            high=3400.0,  # Invalid: high < open
            low=3300.0,
            close=3350.0,
            volume=100.0,
        )
    assert "Bar high" in str(exc.value)

    # Low higher than close
    with pytest.raises(ValidationError) as exc:
        CanonicalMarketDataBar(
            timestamp=ts,
            symbol="TCS",
            open=3500.0,
            high=3600.0,
            low=3450.0,  # Invalid: low > close
            close=3400.0,
            volume=100.0,
        )
    assert "Bar low" in str(exc.value)


def test_canonical_bar_nan_inf_rejection():
    """NaN and Inf values must be rejected fail-closed."""
    ts = datetime(2025, 1, 1, 9, 15, 0, tzinfo=timezone.utc)

    with pytest.raises(ValidationError) as exc:
        CanonicalMarketDataBar(
            timestamp=ts,
            symbol="HDFCBANK",
            open=float("nan"),
            high=1600.0,
            low=1500.0,
            close=1550.0,
            volume=1000.0,
        )
    assert "NaN or Infinite values are strictly prohibited" in str(exc.value)

    with pytest.raises(ValidationError) as exc:
        CanonicalMarketDataBar(
            timestamp=ts,
            symbol="HDFCBANK",
            open=1550.0,
            high=float("inf"),
            low=1500.0,
            close=1550.0,
            volume=1000.0,
        )
    assert "NaN or Infinite values are strictly prohibited" in str(exc.value)


def test_batch_validator_chronological_order_and_duplicates():
    """Batch validator must catch out-of-order timestamps and duplicates."""
    base_ts = datetime(2025, 1, 1, 9, 15, 0, tzinfo=timezone.utc)
    b1 = CanonicalMarketDataBar(
        timestamp=base_ts,
        symbol="SBIN",
        open=750.0, high=760.0, low=745.0, close=755.0, volume=1000.0
    )
    b2 = CanonicalMarketDataBar(
        timestamp=base_ts + timedelta(minutes=5),
        symbol="SBIN",
        open=755.0, high=765.0, low=750.0, close=760.0, volume=1500.0
    )
    # Valid batch
    res = CanonicalMarketDataValidator.validate_series([b1, b2])
    assert res.is_valid is True
    assert res.duplicate_count == 0
    assert res.out_of_order_count == 0

    # Duplicate
    res_dup = CanonicalMarketDataValidator.validate_series([b1, b1])
    assert res_dup.is_valid is False
    assert res_dup.duplicate_count == 1
    assert len(res_dup.quarantined_bars) == 1

    # Out of order
    res_ooo = CanonicalMarketDataValidator.validate_series([b2, b1])
    assert res_ooo.is_valid is False
    assert res_ooo.out_of_order_count == 1
    assert len(res_ooo.quarantined_bars) == 1


def test_batch_validator_empty_series():
    """Empty series must be flagged invalid."""
    res = CanonicalMarketDataValidator.validate_series([])
    assert res.is_valid is False
    assert "Market data series is empty" in res.errors[0]


def test_backward_compatibility_ohlcv_bar():
    """Verify OHLCVBar supports trade_count field without breaking existing usage."""
    ts = datetime(2025, 1, 1, 9, 15, 0, tzinfo=timezone.utc)
    bar = OHLCVBar(
        symbol="NIFTY",
        exchange=Exchange.NSE,
        timeframe=TimeFrame.D1,
        market_timestamp=ts,
        open=24000.0,
        high=24200.0,
        low=23900.0,
        close=24150.0,
        volume=500000.0,
        trade_count=45000,
    )
    assert bar.trade_count == 45000
    assert bar.is_usable_for_trading() is True
