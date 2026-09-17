"""
Algo Lab — Stage 7 Historical Market Regime Classifier
Deterministically classifies historical data into Bull, Bear, Sideways, High Vol, Low Vol regimes
strictly using historical data up to current bar t without look-ahead bias.
"""

import math
from dataclasses import dataclass
from enum import Enum
from typing import List, Dict, Any, Optional
from services.evaluation_engine.walk_forward import LookAheadBiasError


class MarketRegime(str, Enum):
    BULL = "BULL"
    BEAR = "BEAR"
    SIDEWAYS = "SIDEWAYS"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass
class RegimeSlice:
    regime: MarketRegime
    bar_count: int
    start_index: int
    end_index: int
    is_insufficient_evidence: bool


class HistoricalRegimeClassifier:
    """Classifies historical bars into market regimes deterministically."""

    MIN_OBSERVATION_BARS = 20  # AT-61 guard threshold

    @classmethod
    def classify_slice(
        self,
        close_prices: List[float],
        current_index: Optional[int] = None,
    ) -> MarketRegime:
        """Classifies market regime up to `current_index` without inspecting future bars (AT-60)."""
        if current_index is None:
            current_index = len(close_prices) - 1

        # AT-60: Prevent look-ahead
        if current_index >= len(close_prices):
            raise LookAheadBiasError(
                f"Look-ahead access attempt in regime classifier: requested index {current_index} "
                f"exceeds close price list length {len(close_prices)}."
            )

        slice_data = close_prices[: current_index + 1]

        # AT-61: Low observation regime guard
        if len(slice_data) < self.MIN_OBSERVATION_BARS:
            return MarketRegime.INSUFFICIENT_EVIDENCE

        start_price = slice_data[0]
        end_price = slice_data[-1]

        total_return = (end_price - start_price) / start_price if start_price > 0 else 0.0

        # Calculate returns volatility
        returns = [
            (slice_data[i] - slice_data[i - 1]) / slice_data[i - 1]
            for i in range(1, len(slice_data))
            if slice_data[i - 1] > 0
        ]

        if not returns:
            return MarketRegime.INSUFFICIENT_EVIDENCE

        mean_ret = sum(returns) / len(returns)
        var_ret = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
        std_ret = math.sqrt(var_ret)

        if std_ret > 0.03:  # high volatility threshold (>3% daily stddev)
            return MarketRegime.HIGH_VOLATILITY

        if total_return > 0.05:
            return MarketRegime.BULL
        elif total_return < -0.05:
            return MarketRegime.BEAR
        else:
            return MarketRegime.SIDEWAYS
