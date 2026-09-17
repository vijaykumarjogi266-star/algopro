"""
Stage 7 Acceptance Suite — Part 1
Tests AT-01 to AT-06 (Manifest & Boundary Validation),
AT-13 to AT-17 (Temporal Partitioning & Overlap Prevention),
and AT-79 (Structural AST & Behavioral Execution Lockout).
"""

import ast
import os
from pathlib import Path
import pytest

from services.evaluation_engine.manifest import (
    ExperimentManifest,
    FrictionConfig,
    EvaluationEnvironment,
    TemporalPartition,
    PartitionType,
)
from services.evaluation_engine.partitioning import (
    create_disjoint_partitions,
    validate_partition_chronology,
)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
EVALUATION_ENGINE_DIR = BASE_DIR / "services" / "evaluation-engine"


# ==============================================================================
# AT-79: STRUCTURAL AST & BEHAVIORAL EXECUTION LOCKOUT TEST
# ==============================================================================

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
]


def test_at_79_structural_ast_isolation():
    """
    AT-79 Structural AST Test:
    Statically parses all Python modules in services/evaluation-engine
    and asserts zero prohibited broker or execution imports exist.
    """
    assert EVALUATION_ENGINE_DIR.exists(), f"Directory missing: {EVALUATION_ENGINE_DIR}"

    py_files = list(EVALUATION_ENGINE_DIR.glob("*.py"))
    assert len(py_files) > 0, "No Python files found in evaluation-engine"

    for py_file in py_files:
        content = py_file.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(py_file))

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for forbidden in FORBIDDEN_IMPORT_PATTERNS:
                        assert not alias.name.startswith(forbidden), (
                            f"AT-79 Violation in {py_file.name}:{node.lineno}: "
                            f"Prohibited import '{alias.name}' detected."
                        )

            elif isinstance(node, ast.ImportFrom):
                module_name = node.module or ""
                for forbidden in FORBIDDEN_IMPORT_PATTERNS:
                    assert not module_name.startswith(forbidden), (
                        f"AT-79 Violation in {py_file.name}:{node.lineno}: "
                        f"Prohibited import from '{module_name}' detected."
                    )


def test_at_79_behavioral_live_execution_lockout():
    """
    AT-79 Behavioral Test:
    Asserts configuring an experiment manifest with LIVE environment fails closed.
    """
    with pytest.raises(PermissionError, match="Live execution environment is strictly forbidden"):
        ExperimentManifest(
            strategy_id="SMA_Cross",
            dataset_id="NIFTY_DAILY_v1",
            start_date="2023-01-01",
            end_date="2023-12-31",
            initial_capital=100000.0,
            environment=EvaluationEnvironment.LIVE,
        )


# ==============================================================================
# AREA 1: EXPERIMENT CONFIGURATION & BOUNDARY VALIDATION (AT-01 to AT-06)
# ==============================================================================

def test_at_01_valid_experiment_manifest_creation():
    """AT-01: Valid Experiment Manifest Creation."""
    manifest = ExperimentManifest(
        strategy_id="SMA_Cross",
        dataset_id="NIFTY_DAILY_v1",
        start_date="2023-01-01",
        end_date="2023-12-31",
        initial_capital=100000.0,
        timeframe="1d",
        parameters={"fast_period": 10, "slow_period": 30},
    )
    assert manifest.strategy_id == "SMA_Cross"
    assert manifest.dataset_id == "NIFTY_DAILY_v1"
    assert manifest.initial_capital == 100000.0
    assert manifest.experiment_id.startswith("exp_")
    fingerprint = manifest.compute_fingerprint()
    assert len(fingerprint) == 64  # SHA-256 hex string


def test_at_02_missing_strategy_identity_rejection():
    """AT-02: Missing Strategy Identity Rejection."""
    with pytest.raises(ValueError, match="Strategy identity is required"):
        ExperimentManifest(
            strategy_id="",
            dataset_id="NIFTY_DAILY_v1",
            start_date="2023-01-01",
            end_date="2023-12-31",
            initial_capital=100000.0,
        )


def test_at_03_missing_dataset_identity_rejection():
    """AT-03: Missing Dataset Identity Rejection."""
    with pytest.raises(ValueError, match="Dataset identity is required"):
        ExperimentManifest(
            strategy_id="SMA_Cross",
            dataset_id="   ",
            start_date="2023-01-01",
            end_date="2023-12-31",
            initial_capital=100000.0,
        )


