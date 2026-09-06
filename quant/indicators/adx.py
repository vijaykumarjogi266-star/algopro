"""Average Directional Index (ADX) Indicator."""

from typing import Dict, List, Optional, Union
import numpy as np
from quant.indicators.base import IndicatorContract


class ADX(IndicatorContract):
    """Average Directional Index (ADX).
    
    Measures the strength of a prevailing trend, independent of trend direction.
    Standardized scale: 0 to 100.
    - ADX < 20: Weak or absent trend (range-bound / mean-reverting regime).
    - ADX > 25: Established directional trend.
    - ADX > 50: Extremely strong directional trend.
    Evidence role: Market regime filter (trend vs range regime discrimination).
    """

    def __init__(self, period: int = 14):
        if period <= 1:
            raise ValueError("ADX period must be greater than 1.")
        super().__init__(
            name="ADX",
            version="1.0.0",
            params={"period": period},
            required_columns=["high", "low", "close"],
            output_columns=["plus_di", "minus_di", "dx", "adx"],
            warm_up_period=2 * period,
        )
        self.period = period

    def calculate(self, closes: np.ndarray, **kwargs) -> Dict[str, np.ndarray]:
        highs = kwargs.get("highs", kwargs.get("high"))
        lows = kwargs.get("lows", kwargs.get("low"))
        if highs is None or lows is None:
            raise ValueError("ADX calculation requires 'highs' and 'lows' arrays.")

        n = len(closes)
        plus_di = np.full(n, np.nan, dtype=float)
        minus_di = np.full(n, np.nan, dtype=float)
        dx = np.full(n, np.nan, dtype=float)
        adx = np.full(n, np.nan, dtype=float)

        if n < self.warm_up_period:
            return {
                "plus_di": plus_di,
                "minus_di": minus_di,
                "dx": dx,
                "adx": adx,
            }

        # Calculate True Range (TR), +DM, -DM
        tr = np.zeros(n, dtype=float)
        plus_dm = np.zeros(n, dtype=float)
        minus_dm = np.zeros(n, dtype=float)

        tr[0] = highs[0] - lows[0]
        for i in range(1, n):
            h_diff = highs[i] - highs[i - 1]
            l_diff = lows[i - 1] - lows[i]

            if h_diff > l_diff and h_diff > 0:
                plus_dm[i] = h_diff
            if l_diff > h_diff and l_diff > 0:
                minus_dm[i] = l_diff

            hl = highs[i] - lows[i]
            hc = abs(highs[i] - closes[i - 1])
            lc = abs(lows[i] - closes[i - 1])
            tr[i] = max(hl, hc, lc)

        # Wilder's Smoothing for TR, +DM, -DM
        smooth_tr = np.full(n, np.nan, dtype=float)
        smooth_plus_dm = np.full(n, np.nan, dtype=float)
        smooth_minus_dm = np.full(n, np.nan, dtype=float)

        p = self.period
        smooth_tr[p] = np.sum(tr[1 : p + 1])
        smooth_plus_dm[p] = np.sum(plus_dm[1 : p + 1])
        smooth_minus_dm[p] = np.sum(minus_dm[1 : p + 1])

        for i in range(p + 1, n):
            smooth_tr[i] = smooth_tr[i - 1] - (smooth_tr[i - 1] / p) + tr[i]
            smooth_plus_dm[i] = smooth_plus_dm[i - 1] - (smooth_plus_dm[i - 1] / p) + plus_dm[i]
            smooth_minus_dm[i] = smooth_minus_dm[i - 1] - (smooth_minus_dm[i - 1] / p) + minus_dm[i]

        # Calculate +DI, -DI, and DX
        for i in range(p, n):
            if smooth_tr[i] > 0:
                p_di = 100.0 * (smooth_plus_dm[i] / smooth_tr[i])
                m_di = 100.0 * (smooth_minus_dm[i] / smooth_tr[i])
                plus_di[i] = p_di
                minus_di[i] = m_di
                di_sum = p_di + m_di
                if di_sum > 0:
                    dx[i] = 100.0 * (abs(p_di - m_di) / di_sum)
                else:
                    dx[i] = 0.0

        # Calculate ADX (Wilder's smoothing of DX)
        adx_start = 2 * p - 1
        if n > adx_start:
            adx[adx_start] = np.mean(dx[p : adx_start + 1])
            for i in range(adx_start + 1, n):
                adx[i] = (adx[i - 1] * (p - 1) + dx[i]) / p

        return {
            "plus_di": plus_di,
            "minus_di": minus_di,
            "dx": dx,
            "adx": adx,
        }
