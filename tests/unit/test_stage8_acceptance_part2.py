"""
Algo Lab — Stage 8 Acceptance Test Suite (Part 2: AT-121 to AT-135)
Covers Point-in-Time Data Revision Isolation (INV-26), Point-in-Time Sector Constituent
Versioning (INV-27), Stale Data Warnings, AST Execution Isolation, and AI Authority Controls.
"""

from datetime import datetime, date, timezone, timedelta
import pytest
import warnings

from services.evaluation_engine.manifest import ExperimentManifest
from services.market_intelligence.contracts import (
    PointInTimeRecord,
    SectorMembershipRecord,
    MissingTimestampError,
    SourceConflictError,
    MissingMembershipError,
    MarketIntelligenceError,
    StaleDataWarning,
)
from services.market_intelligence.institutional_flows import InstitutionalFlowProcessor
from services.market_intelligence.sector_rotation import SectorRotationEngine
from services.market_intelligence.service import MarketIntelligenceService
from services.market_intelligence.breadth import MarketBreadthCalculator
from services.evaluation_engine.walk_forward import LookAheadBiasError


# AT-121 & AT-123: POINT-IN-TIME HISTORICAL REVISION ISOLATION (INV-26)

def test_at_121_and_123_point_in_time_revision_isolation():
    """AT-121 & AT-123: Verifies historical data revisions published at T_pub,rev > t_sim
    are invisible to simulation clock t_sim (INV-26).
    """
    event_dt = date(2024, 6, 10)
    pub_initial = datetime(2024, 6, 10, 18, 0, tzinfo=timezone.utc)
    pub_revised = datetime(2024, 6, 13, 18, 0, tzinfo=timezone.utc)

    # Initial record published June 10 (+1000 Cr)
    rec_initial = PointInTimeRecord(
        event_date=event_dt,
        publication_timestamp=pub_initial,
        retrieval_timestamp=pub_initial,
        dataset_version_id="FII_V1",
        revision_sequence_id=0,
        payload={"fii_cash_net": 1000.0, "dii_cash_net": -200.0},
    )

    # Revised record published June 13 (+1500 Cr)
    rec_revised = PointInTimeRecord(
        event_date=event_dt,
        publication_timestamp=pub_revised,
        retrieval_timestamp=pub_revised,
        dataset_version_id="FII_V2_REVISED",
        revision_sequence_id=1,
        payload={"fii_cash_net": 1500.0, "dii_cash_net": -200.0},
    )

    processor = InstitutionalFlowProcessor([rec_initial, rec_revised])

    # Simulation clock at June 11 09:15:00 MUST consume initial unrevised record (+1000 Cr)
    sim_time_june_11 = datetime(2024, 6, 11, 9, 15, tzinfo=timezone.utc)
    flow_june_11 = processor.get_eligible_flow(event_dt, sim_time_june_11)
    assert flow_june_11 is not None
    assert flow_june_11.fii_cash_net == 1000.0  # Unrevised value!

    # Simulation clock at June 14 09:15:00 MUST consume revised record (+1500 Cr)
    sim_time_june_14 = datetime(2024, 6, 14, 9, 15, tzinfo=timezone.utc)
    flow_june_14 = processor.get_eligible_flow(event_dt, sim_time_june_14)
    assert flow_june_14 is not None
    assert flow_june_14.fii_cash_net == 1500.0  # Revised value!


# AT-122, AT-127 to AT-130: POINT-IN-TIME SECTOR CONSTITUENT INTEGRITY (INV-27)

def test_at_122_and_127_to_130_point_in_time_sector_constituents():
    """AT-122, AT-127..AT-130: Verifies historical sector relative strength at date t
    resolves constituent stocks active on date t strictly without survivorship bias (INV-27).
    """
    engine = SectorRotationEngine()

    # Record 1: Nifty Bank constituents active on 2021-01-01 (STOCK_A, STOCK_B)
    mem_2021 = SectorMembershipRecord(
        sector_id="NIFTY_BANK",
        effective_date=date(2021, 1, 1),
        added_symbols=["STOCK_A", "STOCK_B"],
        removed_symbols=[],
        active_constituents=["STOCK_A", "STOCK_B"],
    )

    # Record 2: Rebalance on 2022-03-31: STOCK_C added, STOCK_B removed
    mem_2022 = SectorMembershipRecord(
        sector_id="NIFTY_BANK",
        effective_date=date(2022, 3, 31),
        added_symbols=["STOCK_C"],
        removed_symbols=["STOCK_B"],
        active_constituents=["STOCK_A", "STOCK_C"],
    )

    engine.add_membership_record(mem_2021)
    engine.add_membership_record(mem_2022)

    # Query constituents for date 2021-12-15 MUST return [STOCK_A, STOCK_B]
    const_2021 = engine.get_point_in_time_constituents("NIFTY_BANK", date(2021, 12, 15))
    assert const_2021 == ["STOCK_A", "STOCK_B"]
    assert "STOCK_C" not in const_2021  # Future addition excluded!

    # Query constituents for date 2022-04-15 MUST return [STOCK_A, STOCK_C]
    const_2022 = engine.get_point_in_time_constituents("NIFTY_BANK", date(2022, 4, 15))
    assert const_2022 == ["STOCK_A", "STOCK_C"]
    assert "STOCK_B" not in const_2022  # Removed constituent excluded!


