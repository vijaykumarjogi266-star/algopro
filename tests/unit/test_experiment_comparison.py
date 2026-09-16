"""Tests verifying Experiment Comparison Engine (Phase F).

Adheres to Non-Negotiable Research Invariants:
- Purely descriptive: Compares parameters, datasets, versions, and quantitative metrics directly.
- Strict Non-Ranking: NEVER ranks experiments, declares a "winner", assigns a composite score,
  or generates automated BUY/SELL recommendations.
- Non-Fabrication: Never fabricates missing metrics; missing values are explicitly marked None/Unavailable.
- Immutability: Comparison never mutates underlying experiment or run data structures.
"""

from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

from services.backtest_engine.contracts import (
    ExperimentDefinition,
    BacktestMetrics,
    CostModelConfig,
    SlippageModelConfig,
)
from services.backtest_engine.comparison import (
    ExperimentComparator,
    ExperimentComparisonResult,
    ParameterDifference,
    MetricDifference,
)
from services.backtest_engine.service import BacktestService
from apps.api.main import app
from apps.api.routes.experiments import set_service


def make_experiment(
    experiment_id: str = "exp_001",
    name: str = "Test SMA Alpha",
    strategy_id: str = "Canonical_SMA",
    strategy_version: str = "1.0.0",
    dataset_id: str = "NSE_NIFTY50_DAILY",
    dataset_version: str = "2026.09.14",
    dataset_checksum: str = "f" * 64,
    universe: list = None,
    timeframe: str = "1d",
    parameters: dict = None,
    initial_capital: float = 500_000.0,
) -> ExperimentDefinition:
    return ExperimentDefinition(
        experiment_id=experiment_id,
        name=name,
        description="Testing comparative analytics",
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        dataset_checksum=dataset_checksum,
        universe=universe or ["NIFTY50", "RELIANCE"],
        timeframe=timeframe,
        start_date=datetime(2026, 1, 1, 9, 15, tzinfo=timezone.utc),
        end_date=datetime(2026, 6, 30, 15, 30, tzinfo=timezone.utc),
        parameters=parameters or {"fast_period": 10, "slow_period": 30},
        risk_policy_version="1.0.0",
        cost_model=CostModelConfig(),
        slippage_model=SlippageModelConfig(),
        initial_capital=initial_capital,
        seed=42,
        code_revision="main",
    )


def make_metrics(
    total_return_pct: float = 12.5,
    cagr_pct: float = 26.5,
    sharpe_ratio: float = 1.85,
    sortino_ratio: float = 2.40,
    maximum_drawdown_pct: float = 4.5,
    win_rate: float = 0.65,
    number_of_trades: int = 40,
    total_transaction_costs: float = 1250.0,
    total_slippage_impact: float = 450.0,
) -> BacktestMetrics:
    return BacktestMetrics(
        total_return_pct=total_return_pct,
        cagr_pct=cagr_pct,
        sharpe_ratio=sharpe_ratio,
        sortino_ratio=sortino_ratio,
        maximum_drawdown_pct=maximum_drawdown_pct,
        win_rate=win_rate,
        average_win=3500.0,
        average_loss=1500.0,
        profit_factor=2.33,
        expectancy=1750.0,
        number_of_trades=number_of_trades,
        maximum_consecutive_losses=3,
        average_holding_time_seconds=86400.0,
        exposure_pct=42.5,
        total_transaction_costs=total_transaction_costs,
        total_slippage_impact=total_slippage_impact,
        worst_trade_pnl=-4500.0,
        worst_day_pnl=-6200.0,
    )


def test_identical_experiment_comparison():
    """Comparing an experiment to itself yields same fingerprint and zero deltas."""
    exp = make_experiment()
    metrics = make_metrics()

    res = ExperimentComparator.compare(
        baseline_exp=exp,
        target_exp=exp,
        baseline_metrics=metrics,
        target_metrics=metrics,
        baseline_trades_count=40,
        target_trades_count=40,
        baseline_rejected_count=0,
        target_rejected_count=0,
    )

    assert res.same_fingerprint is True
    assert res.dataset_changed is False
    assert res.strategy_version_changed is False
    assert res.universe_changed is False
    assert res.timeframe_changed is False
    assert all(not p.is_different for p in res.parameters_different.values())

    # Metric deltas should be exactly 0.0
    for metric_diff in res.metric_differences.values():
        assert metric_diff.is_available is True
        assert metric_diff.difference == 0.0
        if metric_diff.baseline_value != 0:
            assert metric_diff.difference_pct == 0.0


