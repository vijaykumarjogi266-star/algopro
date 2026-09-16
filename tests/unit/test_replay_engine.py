"""Unit tests for Historical Market Replay Engine & Look-Ahead Guard (Stage 6)."""

from datetime import datetime, timezone, timedelta
import pytest

from data.schemas.canonical_market_data import CanonicalMarketDataBar
from services.backtest_engine.replay import (
    HistoricalReplayEngine,
    ReplayConfig,
    ReplayEvent,
    LookAheadBiasError,
)
from services.market_data.calendar import IndianMarketCalendar


def _make_bar(symbol: str, dt: datetime, price: float = 100.0) -> CanonicalMarketDataBar:
    return CanonicalMarketDataBar(
        timestamp=dt,
        symbol=symbol,
        exchange="NSE",
        timeframe="1d",
        open=price,
        high=price + 5.0,
        low=price - 5.0,
        close=price + 2.0,
        volume=1000.0,
        trade_count=100,
    )


def test_replay_chronological_ordering():
    """Events must be delivered strictly in chronological order."""
    base = datetime(2025, 2, 3, 9, 15, tzinfo=timezone.utc)  # Monday
    b1 = _make_bar("INFY", base)
    b2 = _make_bar("INFY", base + timedelta(days=1))
    b3 = _make_bar("INFY", base + timedelta(days=2))

    # Pass in scrambled order
    engine = HistoricalReplayEngine([b3, b1, b2])
    assert engine.total_events == 3
    assert engine.current_time is None

    ev1 = engine.step()
    assert ev1.timestamp == base
    assert engine.current_time == base

    ev2 = engine.step()
    assert ev2.timestamp == base + timedelta(days=1)

    ev3 = engine.step()
    assert ev3.timestamp == base + timedelta(days=2)
    assert engine.is_finished is True


def test_strict_look_ahead_guard():
    """Engine must strictly prohibit peeking or querying future bars."""
    base = datetime(2025, 2, 3, 9, 15, tzinfo=timezone.utc)
    b1 = _make_bar("TCS", base)
    b2 = _make_bar("TCS", base + timedelta(days=1))
    b3 = _make_bar("TCS", base + timedelta(days=2))

    engine = HistoricalReplayEngine([b1, b2, b3])

    # Before start: history is empty
    assert engine.get_history("TCS") == []
    with pytest.raises(LookAheadBiasError):
        engine.peek_future(base)

    # Step 1: Only bar 1 is accessible
    engine.step()
    history = engine.get_history("TCS")
    assert len(history) == 1
    assert history[0].timestamp == base

    # Peeking into tomorrow must raise LookAheadBiasError
    with pytest.raises(LookAheadBiasError) as exc:
        engine.peek_future(base + timedelta(days=1))
    assert "Look-Ahead Bias Violation" in str(exc.value)

    # Step 2: Now bar 1 and 2 are accessible
    engine.step()
    history = engine.get_history("TCS")
    assert len(history) == 2
    assert history[-1].timestamp == base + timedelta(days=1)

    # Still cannot peek into day 3
    with pytest.raises(LookAheadBiasError):
        engine.peek_future(base + timedelta(days=2))


def test_replay_calendar_filtering():
    """Holidays and weekends must be filtered out if calendar filtering is enabled."""
    # 2025-08-15 is Independence Day (Friday holiday)
    holiday_dt = datetime(2025, 8, 15, 9, 15, tzinfo=timezone.utc)
    trading_dt = datetime(2025, 8, 18, 9, 15, tzinfo=timezone.utc)  # Monday

    b_holiday = _make_bar("RELIANCE", holiday_dt)
    b_trading = _make_bar("RELIANCE", trading_dt)

    engine = HistoricalReplayEngine(
        [b_holiday, b_trading],
        config=ReplayConfig(symbols=["RELIANCE"], filter_holidays=True),
    )
    assert engine.total_events == 1
    ev = engine.step()
    assert ev.timestamp == trading_dt


def test_replay_reset_and_callback():
    """Test full replay run with callback and reset functionality."""
    base = datetime(2025, 2, 3, 9, 15, tzinfo=timezone.utc)
    bars = [_make_bar("SBIN", base + timedelta(days=i)) for i in range(5)]

    engine = HistoricalReplayEngine(bars)
    visited_events = []

    def callback(event: ReplayEvent, eng: HistoricalReplayEngine):
        visited_events.append(event.timestamp)
        # Verify that at each callback, get_history only has bars <= current event
        h = eng.get_history("SBIN")
        assert h[-1].timestamp == event.timestamp

    count = engine.run(on_event=callback)
    assert count == 5
    assert len(visited_events) == 5
    assert engine.is_finished is True

    # Reset
    engine.reset()
    assert engine.events_processed == 0
    assert engine.current_time is None
    assert engine.is_finished is False
