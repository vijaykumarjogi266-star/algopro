"""Algo Lab Backtest Engine Contracts & Metrics.

Adheres to Non-Negotiable Principles:
- Principle 4: No look-ahead bias.
- Principle 7: Every backtest must be reproducible.
- Principle 19: Performance must be evaluated after realistic costs and slippage.
- Principle 20: Optimize for robustness, not maximum historical return.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_LOSS = "STOP_LOSS"


class CostModelConfig(BaseModel):
    """Realistic Indian Market Transaction Cost Model (NSE/BSE)."""

    brokerage_per_crore_or_order: float = Field(default=20.0, description="INR flat or percentage")
    stt_rate: float = Field(default=0.001, description="Securities Transaction Tax (0.1% for delivery, 0.025% intraday)")
    exchange_turnover_fee_rate: float = Field(default=0.0000345, description="NSE turnover charges")
    sebi_turnover_fee_rate: float = Field(default=0.000001, description="SEBI regulatory fees")
    gst_rate: float = Field(default=0.18, description="18% GST on (Brokerage + Exchange fees)")
    stamp_duty_rate: float = Field(default=0.00015, description="0.015% stamp duty on buy side")


class SlippageModelConfig(BaseModel):
    """Realistic execution slippage model."""

    fixed_tick_slippage_pts: float = 0.05
    variable_slippage_pct: float = 0.0005  # 5 bps


class TradeRecord(BaseModel):
    """Detailed record of an executed trade with evidence and cost attribution."""

    trade_id: str
    symbol: str
    strategy_id: str
    strategy_version: str
    side: OrderSide
    entry_timestamp: datetime
    exit_timestamp: datetime
    entry_price: float
    exit_price: float
    quantity: int
    stop_loss: Optional[float] = None
    target_price: Optional[float] = None

    gross_pnl: float
    costs: float
    slippage: float
    net_pnl: float
    holding_time_seconds: float

    entry_reason: str
    exit_reason: str
    evidence_snapshot: Dict[str, Any] = Field(default_factory=dict)


class BacktestMetrics(BaseModel):
    """Complete quant performance metrics suite."""

    total_return_pct: float
    cagr_pct: Optional[float] = None
    number_of_trades: int
    win_rate: float
    average_win: float
    average_loss: float
    profit_factor: float
    expectancy: float
    maximum_drawdown_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    maximum_consecutive_losses: int
    average_holding_time_seconds: float
    exposure_pct: float
    total_transaction_costs: float
    total_slippage_impact: float
    worst_trade_pnl: float
    worst_day_pnl: float


class ReproducibilityRecord(BaseModel):
    """Guarantees complete reproducibility of an experiment."""

    experiment_id: str
    git_commit: str
    dataset_version: str
    strategy_version: str
    indicator_versions: Dict[str, str]
    parameters: Dict[str, Any]
    initial_capital: float
    cost_model: CostModelConfig
    slippage_model: SlippageModelConfig
    universe: List[str]
    timeframe: str
    start_date: datetime
    end_date: datetime
    random_seed: Optional[int] = 42
    environment_info: Dict[str, str] = Field(default_factory=dict)
    reproducibility_hash: str


class BacktestResult(BaseModel):
    """Complete encapsulated outcome of a backtesting run."""

    reproducibility: ReproducibilityRecord
    metrics: BacktestMetrics
    trades: List[TradeRecord] = Field(default_factory=list)
    rejected_trades_count: int = 0
    wait_decisions_count: int = 0
    equity_curve: List[Dict[str, Any]] = Field(default_factory=list)


class ExperimentStatus(str, Enum):
    CREATED = "CREATED"
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ExperimentDefinition(BaseModel):
    """Canonical specification of a systematic quantitative experiment."""

    experiment_id: str
    name: str = Field(..., min_length=1)
    description: Optional[str] = ""
    strategy_id: str = Field(..., min_length=1)
    strategy_version: str = Field(..., min_length=1)
    dataset_id: str = Field(..., min_length=1)
    dataset_version: str = Field(..., min_length=1)
    dataset_checksum: str = Field(..., min_length=64, max_length=64, description="SHA-256 dataset digest")
    universe: List[str] = Field(..., min_length=1)
    timeframe: str = Field(default="1d", min_length=1)
    start_date: datetime
    end_date: datetime
    parameters: Dict[str, Any] = Field(default_factory=dict)
    risk_policy_version: str = Field(default="1.0.0", min_length=1)
    cost_model: CostModelConfig = Field(default_factory=CostModelConfig)
    slippage_model: SlippageModelConfig = Field(default_factory=SlippageModelConfig)
    initial_capital: float = Field(default=500_000.0, gt=0.0)
    seed: int = 42
    code_revision: str = Field(default="main", min_length=1)
    fingerprint: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: ExperimentStatus = ExperimentStatus.CREATED

    @field_validator("universe")
    @classmethod
    def validate_universe(cls, v: List[str]) -> List[str]:
        if not v or len(v) == 0:
            raise ValueError("Universe cannot be empty")
        for sym in v:
            if not sym or not isinstance(sym, str) or not sym.strip():
                raise ValueError("Universe symbols must be non-empty strings")
        return v

    @model_validator(mode="after")
    def validate_dates_and_fingerprint(self) -> "ExperimentDefinition":
        if self.start_date >= self.end_date:
            raise ValueError("start_date must be strictly before end_date")
        if not self.fingerprint:
            self.fingerprint = self.compute_fingerprint()
        return self

    def compute_fingerprint(self) -> str:
        from services.backtest_engine.fingerprint import compute_reproducibility_hash
        material = {
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "dataset_checksum": self.dataset_checksum,
            "universe": sorted(self.universe),
            "timeframe": self.timeframe,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "parameters": self.parameters,
            "risk_policy_version": self.risk_policy_version,
            "cost_model": self.cost_model.model_dump() if hasattr(self.cost_model, "model_dump") else self.cost_model.dict(),
            "slippage_model": self.slippage_model.model_dump() if hasattr(self.slippage_model, "model_dump") else self.slippage_model.dict(),
            "initial_capital": self.initial_capital,
            "seed": self.seed,
            "code_revision": self.code_revision,
        }
        return compute_reproducibility_hash(material)


class ExperimentRun(BaseModel):
    """Encapsulates a backtest execution run instantiated from an experiment."""

    run_id: str
    experiment_id: str
    status: ExperimentStatus = ExperimentStatus.PENDING
    reproducibility_hash: str
    metrics: Optional[BacktestMetrics] = None
    error_message: Optional[str] = None
    trades_count: int = 0
    rejected_trades_count: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
