"""
Algo Lab — Stage 9 Acceptance Test Suite (Part 1: AT-136 to AT-150)
Covers Multi-Strategy Allocation, Degradation Throttling, Macro Scaling,
Deterministic Rebalancing, Cash Solvency, and AST Execution Isolation.
"""

import ast
from datetime import datetime, date, timezone
from pathlib import Path
import pytest

from services.evaluation_engine.manifest import (
    ExperimentManifest,
    EvaluationEnvironment,
)
from services.portfolio_optimization.contracts import (
    WeightingScheme,
    StrategyAllocationConfig,
    PortfolioRiskBudget,
    AllocationError,
    SolvencyError,
    MissingMetricError,
    ASTIsolationError,
)
from services.portfolio_optimization.risk_budgeting import RiskBudgetingEngine
from services.portfolio_optimization.dynamic_allocator import DynamicAllocationEngine
from services.portfolio_optimization.rebalancer import PortfolioRebalancer
from services.portfolio_optimization.service import PortfolioOptimizationService
from services.evaluation_engine.walk_forward import LookAheadBiasError


BASE_DIR = Path(__file__).resolve().parent.parent.parent
PORTFOLIO_DIR = BASE_DIR / "services" / "portfolio_optimization"

FORBIDDEN_IMPORT_PATTERNS = [
    "services.paper_engine.adapters",
    "services.paper_engine.adapters.base",
    "services.paper_engine.adapters.upstox",
    "services.paper_engine.adapters.zerodha",
    "services.paper_engine.adapters.credentials",
    "kiteconnect",
    "upstox_client",
    "interactive_brokers",
    "ib_insync",
    "alpaca_trade_api",
    "smartapi",
    "NorenApi",
    "services.execution_engine",
    "services.execution-engine",
    "socket",
    "websockets",
]


# AT-157: STRUCTURAL AST EXECUTION ISOLATION SCANNER FOR STAGE 9

def test_at_157_structural_ast_execution_isolation():
    """AT-157: Statically parses all Python modules in services/portfolio_optimization/
    and asserts zero prohibited broker or execution imports exist (INV-33).
    """
    assert PORTFOLIO_DIR.exists(), f"Directory missing: {PORTFOLIO_DIR}"
    py_files = list(PORTFOLIO_DIR.glob("*.py"))
    assert len(py_files) > 0, "No Python files found in portfolio_optimization"

    for py_file in py_files:
        content = py_file.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(py_file))

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for forbidden in FORBIDDEN_IMPORT_PATTERNS:
                        assert not alias.name.startswith(forbidden), (
                            f"AT-157 Violation in {py_file.name}:{node.lineno}: "
                            f"Prohibited import '{alias.name}' detected."
                        )

            elif isinstance(node, ast.ImportFrom):
                module_name = node.module or ""
                for forbidden in FORBIDDEN_IMPORT_PATTERNS:
                    assert not module_name.startswith(forbidden), (
                        f"AT-157 Violation in {py_file.name}:{node.lineno}: "
                        f"Prohibited import from '{module_name}' detected."
                    )


# AT-158: LIVE ENVIRONMENT FAIL-CLOSED LOCKOUT

def test_at_158_live_environment_lockout():
    """AT-158: Assert configuring PortfolioOptimizationService with LIVE environment fails closed."""
    with pytest.raises(PermissionError, match="LIVE is strictly forbidden"):
        PortfolioOptimizationService(environment=EvaluationEnvironment.LIVE)


# AT-136: VALID MULTI-STRATEGY CAPITAL ALLOCATION

def test_at_136_valid_multi_strategy_allocation():
    """AT-136: Equal weight scheme across 3 strategies assigns equal weights + 5% cash floor."""
    configs = [
        StrategyAllocationConfig("STRAT_A", base_weight=0.316667),
        StrategyAllocationConfig("STRAT_B", base_weight=0.316667),
        StrategyAllocationConfig("STRAT_C", base_weight=0.316667),
    ]
    deg_scores = {"STRAT_A": 0.10, "STRAT_B": 0.12, "STRAT_C": 0.15}

    weights, cash_w, records = DynamicAllocationEngine.calculate_allocations(
        scheme=WeightingScheme.EQUAL_WEIGHT,
        configs=configs,
        strategy_degradation_scores=deg_scores,
        cash_floor_pct=0.05,
    )

    assert len(weights) == 3
    assert abs(weights["STRAT_A"] - 0.316667) < 1e-4
    assert abs(cash_w - 0.05) < 1e-4
    assert abs(sum(weights.values()) + cash_w - 1.0) < 1e-5


# AT-137: WALK-FORWARD DEGRADATION THROTTLING

def test_at_137_degradation_throttling():
    """AT-137: Strategy A degradation > max_degradation_threshold (0.40) is throttled to 0.0 weight."""
    configs = [
        StrategyAllocationConfig("STRAT_A", base_weight=0.40, max_degradation_threshold=0.40),
        StrategyAllocationConfig("STRAT_B", base_weight=0.40, max_degradation_threshold=0.40),
    ]
    deg_scores = {"STRAT_A": 0.45, "STRAT_B": 0.10}  # STRAT_A degraded!

    weights, cash_w, records = DynamicAllocationEngine.calculate_allocations(
        scheme=WeightingScheme.DEGRADATION_ADJUSTED,
        configs=configs,
        strategy_degradation_scores=deg_scores,
        cash_floor_pct=0.05,
    )

    assert weights["STRAT_A"] == 0.0
    assert weights["STRAT_B"] > 0.0
    rec_a = next(r for r in records if r.strategy_id == "STRAT_A")
    assert rec_a.is_throttled is True


# AT-138: MACRO REGIME ALIGNMENT SCALING

