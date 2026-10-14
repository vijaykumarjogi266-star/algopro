"""Unit Tests for Workstream E: Data Governance, Manifests, Lineage, and Versioned Calendar.

Verifies:
1. Typed DatasetManifest schemas and SHA-256 validation.
2. Invariant #6: Prohibits synthetic fallback in forward validation / production.
3. Strict lineage stage transitions: RAW -> VALIDATED -> ADJUSTED -> FEATURE -> EXPERIMENT_INPUT.
4. Versioned CalendarProvider for multi-year NSE trading sessions and Muhurat special sessions.
5. ExperimentManifest source code hashing, parameter locking, and dataset linking.
"""

from datetime import date, datetime, time, timezone
import pytest

from services.market_data.manifest import (
    DataLineageStage,
    DataQualityMetrics,
    DatasetManifest,
    ExperimentManifest,
    LicenseClassification,
)
from services.market_data.calendar_provider import (
    CalendarMetadata,
    SpecialSessionRecord,
    VersionedCalendarProvider,
    IST_TZ,
)
from services.market_data.calendar import IndianMarketCalendar


def test_dataset_manifest_checksum_validation():
    """Manifest requires valid 64-char hexadecimal SHA-256 checksum."""
    valid_sha = "a" * 64
    manifest = DatasetManifest(
        dataset_id="nifty50_daily",
        version="1.0.0",
        provider_source="NSE",
        checksum=valid_sha,
        immutable_storage_reference="data/processed/nifty50_daily_v1.parquet",
    )
    assert manifest.checksum == valid_sha

    with pytest.raises(ValueError, match="Checksum must be a valid 64-character"):
        DatasetManifest(
            dataset_id="nifty50_daily",
            version="1.0.0",
            provider_source="NSE",
            checksum="invalid_short_hash",
            immutable_storage_reference="data/processed/nifty50_daily_v1.parquet",
        )


def test_safety_invariant_no_synthetic_fallback():
    """Safety Invariant #6: Prohibits synthetic data in production or forward validation."""
    valid_sha = "b" * 64
    manifest = DatasetManifest(
        dataset_id="nifty50_synthetic",
        version="1.0.0",
        provider_source="MOCK",
        checksum=valid_sha,
        immutable_storage_reference="data/processed/mock.parquet",
        is_synthetic=True,
    )
    with pytest.raises(ValueError, match="Synthetic data fallback is strictly prohibited"):
        manifest.assert_no_synthetic_fallback()


def test_data_lineage_transitions():
    """Validates strictly permitted data lineage progression stages."""
    sha_raw = "1" * 64
    sha_val = "2" * 64
    sha_adj = "3" * 64
    sha_feat = "4" * 64
    sha_exp = "5" * 64

    # RAW -> VALIDATED is valid
    raw_manifest = DatasetManifest(
        dataset_id="nifty50_feed",
        version="1.0.0",
        lineage_stage=DataLineageStage.RAW,
        provider_source="NSE_FEED",
        checksum=sha_raw,
        immutable_storage_reference="data/raw/feed.parquet",
    )

    # Invalid: RAW cannot skip directly to FEATURE
    with pytest.raises(ValueError, match="Invalid lineage transition"):
        raw_manifest.transition_to(DataLineageStage.FEATURE, sha_feat, "data/features/f.parquet")

    # Step 1: RAW -> VALIDATED
    val_manifest = raw_manifest.transition_to(
        DataLineageStage.VALIDATED,
        sha_val,
        "data/validated/val.parquet",
        DataQualityMetrics(total_bars=1000, null_count=0, duplicate_count=0),
    )
    assert val_manifest.lineage_stage == DataLineageStage.VALIDATED

    # Step 2: VALIDATED -> ADJUSTED
    adj_manifest = val_manifest.transition_to(
        DataLineageStage.ADJUSTED,
        sha_adj,
        "data/adjusted/adj.parquet",
    )
    assert adj_manifest.lineage_stage == DataLineageStage.ADJUSTED

    # Step 3: ADJUSTED -> FEATURE
    feat_manifest = adj_manifest.transition_to(
        DataLineageStage.FEATURE,
        sha_feat,
        "data/features/feat.parquet",
    )
    assert feat_manifest.lineage_stage == DataLineageStage.FEATURE

    # Step 4: FEATURE -> EXPERIMENT_INPUT
    exp_manifest = feat_manifest.transition_to(
        DataLineageStage.EXPERIMENT_INPUT,
        sha_exp,
        "data/experiments/exp_input.parquet",
    )
    assert exp_manifest.lineage_stage == DataLineageStage.EXPERIMENT_INPUT

    # Terminal: EXPERIMENT_INPUT cannot transition further
    with pytest.raises(ValueError, match="Invalid lineage transition"):
        exp_manifest.transition_to(DataLineageStage.VALIDATED, sha_val, "data/foo.parquet")


