"""Algo Lab Experiment API Schemas.

Pydantic models for experiment validation, creation, execution submission,
status querying, and research result retrieval.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from services.backtest_engine.contracts import (
    CostModelConfig,
    SlippageModelConfig,
    BacktestMetrics,
    ExperimentStatus,
)


class ExperimentCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, description="Human-readable experiment name")
    description: Optional[str] = Field(default="", description="Detailed research rationale")
    strategy_id: str = Field(..., min_length=1, description="Target strategy identifier")
    strategy_version: str = Field(..., min_length=1, description="Semantic version of strategy")
    dataset_id: str = Field(..., min_length=1, description="Dataset identifier")
    dataset_version: str = Field(..., min_length=1, description="Dataset release version")
    dataset_checksum: str = Field(..., min_length=64, max_length=64, description="SHA-256 dataset digest")
    universe: List[str] = Field(..., min_length=1, description="Traded asset symbols")
    timeframe: str = Field(default="1d", min_length=1, description="Bar timeframe")
    start_date: datetime = Field(..., description="Simulation start UTC timestamp")
    end_date: datetime = Field(..., description="Simulation end UTC timestamp")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Hyperparameters dictionary")
    risk_policy_version: str = Field(default="1.0.0", min_length=1)
    cost_model: CostModelConfig = Field(default_factory=CostModelConfig)
    slippage_model: SlippageModelConfig = Field(default_factory=SlippageModelConfig)
    initial_capital: float = Field(default=500_000.0, gt=0.0)
    seed: int = Field(default=42)
    code_revision: str = Field(default="main", min_length=1)


class ExperimentValidateRequest(ExperimentCreateRequest):
    """Schema for dry-run experiment validation."""
    pass


class ExperimentValidationResponse(BaseModel):
    is_valid: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    fingerprint: Optional[str] = None


class ExperimentResponse(BaseModel):
    experiment_id: str
    name: str
    description: Optional[str] = ""
    strategy_id: str
    strategy_version: str
    dataset_id: str
    dataset_version: str
    dataset_checksum: str
    universe: List[str]
    timeframe: str
    start_date: datetime
    end_date: datetime
    parameters: Dict[str, Any]
    risk_policy_version: str
    cost_model: CostModelConfig
    slippage_model: SlippageModelConfig
    initial_capital: float
    seed: int
    code_revision: str
    fingerprint: str
    created_at: datetime
    status: ExperimentStatus


class ExperimentListResponse(BaseModel):
    experiments: List[ExperimentResponse]
    total: int
    limit: int
    offset: int


class RunSubmitResponse(BaseModel):
    status: str
    experiment_id: str
    run_id: str
    reproducibility_hash: str
    is_idempotent_duplicate: bool


class RunStatusResponse(BaseModel):
    run_id: str
    experiment_id: str
    status: str
    reproducibility_hash: str
    metrics: Optional[Dict[str, Any]] = None
    trades_count: int = 0
    rejected_trades_count: int = 0
    created_at: str


class RunResultResponse(BaseModel):
    experiment_id: str
    run_id: str
    status: str
    metrics: Optional[Dict[str, Any]] = None
    reproducibility: Optional[Dict[str, Any]] = None
    trades_count: int = 0
    rejected_trades_count: int = 0


class AuditEventResponse(BaseModel):
    timestamp: str
    event_type: str
    payload: Dict[str, Any]


class ExperimentCompareRequest(BaseModel):
    baseline_experiment_id: str = Field(..., min_length=1, description="Baseline experiment ID")
    target_experiment_id: str = Field(..., min_length=1, description="Target experiment ID to compare against baseline")
