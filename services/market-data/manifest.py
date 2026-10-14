"""Typed Dataset Manifests, Lineage Tracking, and Experiment Provenance.

Enforces:
- Point-in-time dataset integrity and immutability (SHA-256 checksums).
- Explicit lineage stages: RAW -> VALIDATED -> ADJUSTED -> FEATURE -> EXPERIMENT_INPUT.
- Strict rejection of synthetic fallback in forward paper and production paths.
- Audit-grade experiment manifests with strategy source hashes and dependency locks.
"""

from datetime import datetime, timezone
from enum import Enum
import hashlib
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class DataLineageStage(str, Enum):
    """Lineage progression stages for quantitative market data."""
    RAW = "RAW"
    VALIDATED = "VALIDATED"
    ADJUSTED = "ADJUSTED"
    FEATURE = "FEATURE"
    EXPERIMENT_INPUT = "EXPERIMENT_INPUT"


class LicenseClassification(str, Enum):
    """Data licensing compliance classification."""
    PROPRIETARY = "PROPRIETARY"
    COMMERCIAL = "COMMERCIAL"
    EXCHANGE_LICENSED = "EXCHANGE_LICENSED"
    OPEN_ACCESS = "OPEN_ACCESS"
    RESEARCH_ONLY = "RESEARCH_ONLY"


class DataQualityMetrics(BaseModel):
    """Summary metrics of dataset validation and integrity checks."""
    total_bars: int = Field(default=0, ge=0, description="Total number of canonical bars")
    null_count: int = Field(default=0, ge=0, description="Null or NaN values detected")
    duplicate_count: int = Field(default=0, ge=0, description="Duplicate timestamps rejected")
    min_timestamp: Optional[datetime] = None
    max_timestamp: Optional[datetime] = None
    ohlc_violations: int = Field(default=0, ge=0, description="Number of invalid OHLC bounds")
    is_fully_validated: bool = True


class DatasetManifest(BaseModel):
    """Authoritative typed manifest defining a versioned dataset snapshot."""

    dataset_id: str = Field(..., description="Unique dataset identifier / slug")
    version: str = Field(default="1.0.0", description="Semantic version of dataset")
    lineage_stage: DataLineageStage = Field(default=DataLineageStage.VALIDATED)
    provider_source: str = Field(..., description="Data provider or vendor (e.g. NSE, Zerodha, TruData)")
    license_classification: LicenseClassification = Field(default=LicenseClassification.RESEARCH_ONLY)
    ingestion_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    exchange_timezone: str = Field(default="Asia/Kolkata", description="Exchange local timezone")
    data_availability_timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Point-in-time point when this data became observable"
    )
    schema_version: str = Field(default="v1.0.0", description="Schema definition version")
    symbol_master_version: str = Field(default="symbols-nse-2024.1", description="Symbol master reference version")
    corporate_action_version: str = Field(default="ca-nse-2024.1", description="Corporate actions dataset version")
    checksum: str = Field(..., description="Cryptographic SHA-256 hash of dataset payload")
    quality_metrics: DataQualityMetrics = Field(default_factory=DataQualityMetrics)
    immutable_storage_reference: str = Field(..., description="Storage path, URI, or S3/Blob key")
    is_synthetic: bool = Field(default=False, description="Flag indicating synthetic or mocked data")
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("checksum")
    @classmethod
    def validate_sha256(cls, v: str) -> str:
        if len(v) != 64 or not all(c in "0123456789abcdefABCDEF" for c in v):
            raise ValueError("Checksum must be a valid 64-character hexadecimal SHA-256 digest")
        return v.lower()

    def assert_no_synthetic_fallback(self) -> None:
        """Enforces Safety Invariant #6: Prohibits synthetic data in production or forward validation."""
        if self.is_synthetic:
            raise ValueError(
                f"Synthetic data fallback is strictly prohibited for dataset '{self.dataset_id}' "
                f"in forward validation and production paths."
            )

    def transition_to(
        self,
        target_stage: DataLineageStage,
        new_checksum: str,
        new_storage_ref: str,
        quality_metrics: Optional[DataQualityMetrics] = None,
    ) -> "DatasetManifest":
        """Transitions dataset across valid lineage progression stages."""
        valid_transitions = {
            DataLineageStage.RAW: {DataLineageStage.VALIDATED},
            DataLineageStage.VALIDATED: {DataLineageStage.ADJUSTED, DataLineageStage.FEATURE, DataLineageStage.EXPERIMENT_INPUT},
            DataLineageStage.ADJUSTED: {DataLineageStage.FEATURE, DataLineageStage.EXPERIMENT_INPUT},
            DataLineageStage.FEATURE: {DataLineageStage.EXPERIMENT_INPUT},
            DataLineageStage.EXPERIMENT_INPUT: set(),  # Terminal stage
        }

        if target_stage not in valid_transitions[self.lineage_stage]:
            raise ValueError(
                f"Invalid lineage transition from {self.lineage_stage.value} to {target_stage.value}."
            )

        updated_dict = self.model_dump()
        updated_dict["lineage_stage"] = target_stage
        updated_dict["checksum"] = new_checksum
        updated_dict["immutable_storage_reference"] = new_storage_ref
        if quality_metrics:
            updated_dict["quality_metrics"] = quality_metrics
        updated_dict["ingestion_timestamp"] = datetime.now(timezone.utc)

        return DatasetManifest(**updated_dict)


class ExperimentManifest(BaseModel):
    """Immutable audit record linking strategy code, parameters, datasets, and results."""

    experiment_id: str = Field(..., description="Unique experiment run ID")
    strategy_name: str = Field(..., description="Name of quantitative strategy")
    strategy_source_hash: str = Field(..., description="SHA-256 hash of strategy implementation source code")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Locked strategy parameters")
    dataset_manifest_ids: List[str] = Field(default_factory=list, description="IDs of registered dataset manifests used")
    execution_model_version: str = Field(default="sim-v1.0.0", description="Execution simulator engine version")
    environment_build_metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Runtime environment metadata: Python, OS, git commit"
    )
    dependency_lock_hash: str = Field(default="", description="SHA-256 digest of locked requirements")
    start_time: datetime = Field(..., description="Simulation historical start timestamp")
    end_time: datetime = Field(..., description="Simulation historical end timestamp")
    metrics: Dict[str, Any] = Field(default_factory=dict, description="Performance & risk statistics")
    output_artifacts: Dict[str, str] = Field(
        default_factory=dict,
        description="Map of artifact filenames to their SHA-256 checksums"
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @staticmethod
    def hash_strategy_source(source_code: str) -> str:
        """Computes deterministic SHA-256 digest of strategy source code."""
        return hashlib.sha256(source_code.strip().encode("utf-8")).hexdigest()
