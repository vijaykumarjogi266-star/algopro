"""
Algo Lab — Stage 8 Acceptance Test Suite (Part 1: AT-101 to AT-120)
Covers Market Breadth, FII/DII Flow Ingestion, Publication Timestamp Guards,
Sector Rotation, AST Execution Isolation, and Manifest Audit Provenance.
"""

import ast
from datetime import datetime, date, timezone, timedelta
from pathlib import Path
import pytest

from services.evaluation_engine.manifest import (
    ExperimentManifest,
    EvaluationEnvironment,
    FrictionConfig,
)
from services.evaluation_engine.partitioning import create_disjoint_partitions
from services.market_intelligence.contracts import (
    PointInTimeRecord,
    SectorMembershipRecord,
    BreadthRecord,
    InstitutionalFlowRecord,
    SectorRank,
    MissingTimestampError,
    SourceConflictError,
    MarketIntelligenceError,
)
from services.market_intelligence.breadth import MarketBreadthCalculator
from services.market_intelligence.institutional_flows import InstitutionalFlowProcessor
from services.market_intelligence.sector_rotation import SectorRotationEngine
from services.market_intelligence.service import MarketIntelligenceService
from services.evaluation_engine.walk_forward import LookAheadBiasError
from services.risk_engine.engine import RiskEngine
from services.risk_engine.contracts import HardRiskLimits


BASE_DIR = Path(__file__).resolve().parent.parent.parent
MARKET_INTELLIGENCE_DIR = BASE_DIR / "services" / "market-intelligence"


# AT-109: STRUCTURAL AST EXECUTION ISOLATION SCANNER FOR STAGE 8

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


def test_at_109_structural_ast_execution_isolation():
    """AT-109: Statically parses all Python modules in services/market-intelligence/
    and asserts zero prohibited broker or execution imports exist (INV-22).
    """
    assert MARKET_INTELLIGENCE_DIR.exists(), f"Directory missing: {MARKET_INTELLIGENCE_DIR}"

    py_files = list(MARKET_INTELLIGENCE_DIR.glob("*.py"))
    assert len(py_files) > 0, "No Python files found in market-intelligence"

    for py_file in py_files:
        content = py_file.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(py_file))

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for forbidden in FORBIDDEN_IMPORT_PATTERNS:
                        assert not alias.name.startswith(forbidden), (
                            f"AT-109 Violation in {py_file.name}:{node.lineno}: "
                            f"Prohibited import '{alias.name}' detected."
                        )

            elif isinstance(node, ast.ImportFrom):
                module_name = node.module or ""
                for forbidden in FORBIDDEN_IMPORT_PATTERNS:
                    assert not module_name.startswith(forbidden), (
                        f"AT-109 Violation in {py_file.name}:{node.lineno}: "
                        f"Prohibited import from '{module_name}' detected."
                    )


# AT-110: LIVE ENVIRONMENT FAIL-CLOSED LOCKOUT

def test_at_110_live_environment_lockout():
    """AT-110: Assert configuring MarketIntelligenceService with LIVE environment fails closed."""
    with pytest.raises(PermissionError, match="LIVE is strictly forbidden"):
        MarketIntelligenceService(environment=EvaluationEnvironment.LIVE)


# AT-101 & AT-102: MARKET BREADTH CALCULATIONS

def test_at_101_and_102_valid_breadth_and_sma_calculation():
    """AT-101 & AT-102: Valid Market Breadth & % Above SMA calculation."""
    ts = datetime(2024, 6, 10, 15, 30, tzinfo=timezone.utc)
    # Generate 3 stock price histories
    histories = {
        "STOCK_A": [100.0 + i for i in range(60)],   # Upward trend (above 20, 50 SMA)
        "STOCK_B": [200.0 - i for i in range(60)],   # Downward trend
        "STOCK_C": [150.0] * 60,                     # Flat
    }

    breadth = MarketBreadthCalculator.calculate_breadth(
        timestamp=ts,
        universe_id="NIFTY_50",
        stock_price_histories=histories,
    )

    assert breadth.universe_id == "NIFTY_50"
    assert breadth.advances_count == 1   # STOCK_A
    assert breadth.declines_count == 1   # STOCK_B
    assert breadth.unchanged_count == 1  # STOCK_C
    assert breadth.ad_ratio == 1.0       # 1 / 1
    assert 0.0 <= breadth.pct_above_50_sma <= 1.0


