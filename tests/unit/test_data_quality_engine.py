"""Unit tests for the 11-Dimensional Data Quality Engine."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import pytest

from data.schemas.contracts import DataQualityStatus, Exchange, OHLCVBar, TimeFrame
from services.market_data.calendar import IST_TZ
from services.data_quality.engine import (
    DataQualityEngine,
    DataQualityGateException,
)


@pytest.fixture
def base_valid_bar_sequence():
    """Generates a sequence of 5 valid intraday bars on a trading Monday within session hours."""
    # Monday 2024-09-02 starting at 09:15 IST
    start_ist = datetime(2024, 9, 2, 9, 15, tzinfo=IST_TZ)
    bars = []
    current_ts = start_ist
    price = 2500.0

    for i in range(5):
        utc_ts = current_ts.astimezone(timezone.utc)
        bars.append(
            OHLCVBar(
                symbol="RELIANCE",
                exchange=Exchange.NSE,
                timeframe=TimeFrame.M5,
                market_timestamp=utc_ts,
                ingestion_timestamp=utc_ts + timedelta(seconds=1),
                open=price,
                high=price + 5.0,
                low=price - 4.0,
                close=price + 2.0,
                volume=5000.0 + (i * 100),
            )
        )
        current_ts += timedelta(minutes=5)
        price += 2.0

    return bars


def test_valid_dataset_passes_all_checks(base_valid_bar_sequence):
    engine = DataQualityEngine()
    report = engine.validate_dataset(base_valid_bar_sequence, enforce_session_hours=True)

    assert report.has_critical_failures is False
    assert report.overall_status == DataQualityStatus.VALID
    assert report.total_bars == 5
    assert report.valid_bars == 5
    # Should not raise exception
    report.assert_trading_eligibility()


def test_empty_dataset_fails():
    engine = DataQualityEngine()
    report = engine.validate_dataset([])
    assert report.has_critical_failures is True
    assert report.overall_status == DataQualityStatus.INCOMPLETE

    with pytest.raises(DataQualityGateException, match="Principle 3 Violation"):
        report.assert_trading_eligibility()


def test_duplicate_and_out_of_order_detection(base_valid_bar_sequence):
    engine = DataQualityEngine()
    # Introduce duplicate timestamp
    corrupted_bars = list(base_valid_bar_sequence)
    corrupted_bars[2] = corrupted_bars[1]

    report = engine.validate_dataset(corrupted_bars, enforce_session_hours=False)
    assert report.has_critical_failures is True
    assert report.overall_status == DataQualityStatus.REJECTED

    failed_checks = [c.check_name for c in report.check_results if not c.passed]
    assert "duplicate_detection" in failed_checks


def test_session_hours_violation():
    engine = DataQualityEngine()
    # Bar at 08:30 IST (before market hours)
    out_of_hours_ts = datetime(2024, 9, 2, 8, 30, tzinfo=IST_TZ).astimezone(timezone.utc)
    bar = OHLCVBar(
        symbol="TCS",
        exchange=Exchange.NSE,
        timeframe=TimeFrame.M5,
        market_timestamp=out_of_hours_ts,
        open=3500.0,
        high=3510.0,
        low=3490.0,
        close=3505.0,
        volume=1000.0,
    )

    report = engine.validate_dataset([bar], enforce_session_hours=True)
    assert report.has_critical_failures is True
    failed_checks = [c.check_name for c in report.check_results if not c.passed]
    assert "trading_session_validation" in failed_checks


def test_stale_data_streak_warning(base_valid_bar_sequence):
    engine = DataQualityEngine(max_allowed_stale_bars=3)
    # Make all bars flat (O == H == L == C)
    stale_bars = []
    for b in base_valid_bar_sequence:
        b_dict = b.model_dump()
        b_dict["open"] = 2500.0
        b_dict["high"] = 2500.0
        b_dict["low"] = 2500.0
        b_dict["close"] = 2500.0
        stale_bars.append(OHLCVBar(**b_dict))

    report = engine.validate_dataset(stale_bars, enforce_session_hours=False)
    # Stale data is a WARNING, flags status as SUSPECT
    assert report.overall_status == DataQualityStatus.SUSPECT
    failed_checks = [c.check_name for c in report.check_results if not c.passed]
    assert "stale_data_detection" in failed_checks


def test_future_timestamp_detected():
    engine = DataQualityEngine()
    future_ts = datetime.now(timezone.utc) + timedelta(days=2)
    bar = OHLCVBar(
        symbol="INFY",
        exchange=Exchange.NSE,
        timeframe=TimeFrame.M5,
        market_timestamp=future_ts,
        open=1500.0,
        high=1510.0,
        low=1490.0,
        close=1505.0,
        volume=1000.0,
    )

    report = engine.validate_dataset([bar], enforce_session_hours=False)
    assert report.has_critical_failures is True
    failed_checks = [c.check_name for c in report.check_results if not c.passed]
    assert "point_in_time_future_check" in failed_checks
