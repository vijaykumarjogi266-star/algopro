"""Algo Lab Experiment Comparison Engine.

Provides transparent, purely descriptive comparison between experiments and backtest runs.
Adheres to Non-Negotiable Principles:
- Purely descriptive: Compares parameters, datasets, versions, and quantitative metrics directly.
- Strict Non-Ranking: NEVER ranks experiments, declares a "winner", assigns a composite score,
  or generates automated BUY/SELL recommendations.
- Non-Fabriction: Never fabricates missing metrics; missing values are explicitly marked None/Unavailable.
- Immutability: Comparison never mutates underlying experiment or run data structures.
"""

import copy
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from services.backtest_engine.contracts import (
    ExperimentDefinition,
    BacktestMetrics,
)


class ParameterDifference(BaseModel):
    param_name: str
    baseline_value: Any
    target_value: Any
    is_different: bool


class MetricDifference(BaseModel):
    metric_name: str
    baseline_value: Optional[float] = None
    target_value: Optional[float] = None
    difference: Optional[float] = None
    difference_pct: Optional[float] = None
    is_available: bool = True


class ExperimentComparisonResult(BaseModel):
    baseline_experiment_id: str
    target_experiment_id: str
    same_fingerprint: bool
    dataset_changed: bool
    strategy_version_changed: bool
    universe_changed: bool
    timeframe_changed: bool
    parameters_different: Dict[str, ParameterDifference]
    metric_differences: Dict[str, MetricDifference]
    baseline_metadata: Dict[str, Any]
    target_metadata: Dict[str, Any]
    is_descriptive_only: bool = True  # Strict architectural invariant


