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

# Indian Standard Time (IST)
IST_TZ = ZoneInfo("Asia/Kolkata")

# Standard NSE/BSE Equity Session Times (IST)
SESSION_PRE_OPEN_START = time(9, 0)
SESSION_PRE_OPEN_END = time(9, 8)
SESSION_START_TIME = time(9, 15)
SESSION_END_TIME = time(15, 30)
SESSION_POST_CLOSE_START = time(15, 40)
SESSION_POST_CLOSE_END = time(16, 0)

# Sample Official NSE Holidays for 2024-2026 (Republic Day, Holi, Independence Day, Diwali, etc.)
OFFICIAL_HOLIDAYS_NSE: Set[date] = {
    date(2024, 1, 26),  # Republic Day
    date(2024, 3, 8),   # Mahashivratri
    date(2024, 3, 25),  # Holi
    date(2024, 4, 11),  # Id-Ul-Fitr
    date(2024, 4, 17),  # Shri Ram Navami
    date(2024, 5, 1),   # Maharashtra Day
    date(2024, 6, 17),  # Bakri Id
    date(2024, 7, 17),  # Muharram
    date(2024, 8, 15),  # Independence Day
    date(2024, 10, 2),  # Mahatma Gandhi Jayanti
    date(2024, 11, 1),  # Diwali Laxmi Pujan
    date(2024, 11, 15), # Gurunanak Jayanti
    date(2024, 12, 25), # Christmas
    # 2025
    date(2025, 1, 26),
    date(2025, 8, 15),
    date(2025, 10, 2),
    date(2025, 12, 25),
    # 2026
    date(2026, 1, 26),
    date(2026, 8, 15),
    date(2026, 10, 2),
    date(2026, 12, 25),
}


class IndianMarketCalendar:
    """Provides authoritative validation for Indian market sessions."""

    def __init__(self, custom_holidays: Optional[Set[date]] = None):
        self.holidays = custom_holidays or OFFICIAL_HOLIDAYS_NSE

    def is_trading_day(self, dt: datetime | date) -> bool:
        """Determines if a given calendar day is a scheduled trading day (Monday-Friday, non-holiday)."""
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
        if not self.is_trading_day(d):
            return None

        start_ist = datetime.combine(d, SESSION_START_TIME, tzinfo=IST_TZ)
        end_ist = datetime.combine(d, SESSION_END_TIME, tzinfo=IST_TZ)

        return start_ist.astimezone(timezone.utc), end_ist.astimezone(timezone.utc)

    def get_expected_bar_count(self, timeframe_minutes: int) -> int:
        """Returns the expected number of bars in a complete 09:15 - 15:30 IST session (375 minutes)."""
        total_session_minutes = 375  # 6 hours 15 minutes = 375 minutes
        return total_session_minutes // timeframe_minutes