def test_parameter_difference_detection():
    """Detects hyperparameter modifications between baseline and target."""
    exp1 = make_experiment(parameters={"fast_period": 10, "slow_period": 30})
    exp2 = make_experiment(parameters={"fast_period": 20, "slow_period": 30, "filter": "ATR"})

    res = ExperimentComparator.compare(baseline_exp=exp1, target_exp=exp2)

    assert res.same_fingerprint is False
    diffs = res.parameters_different
    assert diffs["fast_period"].is_different is True
    assert diffs["fast_period"].baseline_value == 10
    assert diffs["fast_period"].target_value == 20

    assert diffs["slow_period"].is_different is False
    assert diffs["slow_period"].baseline_value == 30

    assert diffs["filter"].is_different is True
    assert diffs["filter"].baseline_value is None
    assert diffs["filter"].target_value == "ATR"


def test_dataset_and_version_change_detection():
    """Detects dataset modifications, checksum drift, and strategy version increments."""
    exp1 = make_experiment(
        dataset_id="NSE_NIFTY50_DAILY",
        dataset_version="2026.09.14",
        strategy_version="1.0.0",
    )
    exp2 = make_experiment(
        dataset_id="NSE_EQUITIES_DAILY",
        dataset_version="2026.09.15",
        strategy_version="1.1.0",
    )

    res = ExperimentComparator.compare(baseline_exp=exp1, target_exp=exp2)
    assert res.dataset_changed is True
    assert res.strategy_version_changed is True


def test_universe_and_timeframe_change_detection():
    """Detects universe scope expansion and timeframe differences."""
    exp1 = make_experiment(universe=["NIFTY50"], timeframe="1d")
    exp2 = make_experiment(universe=["NIFTY50", "RELIANCE", "TCS"], timeframe="1h")

    res = ExperimentComparator.compare(baseline_exp=exp1, target_exp=exp2)
    assert res.universe_changed is True
    assert res.timeframe_changed is True


def test_metric_delta_accuracy():
    """Calculates quantitative absolute and percentage deltas with mathematical precision."""
    exp1 = make_experiment()
    exp2 = make_experiment(parameters={"fast_period": 15, "slow_period": 45})

    m1 = make_metrics(total_return_pct=10.0, sharpe_ratio=1.5, maximum_drawdown_pct=6.0)
    m2 = make_metrics(total_return_pct=15.0, sharpe_ratio=2.0, maximum_drawdown_pct=3.0)

    res = ExperimentComparator.compare(
        baseline_exp=exp1,
        target_exp=exp2,
        baseline_metrics=m1,
        target_metrics=m2,
        baseline_trades_count=20,
        target_trades_count=30,
        baseline_rejected_count=2,
        target_rejected_count=0,
    )

    # Return delta: 15.0 - 10.0 = +5.0 (+50.0%)
    ret_diff = res.metric_differences["total_return_pct"]
    assert ret_diff.difference == 5.0
    assert ret_diff.difference_pct == 50.0

    # Sharpe delta: 2.0 - 1.5 = +0.5 (+33.33%)
    sharpe_diff = res.metric_differences["sharpe_ratio"]
    assert sharpe_diff.difference == 0.5
    assert sharpe_diff.difference_pct == 33.33

    # Max Drawdown delta: 3.0 - 6.0 = -3.0 (-50.0%)
    dd_diff = res.metric_differences["maximum_drawdown_pct"]
    assert dd_diff.difference == -3.0
    assert dd_diff.difference_pct == -50.0

    # Trade counts
    t_diff = res.metric_differences["number_of_trades"]
    assert t_diff.difference == 10.0
    assert t_diff.difference_pct == 50.0

    # Rejection count delta: 0 - 2 = -2.0 (-100.0%)
    r_diff = res.metric_differences["rejected_trades_count"]
    assert r_diff.difference == -2.0
    assert r_diff.difference_pct == -100.0