class ExperimentComparator:
    """Performs side-by-side descriptive comparative analysis between two experiments."""

    @staticmethod
    def compare(
        baseline_exp: ExperimentDefinition,
        target_exp: ExperimentDefinition,
        baseline_metrics: Optional[BacktestMetrics] = None,
        target_metrics: Optional[BacktestMetrics] = None,
        baseline_trades_count: int = 0,
        target_trades_count: int = 0,
        baseline_rejected_count: int = 0,
        target_rejected_count: int = 0,
    ) -> ExperimentComparisonResult:
        """Compares two experiment definitions and their execution metrics immutably."""
        # Deepcopy to guarantee zero mutation of caller inputs
        b_exp = copy.deepcopy(baseline_exp)
        t_exp = copy.deepcopy(target_exp)
        b_met = copy.deepcopy(baseline_metrics)
        t_met = copy.deepcopy(target_metrics)

        # 1. Structural differences
        same_fp = b_exp.fingerprint == t_exp.fingerprint
        dataset_changed = (
            b_exp.dataset_id != t_exp.dataset_id
            or b_exp.dataset_version != t_exp.dataset_version
            or b_exp.dataset_checksum != t_exp.dataset_checksum
        )
        strat_ver_changed = b_exp.strategy_version != t_exp.strategy_version
        universe_changed = sorted(b_exp.universe) != sorted(t_exp.universe)
        timeframe_changed = b_exp.timeframe != t_exp.timeframe

        # 2. Parameter differences
        all_param_keys = set(b_exp.parameters.keys()).union(set(t_exp.parameters.keys()))
        param_diffs: Dict[str, ParameterDifference] = {}
        for k in sorted(all_param_keys):
            b_val = b_exp.parameters.get(k)
            t_val = t_exp.parameters.get(k)
            diff = b_val != t_val
            param_diffs[k] = ParameterDifference(
                param_name=k,
                baseline_value=b_val,
                target_value=t_val,
                is_different=diff,
            )

        # 3. Quantitative metrics differences
        metric_diffs: Dict[str, MetricDifference] = {}

        metrics_spec = [
            ("total_return_pct", "Total Return (%)"),
            ("cagr_pct", "CAGR (%)"),
            ("sharpe_ratio", "Sharpe Ratio"),
            ("sortino_ratio", "Sortino Ratio"),
            ("maximum_drawdown_pct", "Max Drawdown (%)"),
            ("win_rate", "Win Rate (Hit Rate)"),
            ("average_win", "Average Win (INR)"),
            ("average_loss", "Average Loss (INR)"),
            ("profit_factor", "Profit Factor"),
            ("expectancy", "Expectancy (INR)"),
            ("exposure_pct", "Market Exposure (%)"),
            ("total_transaction_costs", "Cost Drag (INR)"),
            ("total_slippage_impact", "Slippage Drag (INR)"),
        ]

        for attr, label in metrics_spec:
            b_val = getattr(b_met, attr, None) if b_met else None
            t_val = getattr(t_met, attr, None) if t_met else None

            if b_val is not None and t_val is not None:
                delta = round(t_val - b_val, 4)
                delta_pct = round((delta / abs(b_val)) * 100.0, 2) if b_val != 0 else None
                is_avail = True
            else:
                delta = None
                delta_pct = None
                is_avail = False

            metric_diffs[attr] = MetricDifference(
                metric_name=label,
                baseline_value=round(b_val, 4) if b_val is not None else None,
                target_value=round(t_val, 4) if t_val is not None else None,
                difference=delta,
                difference_pct=delta_pct,
                is_available=is_avail,
            )

        # Trade Counts & Rejections
        b_trades = baseline_trades_count or (baseline_metrics.number_of_trades if baseline_metrics else None)
        t_trades = target_trades_count or (target_metrics.number_of_trades if target_metrics else None)
        if b_trades is not None and t_trades is not None:
            t_delta = t_trades - b_trades
            metric_diffs["number_of_trades"] = MetricDifference(
                metric_name="Number of Trades",
                baseline_value=float(b_trades),
                target_value=float(t_trades),
                difference=float(t_delta),
                difference_pct=round((t_delta / b_trades) * 100.0, 2) if b_trades > 0 else None,
                is_available=True,
            )
        else:
            metric_diffs["number_of_trades"] = MetricDifference(
                metric_name="Number of Trades",
                baseline_value=float(b_trades) if b_trades is not None else None,
                target_value=float(t_trades) if t_trades is not None else None,
                difference=None,
                difference_pct=None,
                is_available=False,
            )

        has_run_data = (baseline_metrics is not None or baseline_rejected_count > 0) and (target_metrics is not None or target_rejected_count > 0)
        if has_run_data:
            r_delta = target_rejected_count - baseline_rejected_count
            metric_diffs["rejected_trades_count"] = MetricDifference(
                metric_name="Risk Rejections",
                baseline_value=float(baseline_rejected_count),
                target_value=float(target_rejected_count),
                difference=float(r_delta),
                difference_pct=round((r_delta / baseline_rejected_count) * 100.0, 2) if baseline_rejected_count > 0 else None,
                is_available=True,
            )
        else:
            metric_diffs["rejected_trades_count"] = MetricDifference(
                metric_name="Risk Rejections",
                baseline_value=float(baseline_rejected_count) if (baseline_metrics is not None or baseline_rejected_count > 0) else None,
                target_value=float(target_rejected_count) if (target_metrics is not None or target_rejected_count > 0) else None,
                difference=None,
                difference_pct=None,
                is_available=False,
            )

        return ExperimentComparisonResult(
            baseline_experiment_id=b_exp.experiment_id,
            target_experiment_id=t_exp.experiment_id,
            same_fingerprint=same_fp,
            dataset_changed=dataset_changed,
            strategy_version_changed=strat_ver_changed,
            universe_changed=universe_changed,
            timeframe_changed=timeframe_changed,
            parameters_different=param_diffs,
            metric_differences=metric_diffs,
            baseline_metadata={
                "name": b_exp.name,
                "strategy_id": b_exp.strategy_id,
                "strategy_version": b_exp.strategy_version,
                "fingerprint": b_exp.fingerprint,
                "dataset_id": b_exp.dataset_id,
            },
            target_metadata={
                "name": t_exp.name,
                "strategy_id": t_exp.strategy_id,
                "strategy_version": t_exp.strategy_version,
                "fingerprint": t_exp.fingerprint,
                "dataset_id": t_exp.dataset_id,
            },
            is_descriptive_only=True,
        )
