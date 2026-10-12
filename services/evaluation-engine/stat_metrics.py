"""
Algo Lab — Institutional Statistical Significance & Hypothesis Testing Suite.

Implements pure-numpy / math implementations (Zero external C/Fortran binary dependencies):
1. Probabilistic Sharpe Ratio (PSR) (Bailey & López de Prado, 2012)
2. Deflated Sharpe Ratio (DSR) (Bailey & López de Prado, 2014) - Multi-testing selection bias correction.
3. Higher-moment risk metrics: Skewness, Kurtosis, Tail Ratio, Omega Ratio, Gain-to-Pain Ratio.
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple, Union
import numpy as np
from pydantic import BaseModel, Field


def _norm_cdf(x: float) -> float:
    """Accurate standard normal cumulative distribution function (error < 7.5e-8)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    """Accurate standard normal percent-point function / inverse CDF using inverse error function."""
    if p <= 0.0:
        return -8.0
    if p >= 1.0:
        return 8.0
    if abs(p - 0.5) < 1e-12:
        return 0.0

    # Relationship: _norm_ppf(p) = sqrt(2) * erfinv(2*p - 1)
    # Winitzki approximation for erfinv(y):
    y = (2.0 * p) - 1.0
    a = 0.147
    sgn = 1.0 if y > 0 else -1.0
    y_clamped = min(abs(y), 1.0 - 1e-15)

    log_term = math.log(1.0 - (y_clamped ** 2))
    part1 = (2.0 / (math.pi * a)) + (log_term / 2.0)
    inner = part1 ** 2 - (log_term / a)
    erfinv_val = sgn * math.sqrt(math.sqrt(inner) - part1)

    return math.sqrt(2.0) * erfinv_val


class StatisticalSignificanceReport(BaseModel):
    sample_size: int = Field(description="Number of discrete return observations")
    annualized_sharpe: float = Field(description="Annualized empirical Sharpe ratio")
    benchmark_sharpe: float = Field(default=0.0, description="Null-hypothesis benchmark Sharpe ratio")
    skewness: float = Field(description="Return distribution skewness (3rd standardized moment)")
    kurtosis: float = Field(description="Return distribution kurtosis (4th standardized moment)")
    psr: float = Field(description="Probabilistic Sharpe Ratio [0, 1]")
    dsr: float = Field(description="Deflated Sharpe Ratio [0, 1] adjusted for trials")
    number_of_trials: int = Field(default=1, description="Number of tested strategy variants/parameters")
    var_sharpe_trials: float = Field(default=0.0, description="Variance of Sharpe ratios across all trials")
    expected_max_sharpe: float = Field(description="Expected maximum Sharpe ratio under the null hypothesis (luck)")
    tail_ratio: float = Field(description="95th percentile return / abs(5th percentile return)")
    omega_ratio: float = Field(description="Probability-weighted ratio of gains vs losses above threshold")
    is_statistically_significant: bool = Field(description="True if DSR >= 0.95 (5% significance level)")


