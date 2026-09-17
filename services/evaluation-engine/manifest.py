"""
Algo Lab — Stage 7 Research & Strategy Evaluation Manifest Model
Implements immutable experiment configuration, parameters, friction settings,
and strict validation controls.
"""

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, date, timezone
from enum import Enum
from typing import Dict, Any, List, Optional


class EvaluationEnvironment(str, Enum):
    OFFLINE_SIMULATION = "OFFLINE_SIMULATION"
    PAPER = "PAPER"
    LIVE = "LIVE"


class PartitionType(str, Enum):
    TRAIN = "TRAIN"
    VALIDATION = "VALIDATION"
    TEST = "TEST"
    WALK_FORWARD = "WALK_FORWARD"


VALID_TIMEFRAMES = {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d", "1D", "1W", "1M"}


@dataclass
class FrictionConfig:
    brokerage_per_order: float = 20.0
    brokerage_bps: float = 10.0
    fixed_tick_slippage_pts: float = 0.05
    variable_slippage_pct: float = 0.0005
    slippage_bps: float = 5.0
    stt_rate: float = 0.001
    gst_rate: float = 0.18
    stamp_duty_rate: float = 0.00015
    exchange_turnover_fee_rate: float = 0.0000345
    exchange_turnover_rate: float = 0.0000345

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TemporalPartition:
    name: str
    partition_type: PartitionType
    start_date: str
    end_date: str

    def __post_init__(self):
        s_dt = _parse_date(self.start_date)
        e_dt = _parse_date(self.end_date)
        if s_dt >= e_dt:
            raise ValueError(
                f"Partition '{self.name}' has invalid date range: {self.start_date} >= {self.end_date}"
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "partition_type": self.partition_type.value if isinstance(self.partition_type, Enum) else str(self.partition_type),
            "start_date": self.start_date,
            "end_date": self.end_date,
        }


def _parse_date(d_val: Any) -> datetime:
    if isinstance(d_val, datetime):
        return d_val
    if isinstance(d_val, date):
        return datetime.combine(d_val, datetime.min.time())
    if isinstance(d_val, str):
        # Support ISO formats YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS
        clean_str = d_val.replace("Z", "").split("+")[0]
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(clean_str, fmt)
            except ValueError:
                pass
    raise ValueError(f"Cannot parse invalid date value: {d_val}")


@dataclass
class ExperimentManifest:
    strategy_id: str
    dataset_id: str
    start_date: str
    end_date: str
    initial_capital: float
    timeframe: str = "1d"
    experiment_id: Optional[str] = None
    environment: EvaluationEnvironment = EvaluationEnvironment.OFFLINE_SIMULATION
    parameters: Dict[str, Any] = field(default_factory=dict)
    friction_config: FrictionConfig = field(default_factory=FrictionConfig)
    partitions: List[TemporalPartition] = field(default_factory=list)
    git_commit: str = "2c09e57"
    dataset_hash: str = ""
    created_at: Optional[str] = None

    def __post_init__(self):
        # Fail Closed on LIVE Environment Request
        if self.environment == EvaluationEnvironment.LIVE or str(self.environment).upper() == "LIVE":
            raise PermissionError(
                "Live execution environment is strictly forbidden in Stage 7 evaluation modules."
            )

        # Validation AT-02: Missing Strategy Identity
        if not self.strategy_id or not str(self.strategy_id).strip():
            raise ValueError("Strategy identity is required.")

        # Validation AT-03: Missing Dataset Identity
        if not self.dataset_id or not str(self.dataset_id).strip():
            raise ValueError("Dataset identity is required.")

        # Validation AT-04: Inverted or Invalid Date Range
        s_dt = _parse_date(self.start_date)
        e_dt = _parse_date(self.end_date)
        if s_dt >= e_dt:
            raise ValueError(
                f"Invalid date range: start_date ({self.start_date}) must be strictly before end_date ({self.end_date})."
            )

        # Validation AT-05: Unsupported Timeframe String
        if self.timeframe not in VALID_TIMEFRAMES:
            raise ValueError(
                f"Unsupported timeframe '{self.timeframe}'. Valid options: {sorted(list(VALID_TIMEFRAMES))}"
            )

        # Validation AT-06: Non-Positive Initial Capital
        try:
            cap_val = float(self.initial_capital)
            if cap_val <= 0.0:
                raise ValueError()
            self.initial_capital = cap_val
        except (ValueError, TypeError):
            raise ValueError(f"Initial capital must be strictly positive. Got: {self.initial_capital}")

        if not self.experiment_id:
            self.experiment_id = f"exp_{uuid.uuid4().hex[:12]}"

        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def compute_fingerprint(self) -> str:
        """Computes deterministic SHA-256 fingerprint of the configuration."""
        payload = {
            "strategy_id": self.strategy_id,
            "dataset_id": self.dataset_id,
            "timeframe": self.timeframe,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "initial_capital": self.initial_capital,
            "parameters": self.parameters,
            "friction_config": self.friction_config.to_dict(),
            "partitions": [p.to_dict() for p in self.partitions],
            "dataset_hash": self.dataset_hash,
            "git_commit": self.git_commit,
        }
        serialized = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "strategy_id": self.strategy_id,
            "dataset_id": self.dataset_id,
            "timeframe": self.timeframe,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "initial_capital": self.initial_capital,
            "environment": self.environment.value if isinstance(self.environment, Enum) else str(self.environment),
            "parameters": self.parameters,
            "friction_config": self.friction_config.to_dict(),
            "partitions": [p.to_dict() for p in self.partitions],
            "git_commit": self.git_commit,
            "dataset_hash": self.dataset_hash,
            "created_at": self.created_at,
            "fingerprint": self.compute_fingerprint(),
        }