# AT-103 to AT-108: INSTITUTIONAL FLOW PROCESSOR & PUBLICATION GUARDS

def test_at_103_to_108_flow_ingestion_and_publication_guards():
    pub_time = datetime(2024, 6, 10, 18, 0, tzinfo=timezone.utc)
    rec = PointInTimeRecord(
        event_date=date(2024, 6, 10),
        publication_timestamp=pub_time,
        retrieval_timestamp=pub_time + timedelta(minutes=5),
        dataset_version_id="FII_DII_2024_V1",
        revision_sequence_id=0,
        payload={
            "fii_cash_net": 1250.5,
            "dii_cash_net": -450.0,
            "fii_cash_buy": 5000.0,
            "fii_cash_sell": 3749.5,
            "dii_cash_buy": 2000.0,
            "dii_cash_sell": 2450.0,
        },
    )

    processor = InstitutionalFlowProcessor([rec])

    # AT-106 & AT-108: Flow Publication Guard (Pre-18:00 IST query raises LookAheadBiasError)
    pre_pub_sim_time = datetime(2024, 6, 10, 15, 30, tzinfo=timezone.utc)
    with pytest.raises(LookAheadBiasError, match="Look-ahead access attempt"):
        processor.get_eligible_flow(date(2024, 6, 10), pre_pub_sim_time)

    # AT-107: Post-Publication Access (Query at 18:30 IST returns valid record)
    post_pub_sim_time = datetime(2024, 6, 10, 18, 30, tzinfo=timezone.utc)
    flow_post = processor.get_eligible_flow(date(2024, 6, 10), post_pub_sim_time)
    assert flow_post is not None
    assert flow_post.fii_cash_net == 1250.5
    assert flow_post.dii_cash_net == -450.0


# AT-111 & AT-112: SECTOR ROTATION & DETERMINISTIC TIE-BREAKING

def test_at_111_and_112_sector_rotation_ranking_and_tie_breaker():
    engine = SectorRotationEngine()
    target_dt = date(2024, 6, 10)

    # Benchmark: 10% gain
    benchmark_prices = [100.0, 110.0]

    # Sector price series
    sector_prices = {
        "NIFTY_IT": [100.0, 125.0],      # +25% gain (RS = +15%) -> LEADING
        "NIFTY_BANK": [100.0, 115.0],    # +15% gain (RS = +5%) -> LEADING
        "NIFTY_AUTO": [100.0, 115.0],    # +15% gain (RS = +5%) -> Tied score with NIFTY_BANK!
        "NIFTY_PHARMA": [100.0, 90.0],   # -10% gain (RS = -20%) -> LAGGING
    }

    ranks = engine.calculate_sector_rankings(target_dt, sector_prices, benchmark_prices)

    assert len(ranks) == 4
    assert ranks[0].sector_id == "NIFTY_IT"
    assert ranks[0].rank == 1

    # AT-112: Tied RS score (+5%) sorted by symbol alphabetical order: NIFTY_AUTO before NIFTY_BANK
    assert ranks[1].sector_id == "NIFTY_AUTO"
    assert ranks[1].rank == 2
    assert ranks[2].sector_id == "NIFTY_BANK"
    assert ranks[2].rank == 3


# AT-114: HARD RISK LIMIT PRECEDENCE

def test_at_114_hard_risk_limit_precedence():
    """AT-114: Verifies hard risk limits override bullish market intelligence signals."""
    risk_limits = HardRiskLimits(
        max_capital_per_trade_pct=0.20,   # 20% max capital per trade limit (Pydantic max)
        max_portfolio_drawdown_pct=0.10,  # 10% max drawdown limit
    )
    risk_engine = RiskEngine(limits=risk_limits)

    # Attempt trade under 15% drawdown condition (qty=1 -> trade value 2500 <= 20000 limit)
    res = risk_engine.evaluate(
        symbol="NSE_RELIANCE",
        price=2500.0,
        proposed_quantity=1,
        stop_loss=2400.0,
        current_portfolio_value=100000.0,
        current_daily_loss_pct=0.02,
        current_drawdown_pct=0.15,  # 15% drawdown breaches 10% max limit!
        current_open_positions_count=1,
    )

    assert res.is_approved is False
    assert "drawdown" in res.rejection_reason.lower()
