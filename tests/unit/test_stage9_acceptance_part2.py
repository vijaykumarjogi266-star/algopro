"""
Algo Lab — Stage 9 Acceptance Test Suite (Part 2: AT-151 to AT-167)
Covers Determinism, Tie-Breaking, Cryptographic Audit Trails, AI Authority Boundaries,
Hard Risk Limit Precedence, Non-Finite Fail-Closed Gates, and Residual Cash Attribution.
"""

from datetime import date, datetime, timezone
import pytest
import json

from services.evaluation_engine.manifest import ExperimentManifest, EvaluationEnvironment
from services.portfolio_optimization.contracts import (
    WeightingScheme,
    StrategyAllocationConfig,
    PortfolioRiskBudget,
    AllocationError,
    SolvencyError,
)
from services.portfolio_optimization.risk_budgeting import RiskBudgetingEngine
from services.portfolio_optimization.dynamic_allocator import DynamicAllocationEngine
from services.portfolio_optimization.rebalancer import PortfolioRebalancer
from services.portfolio_optimization.service import PortfolioOptimizationService


# AT-151: BIT-FOR-BIT DETERMINISTIC REBALANCING

def test_at_151_deterministic_rebalancing():
    """AT-151: Running portfolio rebalancing twice on identical state produces bit-for-bit identical plan."""
    configs = [
        StrategyAllocationConfig("STRAT_A", base_weight=0.30),
        StrategyAllocationConfig("STRAT_B", base_weight=0.30),
    ]
    deg_scores = {"STRAT_A": 0.10, "STRAT_B": 0.15}

    w1, c1, _ = DynamicAllocationEngine.calculate_allocations(
        scheme=WeightingScheme.EQUAL_WEIGHT,
        configs=configs,
        strategy_degradation_scores=deg_scores,
    )

    w2, c2, _ = DynamicAllocationEngine.calculate_allocations(
        scheme=WeightingScheme.EQUAL_WEIGHT,
        configs=configs,
        strategy_degradation_scores=deg_scores,
    )

    assert w1 == w2
    assert c1 == c2


# AT-152: ALPHABETICAL STRATEGY TIE-BREAKER

def test_at_152_alphabetical_tie_breaker():
    """AT-152: Tied strategy allocation scores sort strategies by string alphabetical order."""
    configs = [
        StrategyAllocationConfig("STRATEGY_ZETA", base_weight=0.30),
        StrategyAllocationConfig("STRATEGY_ALPHA", base_weight=0.30),
    ]
    deg_scores = {"STRATEGY_ZETA": 0.10, "STRATEGY_ALPHA": 0.10}

    weights, _, records = DynamicAllocationEngine.calculate_allocations(
        scheme=WeightingScheme.EQUAL_WEIGHT,
        configs=configs,
        strategy_degradation_scores=deg_scores,
    )

    # Strategy ALPHA evaluated before Strategy ZETA
    assert records[0].strategy_id == "STRATEGY_ALPHA"
    assert records[1].strategy_id == "STRATEGY_ZETA"


# AT-153 & AT-155: CRYPTOGRAPHIC AUDIT & SECRET PROTECTION

def test_at_153_and_155_audit_manifest_and_secret_protection():
    """AT-153 & AT-155: Portfolio optimization outputs audit metadata containing zero credentials."""
    manifest = ExperimentManifest(
        strategy_id="MULTI_STRAT_ALPHA",
        dataset_id="NIFTY_DAILY_V1",
        start_date="2024-01-01",
        end_date="2024-06-30",
        initial_capital=100000.0,
    )

    service = PortfolioOptimizationService()
    summary = service.generate_ai_portfolio_summary(manifest)

    assert "MULTI_STRAT_ALPHA" in summary
    # Verify zero API keys or secret tokens
    assert "api_key" not in summary.lower()
    assert "secret" not in summary.lower()
    assert "password" not in summary.lower()


# AT-154: AI SUMMARY AUTHORITY BOUNDARY

def test_at_154_ai_authority_boundary():
    """AT-154: AI summary generator cannot mutate ExperimentManifest fingerprint."""
    manifest = ExperimentManifest(
        strategy_id="MULTI_STRAT_ALPHA",
        dataset_id="NIFTY_DAILY_V1",
        start_date="2024-01-01",
        end_date="2024-06-30",
        initial_capital=100000.0,
    )
    orig_fp = manifest.compute_fingerprint()

    service = PortfolioOptimizationService()
    service.generate_ai_portfolio_summary(manifest)

    # Manifest fingerprint MUST remain 100% identical
    assert manifest.compute_fingerprint() == orig_fp


# AT-156 & AT-167: HARD RISK LIMIT PRECEDENCE & SIMULTANEOUS MULTI-LIMIT CASCADE

