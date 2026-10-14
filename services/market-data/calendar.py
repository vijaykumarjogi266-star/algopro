"""Indian Financial Market Trading Calendar & Session Manager.

Manages National Stock Exchange (NSE) and Bombay Stock Exchange (BSE)
market hours, trading sessions, weekend exclusions, and holiday validation.
Standard Market Hours (IST = UTC + 5:30):
- Pre-Open: 09:00 to 09:08 IST
- Regular Trading Session: 09:15 to 15:30 IST
- Post-Closing Session: 15:40 to 16:00 IST
"""

from datetime import date, datetime, time, timedelta, timezone
from typing import List, Optional, Set, Tuple
from zoneinfo import ZoneInfo

from services.market_data.calendar_provider import (
    CalendarProvider,
    VersionedCalendarProvider,
    IST_TZ,
    SESSION_PRE_OPEN_START,
    SESSION_PRE_OPEN_END,
    SESSION_START_TIME,
    SESSION_END_TIME,
    SESSION_POST_CLOSE_START,
    SESSION_POST_CLOSE_END,
)

# Export legacy holiday set for backward compatibility
_DEFAULT_PROVIDER = VersionedCalendarProvider()
OFFICIAL_HOLIDAYS_NSE: Set[date] = (
    _DEFAULT_PROVIDER.get_holidays_for_year(2024)
    | _DEFAULT_PROVIDER.get_holidays_for_year(2025)
    | _DEFAULT_PROVIDER.get_holidays_for_year(2026)
)


class IndianMarketCalendar:
    """Provides authoritative validation for Indian market sessions."""

    def __init__(
        self,
        custom_holidays: Optional[Set[date]] = None,
        provider: Optional[CalendarProvider] = None,
    ):
        if provider is not None:
            self._provider = provider
            self.holidays = custom_holidays or OFFICIAL_HOLIDAYS_NSE
        elif custom_holidays is not None:
            self.holidays = custom_holidays
            self._provider = None
        else:
            self._provider = _DEFAULT_PROVIDER
            self.holidays = OFFICIAL_HOLIDAYS_NSE

    def is_trading_day(self, dt: datetime | date) -> bool:
        """Determines if a given calendar day is a scheduled trading day (Monday-Friday, non-holiday)."""
        if self._provider is not None:
            return self._provider.is_trading_day(dt)

        d = dt.date() if isinstance(dt, datetime) else dt
        # Weekends: Saturday (5), Sunday (6)
        if d.weekday() >= 5:
            return False
        # Official Exchange Holidays
        if d in self.holidays:
            return False
        return True

    def to_ist(self, dt: datetime) -> datetime:
        """Converts any datetime to Indian Standard Time."""
        if dt.tzinfo is None:
            # Assume UTC if naive, per financial standard
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(IST_TZ)

    def is_regular_trading_session(self, dt: datetime) -> Tuple[bool, str]:
        """Validates if a given timestamp falls strictly within the regular trading session (09:15 - 15:30 IST).
        
        Returns:
            Tuple[bool, str]: (is_valid, reason)
        """
        if self._provider is not None:
            return self._provider.is_regular_trading_session(dt)

        ist_dt = self.to_ist(dt)
        calendar_date = ist_dt.date()

        if not self.is_trading_day(calendar_date):
            if calendar_date.weekday() >= 5:
                return False, f"Timestamp falls on a weekend ({calendar_date.strftime('%A')})"
            return False, f"Timestamp falls on an official exchange holiday ({calendar_date})"

        current_time = ist_dt.time()
        if current_time < SESSION_START_TIME:
            return False, f"Timestamp {current_time} is before session open (09:15 IST)"
        if current_time > SESSION_END_TIME:
            return False, f"Timestamp {current_time} is after session close (15:30 IST)"

        return True, "Within regular NSE/BSE trading hours"

    def get_session_boundaries(self, d: date) -> Optional[Tuple[datetime, datetime]]:
        """Returns UTC session start and end datetimes for a given trading date."""
        if self._provider is not None and hasattr(self._provider, "get_session_boundaries"):
            return self._provider.get_session_boundaries(d)

        if not self.is_trading_day(d):
            return None

        start_ist = datetime.combine(d, SESSION_START_TIME, tzinfo=IST_TZ)
        end_ist = datetime.combine(d, SESSION_END_TIME, tzinfo=IST_TZ)

        return start_ist.astimezone(timezone.utc), end_ist.astimezone(timezone.utc)

    def get_expected_bar_count(self, timeframe_minutes: int) -> int:
        """Returns the expected number of bars in a complete 09:15 - 15:30 IST session (375 minutes)."""
        total_session_minutes = 375  # 6 hours 15 minutes = 375 minutes
        return total_session_minutes // timeframe_minutes
