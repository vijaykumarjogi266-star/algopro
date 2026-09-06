"""Algo Lab Quantitative Indicator Library.

Clean, deterministic indicator implementations categorized by quant domain:
- Trend: SMA, EMA, MACD, ADX
- Momentum: RSI, Stochastic, ROC
- Volatility: ATR, BollingerBands, RealizedVolatility
- Volume: VWAP, OBV, RelativeVolume

Adheres to Principles:
- Principle 11: Indicators provide evidence, never automated trading decisions.
- Principle 12: RSI must never independently generate BUY/SELL decisions.
- Principle 4: Strict look-ahead protection (point-in-time calculation).
"""

from quant.indicators.base import IndicatorContract, IndicatorResult
from quant.indicators.sma import SMA
from quant.indicators.ema import EMA
from quant.indicators.macd import MACD
from quant.indicators.adx import ADX
from quant.indicators.rsi import RSI
from quant.indicators.stochastic import Stochastic
from quant.indicators.roc import ROC
from quant.indicators.atr import ATR
from quant.indicators.bollinger import BollingerBands
from quant.indicators.realized_volatility import RealizedVolatility
from quant.indicators.vwap import VWAP
from quant.indicators.obv import OBV
from quant.indicators.relative_volume import RelativeVolume

__all__ = [
    "IndicatorContract",
    "IndicatorResult",
    # Trend
    "SMA",
    "EMA",
    "MACD",
    "ADX",
    # Momentum
    "RSI",
    "Stochastic",
    "ROC",
    # Volatility
    "ATR",
    "BollingerBands",
    "RealizedVolatility",
    # Volume
    "VWAP",
    "OBV",
    "RelativeVolume",
]
