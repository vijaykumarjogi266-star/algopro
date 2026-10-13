"""Algo Lab Quantitative Strategies Package."""

from quant.strategies.base import BaseStrategy, SignalType, StrategyDecision
from quant.strategies.buy_and_hold import BuyAndHold
from quant.strategies.sma_cross import SMACross, SMA_Cross
from quant.strategies.orb import OpeningRangeBreakout
from quant.strategies.vwap_reversion import VWAPReversion

__all__ = [
    "BaseStrategy",
    "SignalType",
    "StrategyDecision",
    "BuyAndHold",
    "SMACross",
    "SMA_Cross",
    "OpeningRangeBreakout",
    "VWAPReversion",
]
