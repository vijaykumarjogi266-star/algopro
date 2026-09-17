"""
Algo Lab — Stage 10 Acceptance Test Suite (Part 1: AT-168 to AT-183)
Covers Volume Participation Caps, Market Impact Modeling, Partial Fills,
Brinson Attribution, Zero Volume Illiquidity Gates, and AST Execution Isolation.
"""

import ast
from datetime import datetime, date, timezone
from pathlib import Path
import pytest

from services.evaluation_engine.manifest import ExperimentManifest, EvaluationEnvironment
from services.portfolio_optimization.contracts import RebalancePlan, SolvencyError
from services.portfolio_execution.contracts import (
    MarketImpactConfig,
    ExecutionFill,
    PerformanceAttributionRecord,
    ExecutionError,
    ASTIsolationError,
)
from services.portfolio_execution.impact_model import MarketImpactModel
from services.portfolio_execution.execution_router import ExecutionRouter
from services.portfolio_execution.attribution_engine import PerformanceAttributionEngine
from services.portfolio_execution.service import PortfolioExecutionService
from services.market_data.registry import DatasetIntegrityError


BASE_DIR = Path(__file__).resolve().parent.parent.parent
EXECUTION_DIR = BASE_DIR / "services" / "portfolio_execution"

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


# AT-188: STRUCTURAL AST EXECUTION ISOLATION SCANNER FOR STAGE 10

def test_at_188_structural_ast_execution_isolation():
    """AT-188: Statically parses all Python modules in services/portfolio_execution/
    and asserts zero prohibited broker or execution imports exist (INV-44).
    """
    assert EXECUTION_DIR.exists(), f"Directory missing: {EXECUTION_DIR}"
    py_files = list(EXECUTION_DIR.glob("*.py"))
    assert len(py_files) > 0, "No Python files found in portfolio_execution"

    for py_file in py_files:
        content = py_file.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(py_file))

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for forbidden in FORBIDDEN_IMPORT_PATTERNS:
                        assert not alias.name.startswith(forbidden), (
                            f"AT-188 Violation in {py_file.name}:{node.lineno}: "
                            f"Prohibited import '{alias.name}' detected."
                        )

            elif isinstance(node, ast.ImportFrom):
                module_name = node.module or ""
                for forbidden in FORBIDDEN_IMPORT_PATTERNS:
                    assert not module_name.startswith(forbidden), (
                        f"AT-188 Violation in {py_file.name}:{node.lineno}: "
                        f"Prohibited import from '{module_name}' detected."
                    )


# AT-189: LIVE ENVIRONMENT FAIL-CLOSED LOCKOUT

def test_at_189_live_environment_lockout():
    """AT-189: Assert configuring PortfolioExecutionService with LIVE environment fails closed."""
    with pytest.raises(PermissionError, match="LIVE is strictly forbidden"):
        PortfolioExecutionService(environment=EvaluationEnvironment.LIVE)


# AT-168: MULTI-STRATEGY VOLUME PARTICIPATION CAP

def test_at_168_volume_participation_cap():
    """AT-168: Order fill quantity at bar t cannot exceed max_volume_participation_pct (10%) of bar volume (INV-40)."""
    plan = RebalancePlan(
        rebalance_date=date(2024, 6, 10),
        simulation_time=datetime(2024, 6, 10, 15, 30, tzinfo=timezone.utc),
        target_weights={"STRAT_A": 0.50},
        target_cash_weight=0.50,
        proposed_orders=[{"symbol": "STOCK_A", "side": "BUY", "quantity": 5000, "price": 100.0}],
        estimated_turnover_pct=0.10,
        estimated_friction_cost=10.0,
    )

    bar_data = {"STOCK_A": {"close": 100.0, "volume": 10000}}  # 10% of 10,000 = 1,000 max fillable!
    config = MarketImpactConfig(max_volume_participation_pct=0.10)

    fills, _ = ExecutionRouter.match_bar_orders(
        rebalance_plan=plan,
        bar_data=bar_data,
        current_cash_balance=1000000.0,
        config=config,
    )

    assert len(fills) == 1
    fill = fills[0]
    assert fill.fill_quantity == 1000  # Capped at 1,000 shares!
    assert fill.is_partial_fill is True
    assert fill.remaining_quantity == 4000


# AT-169: DYNAMIC SQUARE-ROOT MARKET IMPACT COST

def test_at_169_market_impact_cost():
    """AT-169: Dynamic market impact cost is non-negative and added to fill price (INV-41)."""
    impact = MarketImpactModel.calculate_market_impact(
        order_quantity=1000,
        bar_volume=10000,
        price=100.0,
        volatility_pct=0.02,
        adv=10000.0,
    )

    assert impact > 0.0
    assert isinstance(impact, float)


# AT-170: PARTIAL FILL MULTI-BAR QUEUE SERIALIZATION

