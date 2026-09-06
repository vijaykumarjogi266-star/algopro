"""Unit tests for Corporate Actions & Point-in-Time Adjuster."""

from datetime import date, datetime, timezone
from data.schemas.contracts import Exchange, OHLCVBar, TimeFrame
from services.data_quality.corporate_actions import (
    CorporateAction,
    CorporateActionRegistry,
    CorporateActionType,
)


def test_bonus_adjustment_point_in_time():
    reg = CorporateActionRegistry()
    # Assume a 1:1 bonus on 2024-06-01 (ratio_old=1, ratio_new=2)
    reg.add_action(
        CorporateAction(
            symbol="INFY",
            action_type=CorporateActionType.BONUS,
            ex_date=date(2024, 6, 1),
            record_date=date(2024, 6, 2),
            ratio_old=1.0,
            ratio_new=2.0,
        )
    )

    # Looking at data point-in-time on 2024-05-01 (before the bonus happened)
    # The factor for a bar on 2024-04-01 MUST be 1.0 (no look-ahead to future bonus!)
    factor_before = reg.calculate_adjustment_factor("INFY", date(2024, 4, 1), as_of_date=date(2024, 5, 1))
    assert factor_before == 1.0

    # Looking at data point-in-time on 2024-07-01 (after the bonus happened)
    # The past bar on 2024-04-01 should be adjusted by 0.5
    factor_after = reg.calculate_adjustment_factor("INFY", date(2024, 4, 1), as_of_date=date(2024, 7, 1))
    assert factor_after == 0.5


def test_bar_price_and_volume_adjustment():
    reg = CorporateActionRegistry()
    reg.add_action(
        CorporateAction(
            symbol="RELIANCE",
            action_type=CorporateActionType.SPLIT,
            ex_date=date(2024, 6, 1),
            record_date=date(2024, 6, 2),
            ratio_old=1.0,
            ratio_new=2.0,
        )
    )

    bar = OHLCVBar(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        timeframe=TimeFrame.D1,
        market_timestamp=datetime(2024, 5, 15, 10, 0, tzinfo=timezone.utc),
        open=2000.0,
        high=2100.0,
        low=1950.0,
        close=2050.0,
        volume=10000.0,
    )

    # Adjust as of 2024-07-01 (post-split perspective)
    adjusted_bar = reg.adjust_bar_point_in_time(bar, as_of_date=date(2024, 7, 1))
    assert adjusted_bar.open == 1000.0
    assert adjusted_bar.high == 1050.0
    assert adjusted_bar.low == 975.0
    assert adjusted_bar.close == 1025.0
    # Volume is doubled to maintain equivalent turnover
    assert adjusted_bar.volume == 20000.0
