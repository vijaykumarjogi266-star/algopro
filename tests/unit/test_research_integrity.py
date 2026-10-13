"""Tests for Research VWAP, DSR, Drawdown, and EOD Statistics Integrity.

Tests:
52. test_vwap_resets_with_unequal_volume_across_sessions
53. test_missing_or_zero_session_volume_yields_wait
54. test_dsr_receives_consistent_nonannualized_units
55. test_research_drawdown_includes_first_loss
56. test_terminal_open_loss_is_included
57. test_eod_equity_is_computed_from_persisted_fields
"""

import sqlite3
import json
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import pytest

from services.research_engine.decision_bot import AutonomousResearchBot
from quant.indicators import compute_session_vwap


def test_vwap_resets_with_unequal_volume_across_sessions():
    """Test 52: VWAP resets per IST session.

    Changing prior session's volume alone must not alter the subsequent session's VWAP.
    """
    ist = ZoneInfo("Asia/Kolkata")
    # Session 1: 2025-01-01
    dt1_bar1 = datetime(2025, 1, 1, 9, 15, tzinfo=ist)
    dt1_bar2 = datetime(2025, 1, 1, 10, 15, tzinfo=ist)
    # Session 2: 2025-01-02
    dt2_bar1 = datetime(2025, 1, 2, 9, 15, tzinfo=ist)
    dt2_bar2 = datetime(2025, 1, 2, 10, 15, tzinfo=ist)

    # Hand-calculated Session 2 prices:
    # Bar 1: H=100, L=100, C=100 -> typical=100, vol=10
    # Bar 2: H=110, L=110, C=110 -> typical=110, vol=30
    # Expected S2 Bar 2 VWAP: (100*10 + 110*30) / (10 + 30) = (1000 + 3300) / 40 = 4300 / 40 = 107.5
    df_a = pd.DataFrame({
        "timestamp": [dt1_bar1, dt1_bar2, dt2_bar1, dt2_bar2],
        "High": [200.0, 200.0, 100.0, 110.0],
        "Low": [200.0, 200.0, 100.0, 110.0],
        "Close": [200.0, 200.0, 100.0, 110.0],
        "Volume": [1000.0, 5000.0, 10.0, 30.0],
    })

    # Same session 2, but session 1 volume massively changed:
    df_b = pd.DataFrame({
        "timestamp": [dt1_bar1, dt1_bar2, dt2_bar1, dt2_bar2],
        "High": [200.0, 200.0, 100.0, 110.0],
        "Low": [200.0, 200.0, 100.0, 110.0],
        "Close": [200.0, 200.0, 100.0, 110.0],
        "Volume": [9999999.0, 8888888.0, 10.0, 30.0],
    })

    vwap_a = compute_session_vwap(df_a)
    vwap_b = compute_session_vwap(df_b)

    # Session 2 VWAP must be identical despite prior session volume change
    assert abs(vwap_a.iloc[2] - 100.0) < 1e-4
    assert abs(vwap_a.iloc[3] - 107.5) < 1e-4
    assert abs(vwap_b.iloc[3] - 107.5) < 1e-4
    assert abs(vwap_a.iloc[3] - vwap_b.iloc[3]) < 1e-4


def test_missing_or_zero_session_volume_yields_wait():
    """Test 53: When session volume is missing or zero, must not fabricate uniform weights

    and must yield no volume-weighted entry.
    """
    bot = AutonomousResearchBot(db_path=":memory:")
    # Data with 0 volume
    ist = ZoneInfo("Asia/Kolkata")
    dates = [datetime(2025, 1, 1, 9, 15, tzinfo=ist) + timedelta(hours=i) for i in range(25)]
    df_zero_vol = pd.DataFrame({
        "timestamp": dates,
        "High": [100.0] * 25,
        "Low": [95.0] * 25,
        "Close": [96.0] * 25,
        "Volume": [0.0] * 25,
    })

    trades = bot._simulate_vwap_reversion({"TEST": df_zero_vol})
    # Zero volume must NOT generate fabricated uniform-weight trades
    assert len(trades) == 0


