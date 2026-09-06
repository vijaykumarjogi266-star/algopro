"""Algo Lab Indicator Interface & Contract.

Adheres to Non-Negotiable Principles:
- Principle 11: Indicators are evidence, not automatic trading decisions.
- Principle 12: RSI must never independently generate BUY/SELL decisions.
- Principle 13: Multiple correlated indicators must not be treated as independent evidence.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
import numpy as np


class IndicatorContract(ABC):
    """Abstract base class for all deterministic quantitative indicators."""

    def __init__(self, name: str, version: str, params: Optional[Dict[str, Any]] = None):
        self.name = name
        self.version = version
        self.params = params or {}

    @abstractmethod
    def calculate(self, closes: np.ndarray, **kwargs) -> np.ndarray:
        """Deterministic calculation producing an indicator series.
        
        Args:
            closes: Historical series up to decision timestamp (no look-ahead).
        Returns:
            Calculated indicator values aligned with inputs.
        """
        pass

    def get_evidence(self, values: np.ndarray, index: int = -1) -> Dict[str, Any]:
        """Formats the computed indicator into explainable evidence.
        
        Indicators provide evidentiary context (trend, volatility, exhaustion),
        NEVER automatic trade execution commands.
        """
        val = float(values[index]) if len(values) > 0 and not np.isnan(values[index]) else None
        return {
            "indicator": self.name,
            "version": self.version,
            "params": self.params,
            "value": val,
            "is_evidence_only": True,
        }


class SMA(IndicatorContract):
    """Simple Moving Average (SMA)."""

    def __init__(self, period: int = 20):
        super().__init__(name="SMA", version="1.0.0", params={"period": period})
        self.period = period

    def calculate(self, closes: np.ndarray, **kwargs) -> np.ndarray:
        if len(closes) < self.period:
            return np.full_like(closes, np.nan, dtype=float)
        weights = np.repeat(1.0, self.period) / self.period
        sma = np.convolve(closes, weights, "valid")
        prefix = np.full(self.period - 1, np.nan)
        return np.concatenate((prefix, sma))


class EMA(IndicatorContract):
    """Exponential Moving Average (EMA)."""

    def __init__(self, period: int = 20):
        super().__init__(name="EMA", version="1.0.0", params={"period": period})
        self.period = period
        self.alpha = 2.0 / (period + 1.0)

    def calculate(self, closes: np.ndarray, **kwargs) -> np.ndarray:
        n = len(closes)
        if n == 0:
            return np.array([])
        out = np.full(n, np.nan, dtype=float)
        if n < self.period:
            return out

        # Seed with initial SMA
        out[self.period - 1] = np.mean(closes[: self.period])
        for i in range(self.period, n):
            out[i] = (closes[i] * self.alpha) + (out[i - 1] * (1.0 - self.alpha))
        return out


class RSI(IndicatorContract):
    """Relative Strength Index (RSI).
    
    CRITICAL PRINCIPLE 12:
    RSI must NEVER independently generate BUY/SELL decisions.
    RSI provides momentum exhaustion evidence for portfolio review only.
    """

    def __init__(self, period: int = 14):
        super().__init__(name="RSI", version="1.0.0", params={"period": period})
        self.period = period

    def calculate(self, closes: np.ndarray, **kwargs) -> np.ndarray:
        n = len(closes)
        out = np.full(n, np.nan, dtype=float)
        if n <= self.period:
            return out

        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)

        avg_gain = np.mean(gains[: self.period])
        avg_loss = np.mean(losses[: self.period])

        if avg_loss == 0:
            out[self.period] = 100.0
        else:
            rs = avg_gain / avg_loss
            out[self.period] = 100.0 - (100.0 / (1.0 + rs))

        for i in range(self.period + 1, n):
            gain = gains[i - 1]
            loss = losses[i - 1]
            avg_gain = (avg_gain * (self.period - 1) + gain) / self.period
            avg_loss = (avg_loss * (self.period - 1) + loss) / self.period

            if avg_loss == 0:
                out[i] = 100.0
            else:
                rs = avg_gain / avg_loss
                out[i] = 100.0 - (100.0 / (1.0 + rs))

        return out


class ATR(IndicatorContract):
    """Average True Range (ATR) - Volatility measure."""

    def __init__(self, period: int = 14):
        super().__init__(name="ATR", version="1.0.0", params={"period": period})
        self.period = period

    def calculate(self, closes: np.ndarray, **kwargs) -> np.ndarray:
        highs = kwargs.get("highs")
        lows = kwargs.get("lows")
        if highs is None or lows is None:
            raise ValueError("ATR requires 'highs' and 'lows' arrays.")

        n = len(closes)
        out = np.full(n, np.nan, dtype=float)
        if n <= self.period:
            return out

        tr = np.zeros(n, dtype=float)
        tr[0] = highs[0] - lows[0]
        for i in range(1, n):
            hl = highs[i] - lows[i]
            hc = abs(highs[i] - closes[i - 1])
            lc = abs(lows[i] - closes[i - 1])
            tr[i] = max(hl, hc, lc)

        out[self.period - 1] = np.mean(tr[: self.period])
        for i in range(self.period, n):
            out[i] = (out[i - 1] * (self.period - 1) + tr[i]) / self.period

        return out