class StatisticalMetricsEngine:
    """Institutional testing engine adjusting for non-normality and backtest overfitting."""

    @staticmethod
    def calculate_higher_moments(returns: np.ndarray) -> Tuple[float, float]:
        """Calculates skewness and Pearson kurtosis without external dependencies."""
        n = len(returns)
        if n < 4:
            return 0.0, 3.0

        mean = float(np.mean(returns))
        std = float(np.std(returns, ddof=1))
        if std < 1e-9:
            return 0.0, 3.0

        diff = returns - mean
        m3 = float(np.mean(diff ** 3))
        m4 = float(np.mean(diff ** 4))

        # Sample bias corrections
        skew = m3 / (std ** 3)
        kurt = m4 / (std ** 4)  # Pearson kurtosis (Normal = 3.0)

        if math.isnan(skew) or math.isinf(skew):
            skew = 0.0
        if math.isnan(kurt) or math.isinf(kurt) or kurt <= 0.0:
            kurt = 3.0

        return float(skew), float(kurt)

    @classmethod
    def calculate_psr(
        cls,
        sharpe: float,
        skew: float,
        kurt: float,
        sample_size: int,
        benchmark_sharpe: float = 0.0,
    ) -> float:
        """
        Calculates Probabilistic Sharpe Ratio (PSR).
        PSR(SR*) = N((SR - SR*) * sqrt(T - 1) / sqrt(1 - skew*SR + (kurt - 1)/4 * SR^2))
        """
        if sample_size <= 2:
            return 0.5

        denom_sq = 1.0 - (skew * sharpe) + (((kurt - 1.0) / 4.0) * (sharpe ** 2))
        if denom_sq <= 1e-9:
            return 1.0 if sharpe > benchmark_sharpe else 0.0

        std_err = math.sqrt(denom_sq / (sample_size - 1.0))
        z_stat = (sharpe - benchmark_sharpe) / std_err
        psr = _norm_cdf(z_stat)
        return min(max(psr, 0.0), 1.0)

    @classmethod
    def expected_maximum_sharpe(
        cls,
        number_of_trials: int,
        var_trials: float,
    ) -> float:
        """
        Computes expected maximum Sharpe ratio under null hypothesis of zero skill.
        """
        if number_of_trials <= 1:
            return 0.0

        euler_mascheroni = 0.5772156649
        std_trials = math.sqrt(max(var_trials, 1e-6))

        term1 = (1.0 - euler_mascheroni) * _norm_ppf(1.0 - (1.0 / number_of_trials))
        term2 = euler_mascheroni * _norm_ppf(1.0 - (1.0 / (number_of_trials * math.e)))
        expected_max = (term1 + term2) * std_trials
        return max(0.0, float(expected_max))

    @classmethod
    def calculate_dsr(
        cls,
        sharpe: float,
        skew: float,
        kurt: float,
        sample_size: int,
        number_of_trials: int = 1,
        var_trials: float = 0.0,
    ) -> Tuple[float, float]:
        """Calculates Deflated Sharpe Ratio (DSR) discounting for multiple trials."""
        if number_of_trials <= 1 or var_trials <= 0.0:
            psr = cls.calculate_psr(sharpe, skew, kurt, sample_size, benchmark_sharpe=0.0)
            return psr, 0.0

        exp_max_sr = cls.expected_maximum_sharpe(number_of_trials, var_trials)
        dsr = cls.calculate_psr(sharpe, skew, kurt, sample_size, benchmark_sharpe=exp_max_sr)
        return dsr, exp_max_sr

    @classmethod
    def evaluate_returns_series(
        cls,
        returns: Union[List[float], np.ndarray],
        periods_per_year: int = 252,
        number_of_trials: int = 1,
        var_trials: float = 0.0,
        benchmark_annual_sharpe: float = 0.0,
    ) -> StatisticalSignificanceReport:
        """Performs full institutional statistical audit on a return stream."""
        arr = np.array(returns, dtype=float)
        arr = arr[~np.isnan(arr)]

        sample_size = len(arr)
        if sample_size < 5:
            return StatisticalSignificanceReport(
                sample_size=sample_size,
                annualized_sharpe=0.0,
                benchmark_sharpe=benchmark_annual_sharpe,
                skewness=0.0,
                kurtosis=3.0,
                psr=0.5,
                dsr=0.5,
                number_of_trials=number_of_trials,
                var_sharpe_trials=var_trials,
                expected_max_sharpe=0.0,
                tail_ratio=1.0,
                omega_ratio=1.0,
                is_statistically_significant=False,
            )

        mean_ret = float(np.mean(arr))
        std_ret = float(np.std(arr, ddof=1)) if sample_size > 1 else 0.0

        daily_sharpe = (mean_ret / std_ret) if std_ret > 1e-9 else 0.0
        annual_sharpe = daily_sharpe * math.sqrt(periods_per_year)

        skew, kurt = cls.calculate_higher_moments(arr)

        benchmark_daily_sharpe = benchmark_annual_sharpe / math.sqrt(periods_per_year)
        psr = cls.calculate_psr(daily_sharpe, skew, kurt, sample_size, benchmark_sharpe=benchmark_daily_sharpe)

        daily_var_trials = var_trials / periods_per_year if var_trials > 0 else 0.0
        dsr, exp_max_daily_sr = cls.calculate_dsr(
            sharpe=daily_sharpe,
            skew=skew,
            kurt=kurt,
            sample_size=sample_size,
            number_of_trials=number_of_trials,
            var_trials=daily_var_trials,
        )
        exp_max_annual_sr = exp_max_daily_sr * math.sqrt(periods_per_year)

        p95 = float(np.percentile(arr, 95))
        p05 = float(np.percentile(arr, 5))
        tail_ratio = abs(p95 / p05) if abs(p05) > 1e-9 else 1.0

        pos_returns = arr[arr > 0]
        neg_returns = arr[arr < 0]
        sum_gains = float(np.sum(pos_returns)) if len(pos_returns) > 0 else 0.0
        sum_losses = float(abs(np.sum(neg_returns))) if len(neg_returns) > 0 else 1e-9
        omega_ratio = sum_gains / sum_losses

        is_significant = bool(dsr >= 0.95 and annual_sharpe > 0.0)

        return StatisticalSignificanceReport(
            sample_size=sample_size,
            annualized_sharpe=round(annual_sharpe, 4),
            benchmark_sharpe=benchmark_annual_sharpe,
            skewness=round(skew, 4),
            kurtosis=round(kurt, 4),
            psr=round(psr, 4),
            dsr=round(dsr, 4),
            number_of_trials=number_of_trials,
            var_sharpe_trials=round(var_trials, 4),
            expected_max_sharpe=round(exp_max_annual_sr, 4),
            tail_ratio=round(tail_ratio, 4),
            omega_ratio=round(omega_ratio, 4),
            is_statistically_significant=is_significant,
        )


# Backward-compatibility alias
StatMetricsEngine = StatisticalMetricsEngine
StatisticalMetricsEngine.calculate_moments = StatisticalMetricsEngine.calculate_higher_moments
