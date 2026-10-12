"""
Algo Lab — Cross-Sectional Alpha Factor Research & Evaluation Engine.

Provides institutional factor analysis using pure numpy/pandas (Zero scipy dependency):
1. Cross-sectional z-score factor standardization.
2. Spearman Rank Information Coefficient (Rank IC) and Pearson IC.
3. Factor decay and autocorrelation tracking.
4. Quintile return monotonicity and long-short spread analysis (Q5 - Q1).
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
from pydantic import BaseModel, Field


def _spearman_rank_correlation(x: List[float], y: List[float]) -> float:
    """Computes exact Spearman rank correlation using pure numpy/pandas."""
    n = len(x)
    if n < 3:
        return 0.0

    rx = pd.Series(x).rank().values
    ry = pd.Series(y).rank().values

    cov = np.cov(rx, ry)[0][1]
    std_x = np.std(rx, ddof=1)
    std_y = np.std(ry, ddof=1)
    if std_x < 1e-9 or std_y < 1e-9:
        return 0.0
    return float(cov / (std_x * std_y))


class FactorMetricsReport(BaseModel):
    factor_name: str
    periods_analyzed: int
    mean_rank_ic: float = Field(description="Mean Spearman Rank Information Coefficient")
    std_rank_ic: float = Field(description="Standard deviation of Rank IC")
    rank_ic_ir: float = Field(description="Information Ratio of Rank IC (Mean / Std)")
    t_statistic: float = Field(description="t-statistic testing H0: IC == 0")
    p_value: float = Field(description="Two-tailed p-value for statistical significance")
    factor_autocorrelation: float = Field(description="Mean 1-lag rank autocorrelation (persistence)")
    q5_annualized_return: float = Field(description="Top quintile annualized return")
    q1_annualized_return: float = Field(description="Bottom quintile annualized return")
    long_short_spread: float = Field(description="Q5 - Q1 spread (long top quintile, short bottom)")
    is_monotonic: bool = Field(description="True if quintile returns are strictly increasing Q1 < ... < Q5")


class FactorResearchEngine:
    """Institutional Factor Evaluation Pipeline (WorldQuant / AQR standard)."""

    @staticmethod
    def standardize_cross_section(scores: Dict[str, float]) -> Dict[str, float]:
        """Winsorizes and normalizes factor scores into cross-sectional Z-scores."""
        if len(scores) < 3:
            return scores

        vals = np.array(list(scores.values()), dtype=float)
        mean = float(np.mean(vals))
        std = float(np.std(vals))
        if std < 1e-9:
            return {k: 0.0 for k in scores}

        z_scores = (vals - mean) / std
        clipped = np.clip(z_scores, -3.0, 3.0)
        return {k: float(clipped[i]) for i, k in enumerate(scores.keys())}

    @staticmethod
    def calculate_period_rank_ic(
        factor_values: Dict[str, float],
        forward_returns: Dict[str, float],
    ) -> Optional[float]:
        """Calculates Spearman rank correlation between factor values at t and forward returns at t+1."""
        common_symbols = sorted(list(set(factor_values.keys()) & set(forward_returns.keys())))
        if len(common_symbols) < 4:
            return None

        f_vals = [factor_values[s] for s in common_symbols]
        r_vals = [forward_returns[s] for s in common_symbols]

        corr = _spearman_rank_correlation(f_vals, r_vals)
        if math.isnan(corr):
            return 0.0
        return float(corr)

    @classmethod
    def evaluate_factor_panel(
        cls,
        factor_panel: List[Tuple[str, Dict[str, float], Dict[str, float]]],
        factor_name: str = "Alpha_Factor",
        periods_per_year: int = 252,
    ) -> FactorMetricsReport:
        """
        Evaluates a complete time series of cross-sectional factor snapshots.
        factor_panel: List of tuples (date_str, factor_dict, forward_return_dict)
        """
        rank_ics: List[float] = []
        autocorrs: List[float] = []
        prev_factors: Optional[Dict[str, float]] = None

        quintile_returns: List[List[float]] = [[] for _ in range(5)]

        for _, f_dict, ret_dict in factor_panel:
            std_factors = cls.standardize_cross_section(f_dict)
            ic = cls.calculate_period_rank_ic(std_factors, ret_dict)
            if ic is not None:
                rank_ics.append(ic)

            # Autocorrelation
            if prev_factors:
                common = list(set(std_factors.keys()) & set(prev_factors.keys()))
                if len(common) >= 4:
                    ac = _spearman_rank_correlation(
                        [std_factors[s] for s in common],
                        [prev_factors[s] for s in common],
                    )
                    if not math.isnan(ac):
                        autocorrs.append(float(ac))
            prev_factors = std_factors

            # Quintile bucket returns
            common_symbols = sorted(list(set(std_factors.keys()) & set(ret_dict.keys())))
            if len(common_symbols) >= 5:
                sorted_syms = sorted(common_symbols, key=lambda s: std_factors[s])
                n = len(sorted_syms)
                bucket_size = n / 5.0
                for q in range(5):
                    start_idx = int(round(q * bucket_size))
                    end_idx = int(round((q + 1) * bucket_size))
                    q_syms = sorted_syms[start_idx:end_idx]
                    if q_syms:
                        avg_q_ret = float(np.mean([ret_dict[s] for s in q_syms]))
                        quintile_returns[q].append(avg_q_ret)

        n_periods = len(rank_ics)
        if n_periods < 3:
            return FactorMetricsReport(
                factor_name=factor_name,
                periods_analyzed=n_periods,
                mean_rank_ic=0.0,
                std_rank_ic=0.0,
                rank_ic_ir=0.0,
                t_statistic=0.0,
                p_value=1.0,
                factor_autocorrelation=0.0,
                q5_annualized_return=0.0,
                q1_annualized_return=0.0,
                long_short_spread=0.0,
                is_monotonic=False,
            )

        mean_ic = float(np.mean(rank_ics))
        std_ic = float(np.std(rank_ics, ddof=1)) if n_periods > 1 else 1e-6
        ic_ir = (mean_ic / std_ic) if std_ic > 1e-9 else 0.0

        t_stat = (mean_ic / (std_ic / math.sqrt(n_periods))) if std_ic > 1e-9 else 0.0
        # Normal approximation for p-value with n > 10
        p_val = 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(t_stat) / math.sqrt(2.0))))

        mean_ac = float(np.mean(autocorrs)) if autocorrs else 0.0

        q_annual = []
        for q in range(5):
            mean_q = float(np.mean(quintile_returns[q])) if quintile_returns[q] else 0.0
            q_annual.append(mean_q * periods_per_year)

        ls_spread = q_annual[4] - q_annual[0]
        is_mono = all(q_annual[i] <= q_annual[i + 1] for i in range(4))

        return FactorMetricsReport(
            factor_name=factor_name,
            periods_analyzed=n_periods,
            mean_rank_ic=round(mean_ic, 4),
            std_rank_ic=round(std_ic, 4),
            rank_ic_ir=round(ic_ir, 4),
            t_statistic=round(t_stat, 4),
            p_value=round(p_val, 6),
            factor_autocorrelation=round(mean_ac, 4),
            q5_annualized_return=round(q_annual[4], 4),
            q1_annualized_return=round(q_annual[0], 4),
            long_short_spread=round(ls_spread, 4),
            is_monotonic=is_mono,
        )