def test_missing_metrics_safety_no_fabrication():
    """Guarantees missing metrics are marked unavailable and never fabricated."""
    exp1 = make_experiment()
    exp2 = make_experiment()

    # Neither experiment has executed
    res = ExperimentComparator.compare(
        baseline_exp=exp1,
        target_exp=exp2,
        baseline_metrics=None,
        target_metrics=None,
    )

    for k, diff in res.metric_differences.items():
        assert diff.is_available is False
        assert diff.difference is None
        assert diff.difference_pct is None
        assert diff.baseline_value is None
        assert diff.target_value is None


def test_immutability_zero_mutation():
    """Comparison execution must never mutate input objects."""
    exp1 = make_experiment()
    exp2 = make_experiment(parameters={"fast_period": 25})
    m1 = make_metrics()
    m2 = make_metrics(total_return_pct=20.0)

    p1_copy = dict(exp1.parameters)
    p2_copy = dict(exp2.parameters)

    ExperimentComparator.compare(
        baseline_exp=exp1,
        target_exp=exp2,
        baseline_metrics=m1,
        target_metrics=m2,
    )

    assert exp1.parameters == p1_copy
    assert exp2.parameters == p2_copy
    assert m1.total_return_pct == 12.5
    assert m2.total_return_pct == 20.0


def test_strict_non_ranking_invariant():
    """Comparison result must be purely descriptive with no rankings, scores, or recommendations."""
    exp1 = make_experiment()
    exp2 = make_experiment()
    res = ExperimentComparator.compare(baseline_exp=exp1, target_exp=exp2)

    assert res.is_descriptive_only is True
    res_dict = res.model_dump()
    forbidden_terms = ["winner", "score", "rank", "recommendation", "verdict", "rating"]
    for term in forbidden_terms:
        assert term not in res_dict


def test_api_compare_endpoint():
    """Verifies POST /api/v1/experiments/compare endpoint integration."""
    service = BacktestService()
    set_service(service)
    client = TestClient(app)

    # 1. Create two experiments
    payload1 = {
        "name": "Exp Alpha",
        "strategy_id": "Canonical_SMA",
        "strategy_version": "1.0.0",
        "dataset_id": "NSE_NIFTY50_DAILY",
        "dataset_version": "2026.09.14",
        "dataset_checksum": "f" * 64,
        "universe": ["NIFTY50"],
        "timeframe": "1d",
        "start_date": "2026-01-01T09:15:00Z",
        "end_date": "2026-06-30T15:30:00Z",
        "parameters": {"fast_period": 10, "slow_period": 30},
        "initial_capital": 500000.0,
    }
    r1 = client.post("/api/v1/experiments", json=payload1)
    assert r1.status_code == 201
    id1 = r1.json()["experiment_id"]

    payload2 = dict(payload1)
    payload2["name"] = "Exp Beta"
    payload2["parameters"] = {"fast_period": 15, "slow_period": 45}
    r2 = client.post("/api/v1/experiments", json=payload2)
    assert r2.status_code == 201
    id2 = r2.json()["experiment_id"]

    # 2. Compare them
    cmp_res = client.post(
        "/api/v1/experiments/compare",
        json={"baseline_experiment_id": id1, "target_experiment_id": id2},
    )
    assert cmp_res.status_code == 200
    data = cmp_res.json()
    assert data["baseline_experiment_id"] == id1
    assert data["target_experiment_id"] == id2
    assert data["is_descriptive_only"] is True
    assert data["parameters_different"]["fast_period"]["is_different"] is True
    assert data["parameters_different"]["slow_period"]["is_different"] is True

    # 3. Test 404 handling
    err_res = client.post(
        "/api/v1/experiments/compare",
        json={"baseline_experiment_id": "nonexistent_id", "target_experiment_id": id2},
    )
    assert err_res.status_code == 404