def test_versioned_calendar_provider_trading_days():
    """VersionedCalendarProvider accurately classifies multi-year trading days and holidays."""
    cal = VersionedCalendarProvider()
    assert "NSE-EQUITY-CALENDAR" in cal.get_version()

    # Republic Day (Jan 26) is holiday across years
    assert not cal.is_trading_day(date(2024, 1, 26))
    assert not cal.is_trading_day(date(2025, 1, 26))
    assert not cal.is_trading_day(date(2026, 1, 26))

    # Independence Day (Aug 15)
    assert not cal.is_trading_day(date(2024, 8, 15))
    assert not cal.is_trading_day(date(2025, 8, 15))

    # Standard trading days (Wednesday)
    assert cal.is_trading_day(date(2024, 1, 10))  # Wednesday
    assert cal.is_trading_day(date(2024, 1, 17))  # Wednesday

    # Weekend check
    assert not cal.is_trading_day(date(2024, 1, 13))  # Saturday
    assert not cal.is_trading_day(date(2024, 1, 14))  # Sunday


def test_versioned_calendar_special_muhurat_session():
    """VersionedCalendarProvider supports weekend special / Muhurat trading sessions."""
    muhurat_date = date(2024, 11, 1)  # Diwali Laxmi Pujan (special evening session)
    special = SpecialSessionRecord(
        session_date=muhurat_date,
        start_time=time(18, 15),
        end_time=time(19, 15),
        description="Diwali Muhurat Trading",
    )
    cal = VersionedCalendarProvider(special_sessions={muhurat_date: special})

    # Within special session hours
    in_session = datetime(2024, 11, 1, 18, 30, tzinfo=IST_TZ)
    is_valid, msg = cal.is_regular_trading_session(in_session)
    assert is_valid is True
    assert "special session" in msg.lower()

    # Outside special session hours
    outside_session = datetime(2024, 11, 1, 14, 0, tzinfo=IST_TZ)
    is_valid, msg = cal.is_regular_trading_session(outside_session)
    assert is_valid is False


def test_calendar_session_boundaries_regular_hours():
    """IndianMarketCalendar validates standard 09:15 - 15:30 IST session."""
    calendar = IndianMarketCalendar()

    # Valid regular trading time: 10:30 IST on a normal Wednesday
    valid_dt = datetime(2024, 1, 10, 10, 30, tzinfo=IST_TZ)
    is_valid, reason = calendar.is_regular_trading_session(valid_dt)
    assert is_valid is True
    assert "regular" in reason.lower()

    # Pre-market: 09:10 IST -> rejected
    pre_dt = datetime(2024, 1, 10, 9, 10, tzinfo=IST_TZ)
    is_valid, reason = calendar.is_regular_trading_session(pre_dt)
    assert is_valid is False
    assert "before session open" in reason

    # Post-market: 15:35 IST -> rejected
    post_dt = datetime(2024, 1, 10, 15, 35, tzinfo=IST_TZ)
    is_valid, reason = calendar.is_regular_trading_session(post_dt)
    assert is_valid is False
    assert "after session close" in reason


def test_experiment_manifest_provenance():
    """ExperimentManifest captures immutable strategy code hash and execution metadata."""
    sample_code = """
    class SimpleSMA:
        def on_bar(self, bar):
            return 1.0
    """
    code_hash = ExperimentManifest.hash_strategy_source(sample_code)
    assert len(code_hash) == 64

    exp = ExperimentManifest(
        experiment_id="exp_20261014_001",
        strategy_name="SimpleSMA",
        strategy_source_hash=code_hash,
        parameters={"window_fast": 20, "window_slow": 50},
        dataset_manifest_ids=["nifty50_daily_v1"],
        start_time=datetime(2023, 1, 1, tzinfo=timezone.utc),
        end_time=datetime(2023, 12, 31, tzinfo=timezone.utc),
        metrics={"sharpe": 1.45, "max_drawdown": 0.08},
        output_artifacts={"tearsheet.json": "f" * 64},
    )

    assert exp.strategy_name == "SimpleSMA"
    assert exp.parameters["window_fast"] == 20
    assert exp.output_artifacts["tearsheet.json"] == "f" * 64
