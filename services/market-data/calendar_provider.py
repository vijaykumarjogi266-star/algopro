"""Versioned Indian Market Calendar Provider Interface & Implementation.

Provides point-in-time exchange holiday schedules, trading hours, and session
definitions without hardcoded annual obsolescence.
"""

from abc import ABC, abstractmethod
from datetime import date, datetime, time, timezone
from typing import Dict, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo
from pydantic import BaseModel, Field

IST_TZ = ZoneInfo("Asia/Kolkata")

# Standard NSE/BSE Equity Session Times (IST)
SESSION_PRE_OPEN_START = time(9, 0)
SESSION_PRE_OPEN_END = time(9, 8)
SESSION_START_TIME = time(9, 15)
SESSION_END_TIME = time(15, 30)
SESSION_POST_CLOSE_START = time(15, 40)
SESSION_POST_CLOSE_END = time(16, 0)


class HolidayRecord(BaseModel):
    """Immutable exchange holiday record."""
    holiday_date: date
    description: str
    exchange: str = "NSE"
    is_settlement_only: bool = False


class SpecialSessionRecord(BaseModel):
    """Special or muhurat trading session."""
    session_date: date
    start_time: time
    end_time: time
    description: str = "Muhurat / Special Trading Session"


class CalendarMetadata(BaseModel):
    """Metadata describing a versioned exchange calendar dataset."""
    calendar_id: str = "NSE-EQUITY-CALENDAR"
    calendar_version: str = "2024.1.0"
    exchange: str = "NSE"
    timezone: str = "Asia/Kolkata"
    effective_years: List[int] = Field(default_factory=lambda: [2022, 2023, 2024, 2025, 2026, 2027])


class CalendarProvider(ABC):
    """Abstract interface for exchange calendar providers."""

    @abstractmethod
    def get_version(self) -> str:
        """Returns the calendar schema and dataset version."""
        pass

    @abstractmethod
    def is_trading_day(self, dt: datetime | date) -> bool:
        """Returns True if the specified date is an active trading session."""
        pass

    @abstractmethod
    def get_holidays_for_year(self, year: int) -> Set[date]:
        """Returns all official market closed dates for a given year."""
        pass

    @abstractmethod
    def is_regular_trading_session(self, dt: datetime) -> Tuple[bool, str]:
        """Validates if a timestamp falls within regular trading hours (09:15 - 15:30 IST)."""
        pass


class VersionedCalendarProvider(CalendarProvider):
    """Institutional calendar provider with versioned annual schedules."""

    def __init__(
        self,
        metadata: Optional[CalendarMetadata] = None,
        custom_holidays: Optional[Dict[int, Set[date]]] = None,
        special_sessions: Optional[Dict[date, SpecialSessionRecord]] = None,
    ):
        self.metadata = metadata or CalendarMetadata()
        self.special_sessions = special_sessions or {}

        # Default multi-year official NSE equity holidays
        self._schedules: Dict[int, Set[date]] = {
            2023: {
                date(2023, 1, 26), date(2023, 3, 7), date(2023, 3, 30), date(2023, 4, 4),
                date(2023, 4, 7), date(2023, 4, 14), date(2023, 5, 1), date(2023, 6, 29),
                date(2023, 8, 15), date(2023, 9, 19), date(2023, 10, 2), date(2023, 10, 24),
                date(2023, 11, 14), date(2023, 11, 27), date(2023, 12, 25),
            },
            2024: {
                date(2024, 1, 26), date(2024, 3, 8), date(2024, 3, 25), date(2024, 4, 11),
                date(2024, 4, 17), date(2024, 5, 1), date(2024, 5, 20), date(2024, 6, 17),
                date(2024, 7, 17), date(2024, 8, 15), date(2024, 10, 2), date(2024, 11, 1),
                date(2024, 11, 15), date(2024, 12, 25),
            },
            2025: {
                date(2025, 1, 26), date(2025, 2, 26), date(2025, 3, 14), date(2025, 3, 31),
                date(2025, 4, 10), date(2025, 4, 14), date(2025, 4, 18), date(2025, 5, 1),
                date(2025, 8, 15), date(2025, 8, 27), date(2025, 10, 2), date(2025, 10, 21),
                date(2025, 11, 5), date(2025, 12, 25),
            },
            2026: {
                date(2026, 1, 26), date(2026, 3, 17), date(2026, 4, 3), date(2026, 5, 1),
                date(2026, 8, 15), date(2026, 10, 2), date(2026, 11, 8), date(2026, 12, 25),
            },
            2027: {
                date(2027, 1, 26), date(2027, 3, 22), date(2027, 3, 26), date(2027, 5, 1),
                date(2027, 8, 15), date(2027, 10, 2), date(2027, 10, 28), date(2027, 12, 25),
            },
        }

        if custom_holidays:
            for yr, hset in custom_holidays.items():
                self._schedules[yr] = set(hset)

    def get_version(self) -> str:
        return f"{self.metadata.calendar_id}:{self.metadata.calendar_version}"

    def get_holidays_for_year(self, year: int) -> Set[date]:
        return self._schedules.get(year, {
            # Minimum statutory national holidays if year not explicitly registered
            date(year, 1, 26), date(year, 8, 15), date(year, 10, 2), date(year, 12, 25)
        })

    def is_trading_day(self, dt: datetime | date) -> bool:
        d = dt.date() if isinstance(dt, datetime) else dt
        # Weekend check: Saturday (5), Sunday (6)
        if d.weekday() >= 5:
            # Special Muhurat check on weekend
            if d in self.special_sessions:
                return True
            return False

        holidays = self.get_holidays_for_year(d.year)
        if d in holidays:
            return False
        return True

    def to_ist(self, dt: datetime) -> datetime:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(IST_TZ)

    def is_regular_trading_session(self, dt: datetime) -> Tuple[bool, str]:
        ist_dt = self.to_ist(dt)
        calendar_date = ist_dt.date()

        # Check for special / Muhurat session
        if calendar_date in self.special_sessions:
            special = self.special_sessions[calendar_date]
            current_time = ist_dt.time()
            if special.start_time <= current_time <= special.end_time:
                return True, f"Within special session ({special.description})"
            return False, f"Outside special trading hours ({special.start_time}-{special.end_time} IST)"

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
        if not self.is_trading_day(d):
            return None

        if d in self.special_sessions:
            spec = self.special_sessions[d]
            s_ist = datetime.combine(d, spec.start_time, tzinfo=IST_TZ)
            e_ist = datetime.combine(d, spec.end_time, tzinfo=IST_TZ)
            return s_ist.astimezone(timezone.utc), e_ist.astimezone(timezone.utc)

        start_ist = datetime.combine(d, SESSION_START_TIME, tzinfo=IST_TZ)
        end_ist = datetime.combine(d, SESSION_END_TIME, tzinfo=IST_TZ)
        return start_ist.astimezone(timezone.utc), end_ist.astimezone(timezone.utc)