def test_at_156_and_167_hard_risk_limit_precedence_and_multi_limit_cascade():
    """AT-156 & AT-167: Aggregate portfolio drawdown or volatility breach forces 100% cash allocation."""
    risk_budget = PortfolioRiskBudget(
        max_portfolio_volatility_annual=0.20,
        max_aggregate_drawdown_pct=0.15,
        max_single_strategy_weight=0.35,
    )

    configs = {"STRAT_A": StrategyAllocationConfig("STRAT_A", base_weight=0.40)}
    proposed = {"STRAT_A": 0.40}

    # Simultaneous Drawdown (18% > 15%) & Volatility (25% > 20%) breach!
    is_approved, target_cash_w, adj_weights, reason = RiskBudgetingEngine.evaluate_risk_budget(
        current_drawdown_pct=0.18,
        current_volatility_annual=0.25,
        proposed_weights=proposed,
        configs=configs,
        risk_budget=risk_budget,
    )

    assert is_approved is False
    assert target_cash_w == 1.0  # 100% cash allocation
    assert adj_weights["STRAT_A"] == 0.0
    assert "Risk Budget Breach" in reason


# AT-159: CROSS-STRATEGY STATE ISOLATION

def test_at_159_cross_strategy_state_isolation():
    """AT-159: State mutation in Strategy A cannot alter Strategy B evaluation output."""
    configs = [
        StrategyAllocationConfig("STRAT_A", base_weight=0.30),
        StrategyAllocationConfig("STRAT_B", base_weight=0.30),
    ]

    deg_isolated = {"STRAT_A": 0.10, "STRAT_B": 0.15}
    w_orig, _, _ = DynamicAllocationEngine.calculate_allocations(
        scheme=WeightingScheme.EQUAL_WEIGHT,
        configs=configs,
        strategy_degradation_scores=deg_isolated,
    )

    # Mutate STRAT_A degradation score
    deg_mutated = {"STRAT_A": 0.50, "STRAT_B": 0.15}
    w_mutated, _, _ = DynamicAllocationEngine.calculate_allocations(
        scheme=WeightingScheme.EQUAL_WEIGHT,
        configs=configs,
        strategy_degradation_scores=deg_mutated,
    )

    # STRAT_B weight logic remains isolated
    assert w_orig["STRAT_B"] == w_mutated["STRAT_B"]


# AT-160: TURNOVER CONSTRAINT ENFORCEMENT

def test_at_160_turnover_constraint_enforcement():
    """AT-160: Rebalance turnover exceeding max_turnover_pct (0.20) is scaled down."""
    plan = PortfolioRebalancer.generate_rebalance_plan(
        rebalance_date=date(2024, 6, 10),
        sim_time=datetime(2024, 6, 10, 15, 30, tzinfo=timezone.utc),
        current_portfolio_value=100000.0,
        current_cash_balance=50000.0,
        target_weights={"STRAT_A": 0.80},  # Unconstrained turnover would be 80%
        target_cash_weight=0.20,
        current_positions={},
        asset_prices={"STOCK_A": 1000.0},
        max_turnover_pct=0.20,  # 20% cap
    )

    assert plan.estimated_turnover_pct <= 0.20 + 1e-4


# AT-165: NON-FINITE FLOATING POINT REJECTION

def test_at_165_non_finite_floating_point_rejection():
    """AT-165: Passing NaN or Infinity as strategy weight raises AllocationError immediately (INV-37)."""
    with pytest.raises(AllocationError, match="Non-finite value detected"):
        StrategyAllocationConfig("STRAT_NAN", base_weight=float("nan"))

    configs = [StrategyAllocationConfig("STRAT_INF", base_weight=0.30)]
    with pytest.raises(AllocationError, match="Non-finite degradation score"):
        DynamicAllocationEngine.calculate_allocations(
            scheme=WeightingScheme.EQUAL_WEIGHT,
            configs=configs,
            strategy_degradation_scores={"STRAT_INF": float("inf")},
        )


# AT-166: RESIDUAL SHARE CASH ATTRIBUTION

def test_at_166_residual_share_cash_attribution():
    """AT-166: Unallocated cash from discrete share rounding is credited back to target_cash_weight (INV-38)."""
    # Rebalance target ₹10,000 for ₹800 stock yields 12 shares (₹9,600), leaving ₹400 residual cash
    plan = PortfolioRebalancer.generate_rebalance_plan(
        rebalance_date=date(2024, 6, 10),
        sim_time=datetime(2024, 6, 10, 15, 30, tzinfo=timezone.utc),
        current_portfolio_value=10000.0,
        current_cash_balance=10000.0,
        target_weights={"STRAT_A": 1.0},
        target_cash_weight=0.0,
        current_positions={},
        asset_prices={"STOCK_A": 800.0},
        max_turnover_pct=1.0,
    )

    assert plan.residual_cash_unallocated == 400.0  # ₹400 residual
    assert plan.target_cash_weight > 0.0  # Residual credited to cash weight!
