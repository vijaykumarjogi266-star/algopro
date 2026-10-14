"""AST Architecture Isolation & Execution Simulator Tests for Workstream F.

Enforces:
1. Sovereign Risk Isolation: Strategies, AI bots, and news agents must never import broker
   adapters or directly submit live orders.
2. SimulationExecutionContract: Accurate calculation of Indian statutory taxes (STT, SEBI, GST, Stamp Duty).
3. Volume participation cap and square-root slippage mechanics.
4. Tail-risk metric analytics (VaR 95/99, CVaR 95/99).
"""

import ast
import os
import glob
from pathlib import Path
import numpy as np
import pytest

from services.backtest_engine.contracts import OrderSide, OrderType
from services.backtest_engine.simulator_contract import (
    FillPriceModel,
    PartialFillPolicy,
    SimulationExecutionContract,
    SlippageModelType,
    compute_tail_risk_metrics,
)
from data.schemas.contracts import OHLCVBar, AssetClass, Exchange, TimeFrame
from datetime import datetime, timezone


def test_ast_strategy_isolation_from_broker_execution():
    """Safety Invariant #4 & #5: Strategies must never import broker adapters or call broker APIs directly."""
    strategy_files = glob.glob("quant/strategies/*.py")
    assert len(strategy_files) > 0, "No strategy files found to check"

    forbidden_imports = {
        "services.execution_gateway",
        "services.execution_engine",
        "kiteconnect",
        "zerodha",
    }

    for filepath in strategy_files:
        with open(filepath, "r", encoding="utf-8") as f:
            code = f.read()

        tree = ast.parse(code, filename=filepath)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for forbidden in forbidden_imports:
                        assert forbidden not in alias.name, (
                            f"Violation in {filepath}: Strategy directly imports '{alias.name}'. "
                            f"Strategies must not import broker execution modules."
                        )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for forbidden in forbidden_imports:
                    assert forbidden not in module, (
                        f"Violation in {filepath}: Strategy directly imports from '{module}'. "
                        f"Strategies must not import broker execution modules."
                    )


def test_ast_news_and_ai_agents_isolation():
    """AI and news reasoning agents must not possess direct order submission capability."""
    agent_files = [
        "run_news_fundamentals_agent.py",
        "run_autonomous_research_bot.py",
    ]

    for filepath in agent_files:
        if not os.path.exists(filepath):
            continue
        with open(filepath, "r", encoding="utf-8") as f:
            code = f.read()

        tree = ast.parse(code, filename=filepath)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "services.execution_gateway.broker_router" not in alias.name, (
                        f"Violation in {filepath}: Agent imports direct execution router"
                    )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert "services.execution_gateway.broker_router" not in module, (
                    f"Violation in {filepath}: Agent imports direct execution router"
                )


def test_simulation_contract_statutory_indian_taxes():
    """Simulation contract calculates exact statutory fees for Indian equity trades."""
    contract = SimulationExecutionContract()

    # Buy 100 shares at 1000 INR (Turnover = 100,000 INR)
    # Intraday BUY:
    # Brokerage: min(20, 100000 * 0.0003 = 30) => 20 INR
    # STT: 0 on intraday BUY
    # Exchange fee: 100000 * 0.0000345 = 3.45 INR
    # SEBI fee: 100000 * 0.000001 = 0.10 INR
    # GST: 18% of (20 + 3.45) = 4.221 INR
    # Stamp Duty: 100000 * 0.00015 = 15.00 INR
    costs = contract.calculate_statutory_costs(
        side=OrderSide.BUY,
        quantity=100,
        price=1000.0,
        is_intraday=True,
    )

    assert costs["brokerage"] == 20.0
    assert costs["stt"] == 0.0
    assert costs["exchange_fee"] == 3.45
    assert costs["sebi_fee"] == 0.10
    assert costs["gst"] == 4.221
    assert costs["stamp_duty"] == 15.0
    assert costs["total_costs"] == round(20.0 + 3.45 + 0.10 + 4.221 + 15.0, 4)

    # Intraday SELL:
    # STT = 100000 * 0.00025 = 25 INR
    # Stamp Duty = 0 on SELL
    costs_sell = contract.calculate_statutory_costs(
        side=OrderSide.SELL,
        quantity=100,
        price=1000.0,
        is_intraday=True,
    )
    assert costs_sell["stt"] == 25.0
    assert costs_sell["stamp_duty"] == 0.0


def test_simulation_contract_volume_participation_cap():
    """Execution simulator strictly caps fill quantity at 10% of bar volume."""
    contract = SimulationExecutionContract(
        volume_participation_cap_pct=0.10,
        partial_fill_policy=PartialFillPolicy.PRO_RATA_VOLUME,
    )

    # Bar volume = 500 shares. Max 10% = 50 shares
    bar = OHLCVBar(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        asset_class=AssetClass.EQUITY,
        timeframe=TimeFrame.M5,
        market_timestamp=datetime(2024, 1, 10, 10, 0, tzinfo=timezone.utc),
        open=2500.0,
        high=2510.0,
        low=2495.0,
        close=2505.0,
        volume=500.0,
    )

    # Order requests 200 shares, capped at 50
    filled_qty, exec_price, slippage, costs = contract.simulate_fill(
        side=OrderSide.BUY,
        requested_quantity=200,
        base_price=2500.0,
        bar=bar,
    )
    assert filled_qty == 50
    assert exec_price >= 2500.0
    assert slippage > 0.0


def test_compute_tail_risk_metrics():
    """Tail-loss analytics correctly compute VaR and CVaR at 95% and 99% confidence."""
    # Synthetic return series with a fat negative tail
    returns = np.array([
        0.01, 0.005, -0.002, 0.008, -0.001,
        0.012, -0.004, -0.015, -0.025, -0.05,
    ] * 10)  # 100 observations

    metrics = compute_tail_risk_metrics(returns)
    assert "var_95" in metrics
    assert "cvar_95" in metrics
    assert "var_99" in metrics
    assert "cvar_99" in metrics

    # CVaR (Expected Shortfall) is weakly greater in magnitude than VaR
    assert metrics["cvar_95"] >= metrics["var_95"]
    assert metrics["cvar_99"] >= metrics["var_99"]
