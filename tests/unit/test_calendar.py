"""Unit tests for Indian Market Calendar and Session Management."""

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo
import pytest

from services.market_data.calendar import IST_TZ, IndianMarketCalendar


def test_calendar_weekday_and_weekend():
    cal = IndianMarketCalendar()
    # 2024-09-02 was a Monday (trading day)
    monday = date(2024, 9, 2)
    assert cal.is_trading_day(monday) is True

    # 2024-09-07 was a Saturday (weekend)
    saturday = date(2024, 9, 7)
    assert cal.is_trading_day(saturday) is False

    # 2024-09-08 was a Sunday (weekend)
    sunday = date(2024, 9, 8)
    assert cal.is_trading_day(sunday) is False


def test_calendar_official_holidays():
    cal = IndianMarketCalendar()
    # 2024-01-26 Republic Day (Friday)
    republic_day = date(2024, 1, 26)
    assert cal.is_trading_day(republic_day) is False

    # 2024-08-15 Independence Day (Thursday)
    indep_day = date(2024, 8, 15)
    assert cal.is_trading_day(indep_day) is False


def test_calendar_regular_trading_session_hours():
    cal = IndianMarketCalendar()
    # Monday 2024-09-02 at 10:30 IST (Valid regular trading session)
    dt_valid_ist = datetime(2024, 9, 2, 10, 30, tzinfo=IST_TZ)
    is_valid, reason = cal.is_regular_trading_session(dt_valid_ist)
    assert is_valid is True
    assert "Within regular" in reason

    # Monday 2024-09-02 at 09:05 IST (Pre-open, not regular trading)
    dt_pre_open = datetime(2024, 9, 2, 9, 5, tzinfo=IST_TZ)
    is_valid, reason = cal.is_regular_trading_session(dt_pre_open)
    assert is_valid is False
    assert "before session open" in reason

    # Monday 2024-09-02 at 15:35 IST (Post-close, after 15:30)
    dt_after_close = datetime(2024, 9, 2, 15, 35, tzinfo=IST_TZ)
    is_valid, reason = cal.is_regular_trading_session(dt_after_close)
    assert is_valid is False
    assert "after session close" in reason


def test_calendar_expected_bar_counts():
    cal = IndianMarketCalendar()
    # 375 minutes total in regular session
    assert cal.get_expected_bar_count(timeframe_minutes=1) == 375
    assert cal.get_expected_bar_count(timeframe_minutes=5) == 75
    assert cal.get_expected_bar_count(timeframe_minutes=15) == 25
