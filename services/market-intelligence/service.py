"""
Algo Lab — Stage 8 Integrated Market Intelligence Provider
Provides unified point-in-time access to market breadth, institutional flows,
and sector rotation metrics with strict fail-closed execution environment gating.
"""

from datetime import datetime, date
from typing import List, Dict, Any, Optional
from services.evaluation_engine.manifest import EvaluationEnvironment, ExperimentManifest
from services.market_intelligence.contracts import (
    BreadthRecord,
    InstitutionalFlowRecord,
    SectorRank,
)
from services.market_intelligence.breadth import MarketBreadthCalculator
from services.market_intelligence.institutional_flows import InstitutionalFlowProcessor
from services.market_intelligence.sector_rotation import SectorRotationEngine


class MarketIntelligenceService:
    """Unified service interface for Stage 8 market intelligence."""

    def __init__(
        self,
        environment: EvaluationEnvironment = EvaluationEnvironment.OFFLINE_SIMULATION,
        flow_processor: Optional[InstitutionalFlowProcessor] = None,
        sector_engine: Optional[SectorRotationEngine] = None,
    ):
        # AT-110: Live environment fail-closed lockout
        if environment == EvaluationEnvironment.LIVE:
            raise PermissionError(
                "ExecutionEnvironment.LIVE is strictly forbidden in Stage 8 Market Intelligence Service."
            )

        self.environment = environment
        self.flow_processor = flow_processor or InstitutionalFlowProcessor()
        self.sector_engine = sector_engine or SectorRotationEngine()

    def get_market_breadth(
        self,
        timestamp: datetime,
        universe_id: str,
        stock_histories: Dict[str, List[float]],
    ) -> BreadthRecord:
        """Computes market breadth snapshot for universe at `timestamp`."""
        return MarketBreadthCalculator.calculate_breadth(
            timestamp=timestamp,
            universe_id=universe_id,
            stock_price_histories=stock_histories,
        )

    def get_institutional_flow(
        self,
        event_date: date,
        simulation_time: datetime,
    ) -> Optional[InstitutionalFlowRecord]:
        """Gets point-in-time eligible institutional flows as known at `simulation_time` (INV-26)."""
        return self.flow_processor.get_eligible_flow(
            event_date=event_date,
            simulation_time=simulation_time,
        )

    def get_sector_rankings(
        self,
        target_date: date,
        sector_prices: Dict[str, List[float]],
        benchmark_prices: List[float],
    ) -> List[SectorRank]:
        """Calculates sector relative strength leaderboard at `target_date` (INV-21)."""
        return self.sector_engine.calculate_sector_rankings(
            target_date=target_date,
            sector_price_series=sector_prices,
            benchmark_prices=benchmark_prices,
        )

    def generate_ai_analysis_summary(
        self,
        manifest: ExperimentManifest,
        breadth_record: BreadthRecord,
        flow_record: Optional[InstitutionalFlowRecord],
    ) -> str:
        """Generates descriptive research summary without mutating experiment parameters (AT-135)."""

        # Verify manifest fingerprint immutability
        orig_fp = manifest.compute_fingerprint()

        summary = f"### Market Intelligence Analysis for Experiment `{manifest.experiment_id}`\n"
        summary += f"- **Universe:** `{breadth_record.universe_id}` | **A/D Ratio:** {breadth_record.ad_ratio}\n"
        summary += f"- **% Stocks Above 50 SMA:** {breadth_record.pct_above_50_sma * 100:.1f}%\n"

        if flow_record:
            summary += f"- **FII Net Flow (Cash):** INR {flow_record.fii_cash_net:.2f} Cr\n"
            summary += f"- **DII Net Flow (Cash):** INR {flow_record.dii_cash_net:.2f} Cr\n"
        else:
            summary += "- **Institutional Flows:** No eligible flows available at simulation timestamp.\n"

        # Assert manifest was not mutated
        assert manifest.compute_fingerprint() == orig_fp, "AT-135 Violation: Manifest parameter mutated during summary generation."

        return summary