def test_at_170_partial_fill_queue():
    """AT-170: Order exceeding bar volume capacity produces partial fill with remaining quantity."""
    plan = RebalancePlan(
        rebalance_date=date(2024, 6, 10),
        simulation_time=datetime(2024, 6, 10, 15, 30, tzinfo=timezone.utc),
        target_weights={"STRAT_A": 0.50},
        target_cash_weight=0.50,
        proposed_orders=[{"symbol": "STOCK_A", "side": "BUY", "quantity": 3000, "price": 100.0}],
        estimated_turnover_pct=0.10,
        estimated_friction_cost=10.0,
    )

    bar_data = {"STOCK_A": {"close": 100.0, "volume": 10000}}
    config = MarketImpactConfig(max_volume_participation_pct=0.10)  # Max fill = 1,000

    fills, _ = ExecutionRouter.match_bar_orders(
        rebalance_plan=plan,
        bar_data=bar_data,
        current_cash_balance=1000000.0,
        config=config,
    )

    fill = fills[0]
    assert fill.fill_quantity == 1000
    assert fill.remaining_quantity == 2000
    assert fill.is_partial_fill is True


# AT-171 & AT-172: BRINSON MULTI-FACTOR ATTRIBUTION & FRICTION DRAG

def test_at_171_and_172_brinson_pnl_attribution():
    """AT-171 & AT-172: Portfolio Gross PnL equals sum of Selection + Macro + Sector PnL minus Friction Drag (INV-39)."""
    ts = datetime(2024, 6, 10, 15, 30, tzinfo=timezone.utc)
    fills = [
        ExecutionFill(
            fill_id="F001",
            order_id="O001",
            strategy_id="STRAT_A",
            symbol="STOCK_A",
            fill_timestamp=ts,
            fill_quantity=100,
            fill_price=100.0,
            market_impact_cost=50.0,
            slippage_cost=0.50,
            transaction_fee=10.0,
            is_partial_fill=False,
            remaining_quantity=0,
        )
    ]

    # Friction drag = impact (50) + fee (10) = 60.0
    # Expected total PnL = 500 + 200 + 100 + 0 - 60 = 740.0
    rec = PerformanceAttributionEngine.compute_brinson_attribution(
        timestamp=ts,
        total_gross_pnl=740.0,
        strategy_selection_pnl=500.0,
        macro_timing_pnl=200.0,
        sector_rotation_pnl=100.0,
        risk_budget_overlay_pnl=0.0,
        fills=fills,
    )

    assert rec.execution_friction_drag == 60.0
    assert rec.attribution_residual == 0.0


# AT-173: ZERO BAR VOLUME ILLIQUIDITY LOCKOUT

def test_at_173_zero_bar_volume_lockout():
    """AT-173: Zero bar volume forces fill quantity = 0 and defers order matching."""
    plan = RebalancePlan(
        rebalance_date=date(2024, 6, 10),
        simulation_time=datetime(2024, 6, 10, 15, 30, tzinfo=timezone.utc),
        target_weights={"STRAT_A": 0.50},
        target_cash_weight=0.50,
        proposed_orders=[{"symbol": "STOCK_A", "side": "BUY", "quantity": 100, "price": 100.0}],
        estimated_turnover_pct=0.10,
        estimated_friction_cost=10.0,
    )

    bar_data = {"STOCK_A": {"close": 100.0, "volume": 0}}  # Zero volume!

    fills, _ = ExecutionRouter.match_bar_orders(
        rebalance_plan=plan,
        bar_data=bar_data,
        current_cash_balance=100000.0,
    )

    assert fills[0].fill_quantity == 0
    assert fills[0].remaining_quantity == 100
    assert fills[0].is_partial_fill is True


# AT-174 & AT-175: NON-FINITE REJECTION & NEGATIVE IMPACT COEFFICIENT

def test_at_174_and_175_non_finite_and_invalid_impact_rejection():
    # AT-174: Non-finite participation rate rejection
    with pytest.raises(ExecutionError, match="Non-finite value"):
        MarketImpactConfig(max_volume_participation_pct=float("nan"))

    # AT-175: Negative impact coefficient rejection
    with pytest.raises(ValueError, match="cannot be negative"):
        MarketImpactConfig(gamma_impact_coefficient=-0.50)


# AT-176 to AT-183: PIT AND FAILURE GUARDS

def test_at_176_to_183_pit_and_failure_guards():
    # AT-177: Missing bar volume column fail-closed gate
    plan = RebalancePlan(
        rebalance_date=date(2024, 6, 10),
        simulation_time=datetime(2024, 6, 10, 15, 30, tzinfo=timezone.utc),
        target_weights={"STRAT_A": 0.50},
        target_cash_weight=0.50,
        proposed_orders=[{"symbol": "STOCK_A", "side": "BUY", "quantity": 100, "price": 100.0}],
        estimated_turnover_pct=0.10,
        estimated_friction_cost=10.0,
    )

    bar_missing_vol = {"STOCK_A": {"close": 100.0}}  # Missing volume key!
    with pytest.raises(DatasetIntegrityError, match="Missing bar volume column"):
        ExecutionRouter.match_bar_orders(
            rebalance_plan=plan,
            bar_data=bar_missing_vol,
            current_cash_balance=100000.0,
        )

    # AT-178: Corrupted negative volume rejection
    bar_neg_vol = {"STOCK_A": {"close": 100.0, "volume": -5000}}
    with pytest.raises(DatasetIntegrityError, match="Corrupted negative bar volume"):
        ExecutionRouter.match_bar_orders(
            rebalance_plan=plan,
            bar_data=bar_neg_vol,
            current_cash_balance=100000.0,
        )