def test_at_138_macro_regime_scaling():
    """AT-138: Bearish macro regime score (-0.80) scales equity weights down."""
    configs = [StrategyAllocationConfig("STRAT_MOMENTUM", base_weight=0.40)]
    deg_scores = {"STRAT_MOMENTUM": 0.10}

    # Bullish macro (score = 0.5)
    w_bull, cash_bull, _ = DynamicAllocationEngine.calculate_allocations(
        scheme=WeightingScheme.MACRO_ALIGNED,
        configs=configs,
        strategy_degradation_scores=deg_scores,
        macro_regime_score=0.50,
    )

    # Bearish macro (score = -0.8)
    w_bear, cash_bear, _ = DynamicAllocationEngine.calculate_allocations(
        scheme=WeightingScheme.MACRO_ALIGNED,
        configs=configs,
        strategy_degradation_scores=deg_scores,
        macro_regime_score=-0.80,
    )

    assert w_bear["STRAT_MOMENTUM"] < w_bull["STRAT_MOMENTUM"]
    assert cash_bear > cash_bull


# AT-139: DETERMINISTIC REBALANCE ORDER GENERATION

def test_at_139_rebalance_order_generation():
    """AT-139: Generates discrete, deterministic asset-level buy/sell orders."""
    plan = PortfolioRebalancer.generate_rebalance_plan(
        rebalance_date=date(2024, 6, 10),
        sim_time=datetime(2024, 6, 10, 15, 30, tzinfo=timezone.utc),
        current_portfolio_value=100000.0,
        current_cash_balance=51000.0,
        target_weights={"STRAT_A": 0.50},
        target_cash_weight=0.50,
        current_positions={"NSE_RELIANCE": 0},
        asset_prices={"NSE_RELIANCE": 2500.0},
    )

    assert len(plan.proposed_orders) == 1
    order = plan.proposed_orders[0]
    assert order["symbol"] == "NSE_RELIANCE"
    assert order["side"] == "BUY"
    assert order["quantity"] == 20  # 50,000 / 2,500 = 20 shares


# AT-140: SOLVENCY VERIFICATION UNDER FRICTION

def test_at_140_solvency_verification():
    """AT-140: Required buy costs + friction exceeding cash raises SolvencyError."""
    with pytest.raises(SolvencyError, match="exceeds available cash"):
        PortfolioRebalancer.generate_rebalance_plan(
            rebalance_date=date(2024, 6, 10),
            sim_time=datetime(2024, 6, 10, 15, 30, tzinfo=timezone.utc),
            current_portfolio_value=10000.0,
            current_cash_balance=1000.0,  # Only ₹1,000 cash!
            target_weights={"STRAT_A": 0.90},  # Wants ₹9,000 buy!
            target_cash_weight=0.10,
            current_positions={},
            asset_prices={"STOCK_A": 9000.0},
            cost_per_trade_pct=0.05,  # 5% friction
        )


# AT-141 to AT-144: CONCENTRATION & ALLOCATION BOUNDARIES

def test_at_141_to_144_concentration_and_allocation_boundaries():
    # AT-141: Concentration cap enforcement
    cfg = StrategyAllocationConfig("STRAT_A", base_weight=0.50, max_weight_cap=0.35)
    assert cfg.max_weight_cap == 0.35

    # AT-142: Zero strategy signals -> 100% cash allocation
    configs = [StrategyAllocationConfig("STRAT_ZERO", base_weight=0.0)]
    weights, cash_w, _ = DynamicAllocationEngine.calculate_allocations(
        scheme=WeightingScheme.EQUAL_WEIGHT,
        configs=configs,
        strategy_degradation_scores={"STRAT_ZERO": 0.0},
    )
    assert weights["STRAT_ZERO"] == 0.0
    assert cash_w == 1.0

    # AT-143: Negative strategy weight rejection
    with pytest.raises(ValueError, match="cannot be negative"):
        StrategyAllocationConfig("STRAT_NEG", base_weight=-0.20)

    # AT-144: Total allocation overflow rejection
    configs_overflow = [
        StrategyAllocationConfig("S1", base_weight=0.50),
        StrategyAllocationConfig("S2", base_weight=0.40),
        StrategyAllocationConfig("S3", base_weight=0.35),  # Sum = 1.25 > 1.0
    ]
    with pytest.raises(AllocationError, match="sum to 1.2500 > 1.0"):
        DynamicAllocationEngine.calculate_allocations(
            scheme=WeightingScheme.EQUAL_WEIGHT,
            configs=configs_overflow,
            strategy_degradation_scores={"S1": 0.1, "S2": 0.1, "S3": 0.1},
        )


# AT-145 to AT-150: POINT-IN-TIME AND FAILURE GUARDS

def test_at_145_to_150_point_in_time_and_failure_guards():
    # AT-145: Missing strategy metric fail-closed gate
    configs = [StrategyAllocationConfig("STRAT_MISSING", base_weight=0.30)]
    with pytest.raises(MissingMetricError, match="Missing OOS degradation metric"):
        DynamicAllocationEngine.calculate_allocations(
            scheme=WeightingScheme.EQUAL_WEIGHT,
            configs=configs,
            strategy_degradation_scores={},  # Empty metrics!
        )

    # AT-146: Stale macro data throttling flag
    configs_stale = [StrategyAllocationConfig("STRAT_STALE", base_weight=0.40)]
    w_stale, _, records = DynamicAllocationEngine.calculate_allocations(
        scheme=WeightingScheme.EQUAL_WEIGHT,
        configs=configs_stale,
        strategy_degradation_scores={"STRAT_STALE": 0.10},
        stale_macro_warning=True,
    )
    assert w_stale["STRAT_STALE"] <= 0.20  # Capped at 50% factor
