"""
Algo Lab — Stage 7 Sensitivity Analysis & Friction Stress Sweeps
Evaluates strategy robustness against cost (+10%, +25%, +50%) and slippage (2x, 5x) perturbations.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from services.evaluation_engine.manifest import ExperimentManifest, FrictionConfig
from services.evaluation_engine.engine import DeterministicEvaluationEngine, EvaluationResult
from services.evaluation_engine.analytics import PerformanceAnalytics, PerformanceMetrics


@dataclass
class SensitivityScenarioResult:
    scenario_name: str
    cost_multiplier: float
    slippage_multiplier: float
    total_net_return: float
    final_equity: float
    total_friction_cost: float
    metrics: PerformanceMetrics


@dataclass
class SensitivityReport:
    base_result: SensitivityScenarioResult
    stress_scenarios: List[SensitivityScenarioResult]
    is_monotonic_degradation: bool
    autonomous_deployment_blocked: bool = True  # AT-58 invariant guard


class SensitivityEngine:
    """Executes multi-tier friction stress testing and parameter neighborhood sweeps."""

    def __init__(self, manifest: ExperimentManifest):
        self.manifest = manifest

    def run_stress_sweep(
        self,
        bars: List[Dict[str, Any]],
        signals: Optional[List[Dict[str, Any]]] = None,
    ) -> SensitivityReport:
        """Runs base friction run + multi-tier cost (+10%, +25%, +50%) and slippage (2x, 5x) sweeps."""

        base_friction = self.manifest.friction_config
        scenarios_config = [
            ("BASE", 1.0, 1.0),
            ("COST_+10%", 1.10, 1.0),
            ("COST_+25%", 1.25, 1.0),
            ("COST_+50%", 1.50, 1.0),
            ("SLIPPAGE_2X", 1.0, 2.0),
            ("SLIPPAGE_5X", 1.0, 5.0),
        ]

        scenario_results: List[SensitivityScenarioResult] = []

        for name, cost_mult, slip_mult in scenarios_config:
            stressed_friction = FrictionConfig(
                brokerage_per_order=base_friction.brokerage_per_order * cost_mult,
                stt_rate=base_friction.stt_rate * cost_mult,
                exchange_turnover_fee_rate=base_friction.exchange_turnover_fee_rate * cost_mult,
                gst_rate=base_friction.gst_rate * cost_mult,
                stamp_duty_rate=base_friction.stamp_duty_rate * cost_mult,
                fixed_tick_slippage_pts=base_friction.fixed_tick_slippage_pts * slip_mult,
                variable_slippage_pct=base_friction.variable_slippage_pct * slip_mult,
            )

            # Build modified manifest copy
            stressed_manifest = ExperimentManifest(
                strategy_id=self.manifest.strategy_id,
                dataset_id=self.manifest.dataset_id,
                timeframe=self.manifest.timeframe,
                start_date=self.manifest.start_date,
                end_date=self.manifest.end_date,
                initial_capital=self.manifest.initial_capital,
                parameters=self.manifest.parameters,
                friction_config=stressed_friction,
                partitions=self.manifest.partitions,
                environment=self.manifest.environment,
            )

            engine = DeterministicEvaluationEngine(manifest=stressed_manifest)
            eval_res = engine.evaluate_bar_series(bars=bars, signals=signals)
            metrics = PerformanceAnalytics.calculate_metrics(
                equity_curve=eval_res.equity_curve,
                trades=eval_res.trades,
            )

            res = SensitivityScenarioResult(
                scenario_name=name,
                cost_multiplier=cost_mult,
                slippage_multiplier=slip_mult,
                total_net_return=eval_res.total_net_return,
                final_equity=eval_res.final_equity,
                total_friction_cost=eval_res.total_friction_cost,
                metrics=metrics,
            )
            scenario_results.append(res)

        base_res = scenario_results[0]
        cost_scenarios = scenario_results[1:4]  # +10%, +25%, +50%

        # Check monotonic net return degradation for cost increases
        is_monotonic = True
        prev_ret = base_res.total_net_return
        for sc in cost_scenarios:
            if sc.total_net_return > prev_ret + 1e-9:  # should decrease or stay equal
                is_monotonic = False
            prev_ret = sc.total_net_return

        return SensitivityReport(
            base_result=base_res,
            stress_scenarios=scenario_results[1:],
            is_monotonic_degradation=is_monotonic,
            autonomous_deployment_blocked=True,  # AT-58 guard enforced
        )
