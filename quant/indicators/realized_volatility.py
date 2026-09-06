"""Realized Volatility Indicator."""

from typing import Dict, List, Optional, Union
import numpy as np
from quant.indicators.base import IndicatorContract


class RealizedVolatility(IndicatorContract):
    """Realized Volatility (Annualized).
    
    Computes the sample standard deviation of historical log returns over a rolling window:
    r_t = ln(Close_t / Close_t-1)
    Realized Volatility = std(r, period) * sqrt(annualization_factor) * 100
    
    Evidence role: Quantitative regime classification, volatility forecasting, option pricing comparison.
    """

    def __init__(self, period: int = 20, annualization_factor: float = 252.0):
        if period <= 1:
            raise ValueError("Realized volatility period must be greater than 1.")
        if annualization_factor <= 0:
            raise ValueError("Annualization factor must be strictly positive.")

        col_name = f"realized_vol_{period}"
        super().__init__(
            name="RealizedVolatility",
            version="1.0.0",
            params={
                "period": period,
                "annualization_factor": annualization_factor,
            },
            required_columns=["close"],
            output_columns=[col_name],
            warm_up_period=period + 1,
        )
        self.period = period
        self.annualization_factor = annualization_factor
        self.output_col = col_name

    def calculate(self, closes: np.ndarray, **kwargs) -> np.ndarray:
        n = len(closes)
        out = np.full(n, np.nan, dtype=float)
        # We need period returns, which requires period + 1 prices
        if n <= self.period:
            return out

        # Compute log returns
        with np.errstate(divide="ignore", invalid="ignore"):
            log_returns = np.diff(np.log(closes))

        scale = np.sqrt(self.annualization_factor) * 100.0
        p = self.period

        for i in range(p - 1, len(log_returns)):
            window = log_returns[i - p + 1 : i + 1]
            if np.all(np.isfinite(window)):
                vol = np.std(window, ddof=1)
                # Output index aligns with original closes array (offset by 1 due to diff)
                out[i + 1] = vol * scale

        return out