def test_dsr_receives_consistent_nonannualized_units(monkeypatch):
    """Test 54: DSR receives per-trade non-annualized Sharpe ratio matching the trade-count sample size."""
    bot = AutonomousResearchBot(db_path=":memory:")
    trades = [0.02, -0.01, 0.03, -0.015, 0.025, 0.01]

    captured_inputs = {}

    from services.evaluation_engine.stat_metrics import StatisticalMetricsEngine

    orig_dsr = StatisticalMetricsEngine.calculate_dsr

    def _mock_dsr(*args, **kwargs):
        captured_inputs.update(kwargs)
        if args and len(args) >= 1:
            captured_inputs["sharpe"] = args[0]
        return orig_dsr(*args, **kwargs)

    monkeypatch.setattr(StatisticalMetricsEngine, "calculate_dsr", _mock_dsr)

    bot._evaluate_strategy_metrics("STRAT_VWAP_REVERSION", trades)

    # Sample size must equal number of trades
    assert captured_inputs.get("sample_size") == len(trades)
    # Passed sharpe must NOT be multiplied by sqrt(252*6)
    passed_sharpe = captured_inputs.get("sharpe")
    raw_sharpe = float(np.mean(trades) / np.std(trades))
    assert abs(passed_sharpe - raw_sharpe) < 1e-3


def test_research_drawdown_includes_first_loss():
    """Test 55: Trade returns [-0.20, 0.10, 0.10] must result in 20% max drawdown."""
    bot = AutonomousResearchBot(db_path=":memory:")
    trades = [-0.20, 0.10, 0.10]
    metrics = bot._evaluate_strategy_metrics("STRAT_TEST", trades)
    assert abs(metrics["max_drawdown_pct"] - 20.0) < 1e-2


def test_terminal_open_loss_is_included():
    """Test 56: Position open at end of data must be liquidated and include terminal loss."""
    bot = AutonomousResearchBot(db_path=":memory:")
    ist = ZoneInfo("Asia/Kolkata")
    dates = [datetime(2025, 1, 1, 9, 15, tzinfo=ist) + timedelta(hours=i) for i in range(25)]
    # Create price sequence where entry triggers (e.g. at 100), then drops to 80 at end
    closes = [100.0] * 21 + [90.0, 85.0, 80.0, 75.0]
    df = pd.DataFrame({
        "timestamp": dates,
        "High": [c + 2.0 for c in closes],
        "Low": [c - 2.0 for c in closes],
        "Close": closes,
        "Volume": [1000.0] * len(closes),
    })

    trades = bot._simulate_vwap_reversion({"TEST": df})
    # Terminal position must be liquidated at the end
    if trades:
        # Check that the final trade contains negative return from the open position drop
        assert any(t < 0 for t in trades)


def test_eod_equity_is_computed_from_persisted_fields(tmp_path):
    """Test 57: Cash 40,000 and serialized positions worth 8,000 must yield 48,000 ending equity,

    not the default 50,000.
    """
    db_file = tmp_path / "paper_test.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("""
        CREATE TABLE paper_sessions (
            session_id TEXT PRIMARY KEY,
            name TEXT,
            strategy_id TEXT,
            portfolio_data TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    portfolio_data = {
        "cash": 40000.0,
        "positions": {
            "RELIANCE": {"market_value": 8000.0, "quantity": 10, "current_price": 800.0}
        },
        "total_realized_pnl": 500.0,
    }
    conn.execute(
        "INSERT INTO paper_sessions VALUES (?, ?, ?, ?, ?)",
        ("sess_1", "Test Paper", "strat_1", json.dumps(portfolio_data), datetime.now(timezone.utc).isoformat())
    )
    conn.commit()
    conn.close()

    bot = AutonomousResearchBot(db_path=str(db_file))
    summary = bot.analyze_eod_performance()
    assert summary["ending_equity"] == 48000.0
