"""Indian Market Corporate Actions & Point-in-Time Price Adjuster.

Manages Stock Splits, Bonus Issues, Cash Dividends, and Rights Issues.
Strictly adheres to:
- Principle 4: No look-ahead bias (adjustment factors are applied point-in-time).
- Principle 5: No data leakage.
"""

from datetime import date, datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from data.schemas.contracts import OHLCVBar


class CorporateActionType(str, Enum):
    SPLIT = "SPLIT"
    BONUS = "BONUS"
    DIVIDEND = "DIVIDEND"
    RIGHTS = "RIGHTS"


class CorporateAction(BaseModel):
    """Encapsulates a corporate action event."""

    symbol: str
    action_type: CorporateActionType
    ex_date: date
    record_date: date
    ratio_old: float = 1.0  # e.g., for 1:2 bonus, ratio_old=1, ratio_new=2
    ratio_new: float = 1.0
    dividend_amount: Optional[float] = None
    rights_issue_price: Optional[float] = None
    announcement_date: Optional[date] = None

    @property
    def split_multiplier(self) -> float:
        """Multiplier for past price adjustment: old_price = current_price / multiplier."""
        if self.action_type in (CorporateActionType.SPLIT, CorporateActionType.BONUS):
            if self.ratio_old > 0:
                return self.ratio_new / self.ratio_old
        return 1.0


class CorporateActionRegistry:
    """Registry of verified corporate actions with point-in-time retrieval."""

    def __init__(self):
        self._actions: List[CorporateAction] = []
        self._load_sample_actions()

    def _load_sample_actions(self):
        # Sample historical actions for testing
        self._actions = [
            CorporateAction(
                symbol="RELIANCE",
                action_type=CorporateActionType.BONUS,
                ex_date=date(2017, 9, 7),
                record_date=date(2017, 9, 9),
                ratio_old=1.0,
                ratio_new=2.0,  # 1:1 Bonus
            ),
            CorporateAction(
                symbol="TCS",
                action_type=CorporateActionType.BONUS,
                ex_date=date(2018, 6, 1),
                record_date=date(2018, 6, 2),
                ratio_old=1.0,
                ratio_new=2.0,  # 1:1 Bonus
            ),
            CorporateAction(
                symbol="INFY",
                action_type=CorporateActionType.BONUS,
                ex_date=date(2018, 9, 4),
                record_date=date(2018, 9, 5),
                ratio_old=1.0,
                ratio_new=2.0,  # 1:1 Bonus
            ),
        ]

    def add_action(self, action: CorporateAction):
        self._actions.append(action)

    def get_actions_for_symbol(
        self, symbol: str, as_of_date: Optional[date] = None
    ) -> List[CorporateAction]:
        """Point-in-time action retrieval: Only actions known and effective as of as_of_date."""
        symbol_upper = symbol.upper()
        actions = [a for a in self._actions if a.symbol.upper() == symbol_upper]
        if as_of_date:
            actions = [a for a in actions if a.ex_date <= as_of_date]
        return sorted(actions, key=lambda a: a.ex_date)

    def calculate_adjustment_factor(self, symbol: str, bar_date: date, as_of_date: date) -> float:
        """Calculates cumulative adjustment factor for a historical bar without look-ahead bias.
        
        Args:
            symbol: Target ticker.
            bar_date: Date of the historical bar.
            as_of_date: Evaluation timestamp (decision point). No actions after as_of_date are considered!
        """
        if bar_date >= as_of_date:
            return 1.0

        actions = self.get_actions_for_symbol(symbol, as_of_date=as_of_date)
        factor = 1.0

        for action in actions:
            # If the bar date is before the ex-date, the historical price must be adjusted by split multiplier
            if bar_date < action.ex_date <= as_of_date:
                factor *= (1.0 / action.split_multiplier)

        return factor

    def adjust_bar_point_in_time(
        self, bar: OHLCVBar, as_of_date: date
    ) -> OHLCVBar:
        """Produces a point-in-time adjusted bar without mutating original bar."""
        bar_d = bar.market_timestamp.date()
        factor = self.calculate_adjustment_factor(bar.symbol, bar_d, as_of_date)

        if factor == 1.0:
            return bar

        adjusted_data = bar.model_dump()
        adjusted_data["open"] = round(bar.open * factor, 4)
        adjusted_data["high"] = round(bar.high * factor, 4)
        adjusted_data["low"] = round(bar.low * factor, 4)
        adjusted_data["close"] = round(bar.close * factor, 4)
        adjusted_data["volume"] = round(bar.volume / factor, 4)
        if bar.vwap:
            adjusted_data["vwap"] = round(bar.vwap * factor, 4)

        return OHLCVBar(**adjusted_data)
