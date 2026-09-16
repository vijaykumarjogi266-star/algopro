"""Algo Lab Deterministic Historical Market Replay Engine (Stage 6).

Adheres to Non-Negotiable Principles:
- Principle 3: Bad or uncertain data must not produce a trading decision.
- Principle 4: No look-ahead bias (strict time horizon guard).
- Principle 7: Every backtest must be reproducible.
- Principle 9: Every dataset must be versioned.
- Principle 13: Data validation must fail closed.
"""

from datetime import datetime, timezone
from typing import Callable, Dict, Iterator, List, Optional, Set
import uuid
from pydantic import BaseModel, Field

from data.schemas.canonical_market_data import (
    CanonicalMarketDataBar,
    CanonicalMarketDataValidator,
)
from services.market_data.calendar import IndianMarketCalendar
from apps.api.core.logging import get_logger

logger = get_logger(__name__)


class LookAheadBiasError(RuntimeError):
    """Raised when any component attempts to access future data ahead of the simulated clock."""
    pass


class ReplayEvent(BaseModel):
    """Represents a discrete market data event in the replay timeline."""

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(description="Event UTC timestamp")
    symbol: str = Field(description="Instrument symbol")
    bar: CanonicalMarketDataBar = Field(description="Canonical market data bar")


class ReplayConfig(BaseModel):
    """Configuration for deterministic historical replay."""

    symbols: List[str] = Field(min_length=1, description="List of symbols to simulate")
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    enforce_session_hours: bool = False
    filter_holidays: bool = True


class HistoricalReplayEngine:
    """Deterministic, event-driven historical market replay engine.
    
    Guarantees:
    1. Strictly chronological event delivery ordered by (timestamp, symbol).
    2. Strict fail-closed look-ahead guard: any attempt to access data where
       timestamp > current_simulation_time raises LookAheadBiasError.
    3. Multi-symbol synchronization without forward leakage.
    4. Indian market calendar and trading session enforcement.
    """

    def __init__(
        self,
        bars: List[CanonicalMarketDataBar],
        config: Optional[ReplayConfig] = None,
        calendar: Optional[IndianMarketCalendar] = None,
    ):
        if not bars:
            raise ValueError("Replay dataset cannot be empty.")

        # Sort all bars by (timestamp, symbol)
        sorted_bars = sorted(bars, key=lambda b: (b.timestamp, b.symbol))

        # Batch validation - fail closed
        val_res = CanonicalMarketDataValidator.validate_series(sorted_bars)
        if not val_res.is_valid:
            raise ValueError(f"Invalid market data series for replay: {val_res.errors}")

        self.calendar = calendar or IndianMarketCalendar()
        self.config = config or ReplayConfig(
            symbols=sorted(list({b.symbol for b in sorted_bars}))
        )

        # Filter and prepare events
        self._events: List[ReplayEvent] = []
        for b in sorted_bars:
            # Filter by symbol
            if self.config.symbols and b.symbol not in self.config.symbols:
                continue
            # Filter by date range
            if self.config.start_time and b.timestamp < self.config.start_time:
                continue
            if self.config.end_time and b.timestamp > self.config.end_time:
                continue
            # Filter holidays if enabled
            if self.config.filter_holidays and not self.calendar.is_trading_day(b.timestamp):
                continue
            # Filter session hours if enabled
            if self.config.enforce_session_hours:
                is_reg, _ = self.calendar.is_regular_trading_session(b.timestamp)
                if not is_reg:
                    continue

            self._events.append(
                ReplayEvent(
                    timestamp=b.timestamp,
                    symbol=b.symbol,
                    bar=b,
                )
            )

        # Sort strictly chronologically by (timestamp, symbol)
        self._events.sort(key=lambda ev: (ev.timestamp, ev.symbol))

        if not self._events:
            raise ValueError("No events remaining after filtering according to ReplayConfig.")

        # Simulation clock state
        self._current_index: int = 0
        self._current_time: Optional[datetime] = None
        self._history_by_symbol: Dict[str, List[CanonicalMarketDataBar]] = {
            s: [] for s in self.config.symbols
        }
        self._all_history: List[CanonicalMarketDataBar] = []

    @property
    def total_events(self) -> int:
        return len(self._events)

    @property
    def events_processed(self) -> int:
        return self._current_index

    @property
    def current_time(self) -> Optional[datetime]:
        return self._current_time

    @property
    def is_finished(self) -> bool:
        return self._current_index >= len(self._events)

    def reset(self):
        """Resets the simulation to the beginning."""
        self._current_index = 0
        self._current_time = None
        self._history_by_symbol = {s: [] for s in self.config.symbols}
        self._all_history = []

    def has_next(self) -> bool:
        """Checks if there are more events in the simulation timeline."""
        return self._current_index < len(self._events)

    def step(self) -> Optional[ReplayEvent]:
        """Advances the simulation by one discrete event.
        
        Updates current_time to the event timestamp and makes the bar available
        in historical queries up to current_time.
        """
        if not self.has_next():
            return None

        event = self._events[self._current_index]
        self._current_index += 1
        self._current_time = event.timestamp

        # Add to historical buffer
        self._history_by_symbol.setdefault(event.symbol, []).append(event.bar)
        self._all_history.append(event.bar)

        return event

    def get_history(
        self,
        symbol: str,
        count: Optional[int] = None,
    ) -> List[CanonicalMarketDataBar]:
        """Returns historical bars for a symbol available up to current_time.
        
        Strict Look-Ahead Guard: Never returns any bar beyond current_time.
        """
        if self._current_time is None:
            return []

        sym = symbol.upper()
        bars = self._history_by_symbol.get(sym, [])

        # Strict invariant validation: no bar in returned history can exceed current_time
        for b in bars:
            if b.timestamp > self._current_time:
                raise LookAheadBiasError(
                    f"CRITICAL LOOK-AHEAD DETECTED: Bar {b.timestamp.isoformat()} > "
                    f"Current Replay Time {self._current_time.isoformat()}"
                )

        if count is not None and count > 0:
            return bars[-count:]
        return list(bars)

    def peek_future(self, requested_timestamp: datetime):
        """Guard method that strictly rejects future peeking."""
        if self._current_time is None:
            raise LookAheadBiasError("Cannot access market data before replay has started.")
        if requested_timestamp > self._current_time:
            raise LookAheadBiasError(
                f"Look-Ahead Bias Violation: Requested {requested_timestamp.isoformat()} is "
                f"strictly in the future relative to current replay time {self._current_time.isoformat()}."
            )

    def run(
        self,
        on_event: Optional[Callable[[ReplayEvent, "HistoricalReplayEngine"], None]] = None,
    ) -> int:
        """Executes replay until completion, invoking on_event callback at each step."""
        processed = 0
        while self.has_next():
            ev = self.step()
            if ev is not None:
                processed += 1
                if on_event:
                    on_event(ev, self)
        return processed
