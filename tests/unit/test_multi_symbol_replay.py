"""Unit tests for Multi-Symbol Historical Replay Synchronization (Stage 6)."""

from datetime import datetime, timezone, timedelta
import pytest

from data.schemas.canonical_market_data import CanonicalMarketDataBar
from services.backtest_engine.replay import (
    HistoricalReplayEngine,
    ReplayConfig,
    ReplayEvent,
    LookAheadBiasError,
)
from services.backtest_engine.portfolio import PortfolioTracker, Position
from services.backtest_engine.contracts import OrderSide


def _make_bar(symbol: str, dt: datetime, price: float) -> CanonicalMarketDataBar:
    return CanonicalMarketDataBar(
        timestamp=dt,
        symbol=symbol,
        exchange="NSE",
        timeframe="5m",
        open=price,
        high=price + 2.0,
        low=price - 2.0,
        close=price + 1.0,
        volume=5000.0,
        trade_count=200,
    )


def test_multi_symbol_chronological_synchronization():
    """Bars across multiple symbols must be synchronized chronologically."""
    t0 = datetime(2025, 2, 3, 9, 15, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=5)
    t2 = t0 + timedelta(minutes=10)

    bars = [
        _make_bar("INFY", t0, 1500.0),
        _make_bar("TCS", t0, 3500.0),
        _make_bar("RELIANCE", t0, 2500.0),
        _make_bar("INFY", t1, 1505.0),
        _make_bar("TCS", t1, 3510.0),
        _make_bar("RELIANCE", t1, 2495.0),
        _make_bar("INFY", t2, 1510.0),
        _make_bar("TCS", t2, 3520.0),
        _make_bar("RELIANCE", t2, 2510.0),
    ]

    engine = HistoricalReplayEngine(
        bars,
        config=ReplayConfig(symbols=["INFY", "TCS", "RELIANCE"]),
    )
    assert engine.total_events == 9

    # Check order of first 3 events: all at t0, symbols sorted alphabetically
    ev1 = engine.step()
    assert ev1.timestamp == t0 and ev1.symbol == "INFY"
    ev2 = engine.step()
    assert ev2.timestamp == t0 and ev2.symbol == "RELIANCE"
    ev3 = engine.step()
    assert ev3.timestamp == t0 and ev3.symbol == "TCS"

    # At t0, TCS history has 1 bar, INFY history has 1 bar, RELIANCE has 1 bar
    assert len(engine.get_history("INFY")) == 1
    assert len(engine.get_history("TCS")) == 1
    assert len(engine.get_history("RELIANCE")) == 1

    # Neither symbol has access to t1 data yet
    with pytest.raises(LookAheadBiasError):
        engine.peek_future(t1)

    # Advance through t1
    engine.step()  # INFY t1
    engine.step()  # RELIANCE t1
    engine.step()  # TCS t1
    assert engine.current_time == t1

    # Now all symbols have 2 bars
    assert len(engine.get_history("INFY")) == 2
    assert len(engine.get_history("TCS")) == 2
    assert len(engine.get_history("RELIANCE")) == 2
    assert engine.get_history("INFY")[-1].close == 1506.0


def test_multi_symbol_portfolio_isolation():
    """Multi-symbol execution must maintain isolated position tracking in PortfolioTracker."""
    tracker = PortfolioTracker(initial_capital=1_000_000.0)

    # Position in INFY
    pos_infy = Position(
        symbol="INFY",
        side=OrderSide.BUY,
        quantity=100,
        entry_price=1500.0,
        current_price=1500.0,
        entry_timestamp=datetime(2025, 2, 3, 9, 15, tzinfo=timezone.utc),
        candidate_id="c_infy_1",
        entry_reason="Breakout",
    )
    tracker.positions["INFY"] = pos_infy
    tracker.cash -= 1500.0 * 100

    # Position in TCS
    pos_tcs = Position(
        symbol="TCS",
        side=OrderSide.BUY,
        quantity=50,
        entry_price=3500.0,
        current_price=3500.0,
        entry_timestamp=datetime(2025, 2, 3, 9, 15, tzinfo=timezone.utc),
        candidate_id="c_tcs_1",
        entry_reason="Mean reversion",
    )
    tracker.positions["TCS"] = pos_tcs
    tracker.cash -= 3500.0 * 50

    assert tracker.cash == 1_000_000.0 - 150000.0 - 175000.0
    assert len(tracker.positions) == 2

    # Update INFY price only
    tracker.positions["INFY"].update_price(1550.0)
    assert tracker.positions["INFY"].unrealized_pnl == (1550.0 - 1500.0) * 100  # +5000
    # TCS unrealized pnl remains zero
    assert tracker.positions["TCS"].unrealized_pnl == 0.0

    # Total equity includes cash + market value of both positions
    expected_equity = tracker.cash + tracker.positions["INFY"].market_value + tracker.positions["TCS"].market_value
    assert tracker.total_equity == pytest.approx(expected_equity)
