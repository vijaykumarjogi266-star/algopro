"""Algo Lab Quantitative Strategies Package."""

from quant.strategies.base import BaseStrategy, SignalType, StrategyDecision
from quant.strategies.buy_and_hold import BuyAndHold
from quant.strategies.sma_cross import SMACross, SMA_Cross
from quant.strategies.orb import OpeningRangeBreakout
from quant.strategies.vwap_reversion import VWAPReversion
from quant.strategies.donchian_breakout import DonchianBreakout
from quant.strategies.bollinger_reversion import BollingerReversion
from quant.strategies.registry import StrategyRegistry

__all__ = [
    "BaseStrategy",
    "SignalType",
    "StrategyDecision",
    "BuyAndHold",
    "SMACross",
    "SMA_Cross",
    "OpeningRangeBreakout",
    "VWAPReversion",
    "DonchianBreakout",
    "BollingerReversion",
    "StrategyRegistry",
]