def test_at_124_missing_t_pub_fail_closed():
    """AT-124: Loading PointInTimeRecord with missing T_pub raises MissingTimestampError."""
    rec_invalid = PointInTimeRecord(
        event_date=date(2024, 6, 10),
        publication_timestamp=None,
        retrieval_timestamp=datetime.now(timezone.utc),
        dataset_version_id="FII_V1",
        revision_sequence_id=0,
        payload={"fii_cash_net": 1000.0},
    )
    processor = InstitutionalFlowProcessor()
    with pytest.raises(MissingTimestampError, match="missing publication timestamp"):
        processor.add_record(rec_invalid)


def test_at_125_conflicting_dataset_version_handling():
    """AT-125: Loading conflicting records for identical (T_event, T_pub) raises SourceConflictError."""
    pub_time = datetime(2024, 6, 10, 18, 0, tzinfo=timezone.utc)
    rec1 = PointInTimeRecord(
        event_date=date(2024, 6, 10),
        publication_timestamp=pub_time,
        retrieval_timestamp=pub_time,
        dataset_version_id="FEED_A",
        revision_sequence_id=0,
        payload={"fii_cash_net": 1000.0},
    )
    rec2 = PointInTimeRecord(
        event_date=date(2024, 6, 10),
        publication_timestamp=pub_time,
        retrieval_timestamp=pub_time,
        dataset_version_id="FEED_B",
        revision_sequence_id=0,
        payload={"fii_cash_net": -500.0},  # Conflicting payload!
    )
    processor = InstitutionalFlowProcessor([rec1])
    with pytest.raises(SourceConflictError, match="Conflicting datasets detected"):
        processor.add_record(rec2)


def test_at_132_stale_source_warning_flag():
    """AT-132: Institutional flows un-updated for >3 days emits StaleDataWarning."""
    pub_time = datetime(2024, 6, 1, 18, 0, tzinfo=timezone.utc)
    rec = PointInTimeRecord(
        event_date=date(2024, 6, 1),
        publication_timestamp=pub_time,
        retrieval_timestamp=pub_time,
        dataset_version_id="FII_V1",
        revision_sequence_id=0,
        payload={"fii_cash_net": 500.0},
    )
    processor = InstitutionalFlowProcessor([rec])
    sim_time_stale = datetime(2024, 6, 10, 12, 0, tzinfo=timezone.utc)  # 9 days later!

    with pytest.warns(StaleDataWarning, match="STALE_MACRO_DATA"):
        processor.check_stale_data_warning(sim_time_stale)


def test_at_133_malformed_payload_fail_closed_gate():
    """AT-133: Flow record with negative buy volume raises MarketIntelligenceError."""
    pub_time = datetime(2024, 6, 10, 18, 0, tzinfo=timezone.utc)
    rec_malformed = PointInTimeRecord(
        event_date=date(2024, 6, 10),
        publication_timestamp=pub_time,
        retrieval_timestamp=pub_time,
        dataset_version_id="FII_V1",
        revision_sequence_id=0,
        payload={"fii_cash_buy": -5000.0},  # Malformed negative volume!
    )
    processor = InstitutionalFlowProcessor()
    with pytest.raises(MarketIntelligenceError, match="invalid negative transaction volume"):
        processor.add_record(rec_malformed)


def test_at_135_ai_authority_boundary_enforcement():
    """AT-135: Verifies AI summary generation cannot mutate ExperimentManifest or alter fingerprint."""
    manifest = ExperimentManifest(
        strategy_id="MOMENTUM_ALPHA",
        dataset_id="NIFTY_DAILY_V1",
        start_date="2024-01-01",
        end_date="2024-06-30",
        initial_capital=100000.0,
    )
    orig_fp = manifest.compute_fingerprint()

    service = MarketIntelligenceService()
    breadth = MarketBreadthCalculator.calculate_breadth(
        timestamp=datetime.now(timezone.utc),
        universe_id="NIFTY_50",
        stock_price_histories={"STOCK_A": [100.0, 105.0]},
    )

    summary = service.generate_ai_analysis_summary(manifest, breadth, flow_record=None)
    assert len(summary) > 0
    # Assert manifest fingerprint is untouched
    assert manifest.compute_fingerprint() == orig_fp