def test_at_04_inverted_date_range_rejection():
    """AT-04: Inverted / Invalid Date Range Rejection."""
    with pytest.raises(ValueError, match="Invalid date range"):
        ExperimentManifest(
            strategy_id="SMA_Cross",
            dataset_id="NIFTY_DAILY_v1",
            start_date="2023-12-31",
            end_date="2023-01-01",
            initial_capital=100000.0,
        )


def test_at_05_unsupported_timeframe_rejection():
    """AT-05: Unsupported / Invalid Timeframe Rejection."""
    with pytest.raises(ValueError, match="Unsupported timeframe"):
        ExperimentManifest(
            strategy_id="SMA_Cross",
            dataset_id="NIFTY_DAILY_v1",
            start_date="2023-01-01",
            end_date="2023-12-31",
            initial_capital=100000.0,
            timeframe="45m_invalid",
        )


def test_at_06_non_positive_capital_rejection():
    """AT-06: Non-Positive Initial Capital Rejection."""
    with pytest.raises(ValueError, match="Initial capital must be strictly positive"):
        ExperimentManifest(
            strategy_id="SMA_Cross",
            dataset_id="NIFTY_DAILY_v1",
            start_date="2023-01-01",
            end_date="2023-12-31",
            initial_capital=0.0,
        )

    with pytest.raises(ValueError, match="Initial capital must be strictly positive"):
        ExperimentManifest(
            strategy_id="SMA_Cross",
            dataset_id="NIFTY_DAILY_v1",
            start_date="2023-01-01",
            end_date="2023-12-31",
            initial_capital=-5000.0,
        )


# ==============================================================================
# AREA 3: TEMPORAL PARTITIONING & OVERLAP PREVENTION (AT-13 to AT-17)
# ==============================================================================

def test_at_13_valid_disjoint_partitions_creation():
    """AT-13: Valid Disjoint Partition Creation."""
    partitions = create_disjoint_partitions(
        start_date="2021-01-01",
        end_date="2023-12-31",
        train_pct=0.6,
        val_pct=0.2,
        test_pct=0.2,
    )
    assert len(partitions) == 3
    assert partitions[0].partition_type == PartitionType.TRAIN
    assert partitions[1].partition_type == PartitionType.VALIDATION
    assert partitions[2].partition_type == PartitionType.TEST
    # Chronology check passes cleanly
    validate_partition_chronology(partitions)


def test_at_14_train_validation_overlap_rejection():
    """AT-14: Training / Validation Overlap Rejection."""
    p_train = TemporalPartition(
        name="train",
        partition_type=PartitionType.TRAIN,
        start_date="2021-01-01",
        end_date="2022-06-30",
    )
    p_val = TemporalPartition(
        name="val",
        partition_type=PartitionType.VALIDATION,
        start_date="2022-06-01",  # Overlaps with train!
        end_date="2022-12-31",
    )
    with pytest.raises(ValueError, match="Partition overlap detected"):
        validate_partition_chronology([p_train, p_val])


def test_at_15_validation_final_test_overlap_rejection():
    """AT-15: Validation / Final Test Overlap Rejection."""
    p_val = TemporalPartition(
        name="val",
        partition_type=PartitionType.VALIDATION,
        start_date="2022-07-01",
        end_date="2022-12-31",
    )
    p_test = TemporalPartition(
        name="test",
        partition_type=PartitionType.TEST,
        start_date="2022-12-15",  # Overlaps with val!
        end_date="2023-12-31",
    )
    with pytest.raises(ValueError, match="Partition overlap detected"):
        validate_partition_chronology([p_val, p_test])


def test_at_16_train_extends_into_final_test_rejection():
    """AT-16: Training Extends Into Final Test Rejection."""
    p_train = TemporalPartition(
        name="train",
        partition_type=PartitionType.TRAIN,
        start_date="2021-01-01",
        end_date="2023-06-30",  # Extends past test start!
    )
    p_test = TemporalPartition(
        name="test",
        partition_type=PartitionType.TEST,
        start_date="2023-01-01",
        end_date="2023-12-31",
    )
    with pytest.raises(ValueError, match="Chronologically inverted|Partition overlap"):
        validate_partition_chronology([p_train, p_test])


def test_at_17_chronologically_inverted_partitions_rejection():
    """AT-17: Chronologically Inverted Partitions Rejection."""
    p_test = TemporalPartition(
        name="test",
        partition_type=PartitionType.TEST,
        start_date="2021-01-01",
        end_date="2021-12-31",
    )
    p_train = TemporalPartition(
        name="train",
        partition_type=PartitionType.TRAIN,
        start_date="2022-01-01",
        end_date="2023-12-31",
    )
    with pytest.raises(ValueError, match="Chronologically inverted"):
        validate_partition_chronology([p_test, p_train])
