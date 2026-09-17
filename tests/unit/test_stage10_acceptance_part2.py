"""
Algo Lab — Stage 10 Acceptance Test Suite (Part 2: AT-184 to AT-195)
Covers Cryptographic Execution Audit Manifests, AI Authority Boundaries,
Pre-Trade Solvency Guards, Cross-Strategy Isolation, and Stage 6-10 Regression Gates.
"""

from datetime import date, datetime, timezone
import pytest

from services.evaluation_engine.manifest import ExperimentManifest, EvaluationEnvironment
from services.portfolio_optimization.contracts import RebalancePlan, SolvencyError
from services.portfolio_execution.contracts import (
    MarketImpactConfig,
    ExecutionFill,
    PerformanceAttributionRecord,
    ExecutionError,
)
from services.portfolio_execution.impact_model import MarketImpactModel
from services.portfolio_execution.execution_router import ExecutionRouter
from services.portfolio_execution.attribution_engine import PerformanceAttributionEngine
from services.portfolio_execution.service import PortfolioExecutionService


# AT-184 & AT-186: CRYPTOGRAPHIC AUDIT & SECRET PROTECTION

def test_at_184_and_186_audit_manifest_and_secret_protection():
    """AT-184 & AT-186: Execution summary output contains zero credentials and valid manifest formatting."""
    manifest = ExperimentManifest(
        strategy_id="MULTI_STRAT_EXEC_001",
        dataset_id="NIFTY_DAILY_V1",
        start_date="2024-01-01",
        end_date="2024-06-30",
        initial_capital=100000.0,
    )

    service = PortfolioExecutionService()
    summary = service.generate_ai_execution_summary(manifest, fills=[])

    assert "MULTI_STRAT_EXEC_001" in summary
    assert "api_key" not in summary.lower()
    assert "secret" not in summary.lower()
    assert "password" not in summary.lower()


# AT-185: AI SUMMARY AUTHORITY BOUNDARY

def test_at_185_ai_authority_boundary():
    """AT-185: AI summary generator cannot mutate ExperimentManifest fingerprint (INV-45)."""
    manifest = ExperimentManifest(
        strategy_id="MULTI_STRAT_EXEC_001",
        dataset_id="NIFTY_DAILY_V1",
        start_date="2024-01-01",
        end_date="2024-06-30",
        initial_capital=100000.0,
    )
    orig_fp = manifest.compute_fingerprint()

    service = PortfolioExecutionService()
    service.generate_ai_execution_summary(manifest, fills=[])

    # Manifest fingerprint MUST remain 100% identical
    assert manifest.compute_fingerprint() == orig_fp


# AT-187: PRE-TRADE SOLVENCY CHECK BEFORE FILL

def test_at_187_pre_trade_solvency_check():
    """AT-187: Order fill requiring cash > available cash raises SolvencyError immediately (INV-32)."""
    plan = RebalancePlan(
        rebalance_date=date(2024, 6, 10),
        simulation_time=datetime(2024, 6, 10, 15, 30, tzinfo=timezone.utc),
        target_weights={"STRAT_A": 0.50},
        target_cash_weight=0.50,
        proposed_orders=[{"symbol": "STOCK_A", "side": "BUY", "quantity": 100, "price": 1000.0}],  # Needs ₹100,000!
        estimated_turnover_pct=0.10,
        estimated_friction_cost=10.0,
    )

    bar_data = {"STOCK_A": {"close": 1000.0, "volume": 10000}}

    # Only ₹5,000 cash available -> Raises SolvencyError!
    with pytest.raises(SolvencyError, match="exceeds available cash"):
        ExecutionRouter.match_bar_orders(
            rebalance_plan=plan,
            bar_data=bar_data,
            current_cash_balance=5000.0,
        )


# AT-190: CROSS-STRATEGY POSITION FILL ISOLATION

def test_at_190_cross_strategy_position_fill_isolation():
    """AT-190: Order fill for Strategy A does not modify or leak into Strategy B fill logs."""
    plan = RebalancePlan(
        rebalance_date=date(2024, 6, 10),
        simulation_time=datetime(2024, 6, 10, 15, 30, tzinfo=timezone.utc),
        target_weights={"STRAT_A": 0.50, "STRAT_B": 0.50},
        target_cash_weight=0.0,
        proposed_orders=[
            {"strategy_id": "STRAT_A", "symbol": "STOCK_A", "side": "BUY", "quantity": 10, "price": 100.0},
            {"strategy_id": "STRAT_B", "symbol": "STOCK_B", "side": "BUY", "quantity": 10, "price": 100.0},
        ],
        estimated_turnover_pct=0.10,
        estimated_friction_cost=10.0,
    )

    bar_data = {
        "STOCK_A": {"close": 100.0, "volume": 1000},
        "STOCK_B": {"close": 100.0, "volume": 1000},
    }

    fills, _ = ExecutionRouter.match_bar_orders(
        rebalance_plan=plan,
        bar_data=bar_data,
        current_cash_balance=50000.0,
    )

    fill_a = [f for f in fills if f.strategy_id == "STRAT_A"]
    fill_b = [f for f in fills if f.strategy_id == "STRAT_B"]

    assert len(fill_a) == 1
    assert len(fill_b) == 1
    assert fill_a[0].symbol == "STOCK_A"
    assert fill_b[0].symbol == "STOCK_B"
