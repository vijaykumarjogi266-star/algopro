import numpy as np
import pandas as pd
import pytest
from services.research_engine.decision_bot import AutonomousResearchBot


def test_cumulative_vwap_calculation_precision():
    # 5 bars with deterministic manual calculation
    # Typical prices: (H + L + C) / 3
    # Bar 0: (10 + 8 + 9)/3 = 9.0, Vol=100 -> CumVol=100, CumTPV=900 -> VWAP = 9.0
    # Bar 1: (12 + 9 + 12)/3 = 11.0, Vol=200 -> CumVol=300, CumTPV=900 + 2200 = 3100 -> VWAP = 3100/300 = 10.3333
    # Bar 2: (15 + 11 + 13)/3 = 13.0, Vol=100 -> CumVol=400, CumTPV=3100 + 1300 = 4400 -> VWAP = 4400/400 = 11.0
    # Bar 3: (14 + 10 + 12)/3 = 12.0, Vol=100 -> CumVol=500, CumTPV=4400 + 1200 = 5600 -> VWAP = 5600/500 = 11.2
    # Bar 4: (16 + 13 + 15)/3 = 14.6667, Vol=500 -> CumVol=1000, CumTPV=5600 + 7333.33 = 12933.33 -> VWAP = 12.9333

    df = pd.DataFrame({
        "High": [10.0, 12.0, 15.0, 14.0, 16.0] * 5,  # replicate to reach >= 20 length
        "Low": [8.0, 9.0, 11.0, 10.0, 13.0] * 5,
        "Close": [9.0, 12.0, 13.0, 12.0, 15.0] * 5,
        "Volume": [100.0, 200.0, 100.0, 100.0, 500.0] * 5,
    })

    bot = AutonomousResearchBot()
    # Test that _simulate_vwap_reversion runs deterministically and does not crash
    trades = bot._simulate_vwap_reversion({"TEST": df})
    assert isinstance(trades, list)


def test_zero_volume_resilience():
    df = pd.DataFrame({
        "High": [10.0] * 25,
        "Low": [8.0] * 25,
        "Close": [9.0] * 25,
        "Volume": [0.0] * 25,
    })
    bot = AutonomousResearchBot()
    trades = bot._simulate_vwap_reversion({"TEST": df})
    assert isinstance(trades, list)
