"""
Algo Lab — Stage 12 Derivatives Engine Data Contracts & Exceptions
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional
import math
import json
import hashlib


class InstrumentType(str, Enum):
    OPTIDX = "OPTIDX"
    OPTSTK = "OPTSTK"
    FUTIDX = "FUTIDX"
    FUTSTK = "FUTSTK"


class OptionType(str, Enum):
    CALL = "CALL"
    PUT = "PUT"
    NONE = "NONE"


class ExerciseStyle(str, Enum):
    EUROPEAN = "EUROPEAN"
    AMERICAN = "AMERICAN"


class SettlementType(str, Enum):
    CASH = "CASH"
    PHYSICAL = "PHYSICAL"


# Base Exceptions
class DerivativesError(Exception):
    """Base exception for derivatives engine errors."""
    pass


class DerivativesValidationError(DerivativesError):
    """Raised when input parameters or non-finite values fail validation."""
    pass


class DerivativesPricingError(DerivativesError):
    """Raised when pricing models fail to compute valid outputs."""
    pass


class CRRConvergenceError(DerivativesError):
    """Raised when CRR tree risk-neutral probability or convergence fails."""
    pass


class IVConvergenceError(DerivativesError):
    """Raised when Implied Volatility solver fails to converge or breaches intrinsic bounds."""
    pass


class VolatilitySurfaceArbitrageError(DerivativesError):
    """Raised when volatility surface exhibits strike or calendar arbitrage."""
    pass


class SPANParameterError(DerivativesError):
    """Raised when SPAN parameter file checksum or structure is invalid."""
    pass


class ContractSpecError(DerivativesError):
    """Raised when contract specification lookup or lot size validation fails."""
    pass


class SettlementRuleError(DerivativesError):
    """Raised when settlement type rule evaluation fails."""
    pass


class MarginCallError(DerivativesError):
    """Raised when total required margin exceeds available collateral."""
    pass


class ASTIsolationError(DerivativesError):
    """Raised when static AST security scan detects prohibited imports or execution paths."""
    pass


class StaleSnapshotError(DerivativesError):
    """Raised when point-in-time snapshot contains post-dated data."""
    pass


@dataclass(frozen=True)
class OptionContract:
    symbol: str
    underlying_symbol: str
    strike_price: float
    expiration_date: datetime
    option_type: OptionType
    exercise_style: ExerciseStyle = ExerciseStyle.EUROPEAN
    currency: str = "INR"

    def __post_init__(self):
        if not self.symbol or not self.underlying_symbol:
            raise DerivativesValidationError("Symbols must be non-empty strings")
        if math.isnan(self.strike_price) or math.isinf(self.strike_price) or self.strike_price <= 0.0:
            raise DerivativesValidationError(f"Invalid strike_price: {self.strike_price}")


@dataclass(frozen=True)
class OptionGreeks:
    delta: float
    gamma: float
    vega: float
    theta: float
    rho: float

    def __post_init__(self):
        for name, val in [("delta", self.delta), ("gamma", self.gamma), ("vega", self.vega), ("theta", self.theta), ("rho", self.rho)]:
            if math.isnan(val) or math.isinf(val):
                raise DerivativesValidationError(f"Non-finite value in OptionGreeks for {name}: {val}")


@dataclass(frozen=True)
class OptionPricingResult:
    contract: OptionContract
    underlying_price: float
    time_to_expiry_years: float
    risk_free_rate: float
    dividend_yield: float
    volatility: float
    theoretical_price: float
    greeks: OptionGreeks
    pricing_model_used: str

    def __post_init__(self):
        for name, val in [
            ("underlying_price", self.underlying_price),
            ("time_to_expiry_years", self.time_to_expiry_years),
            ("risk_free_rate", self.risk_free_rate),
            ("dividend_yield", self.dividend_yield),
            ("volatility", self.volatility),
            ("theoretical_price", self.theoretical_price),
        ]:
            if math.isnan(val) or math.isinf(val):
                raise DerivativesValidationError(f"Non-finite value in OptionPricingResult for {name}: {val}")


@dataclass(frozen=True)
class DerivativesContractSpec:
    contract_id: str
    symbol: str
    underlying_symbol: str
    instrument_type: InstrumentType
    expiry_date: datetime
    strike_price: float
    option_type: OptionType
    exercise_style: ExerciseStyle
    settlement_type: SettlementType
    lot_size: int
    currency: str
    effective_from: datetime
    effective_to: datetime
    contract_version: str
    checksum_sha256: str

    def __post_init__(self):
        if self.lot_size <= 0:
            raise ContractSpecError(f"Invalid lot size: {self.lot_size}")


@dataclass(frozen=True)
class SPANParameterFile:
    file_version: str
    effective_timestamp: datetime
    source_id: str
    checksum_sha256: str
    risk_arrays: Dict[str, List[float]]
    price_scan_range: Dict[str, float]
    volatility_scan_range: Dict[str, float]


@dataclass(frozen=True)
class SPANMarginReport:
    timestamp: datetime
    account_id: str
    span_file_version: str
    span_file_checksum: str
    span_risk_requirement: float
    exposure_margin: float
    net_option_value: float
    total_margin_required: float
    available_collateral: float
    is_margin_call: bool


@dataclass(frozen=True)
class ExpiryPinRiskAlert:
    timestamp: datetime
    contract: OptionContract
    underlying_price: float
    distance_to_strike_pct: float
    is_0dte: bool
    is_itm: bool
    settlement_type: SettlementType
    pin_risk_level: str
    action_recommended: str


@dataclass(frozen=True)
class DerivativesAuditManifest:
    manifest_id: str
    timestamp: str
    model_version: str
    dataset_version: str
    pricing_results_summary: Dict[str, float]
    span_margin_summary: Dict[str, float]
    manifest_hash_sha256: str


# Stage 13 Exceptions
class GreeksHedgingLimitError(DerivativesError):
    """Raised when required delta hedge quantity breaches maximum limit."""
    pass


class StrategyBacktestError(DerivativesError):
    """Raised when strategy backtest execution fails or collateral is insufficient."""
    pass


class StrategyType(str, Enum):
    BULL_CALL_SPREAD = "BULL_CALL_SPREAD"
    BEAR_CALL_SPREAD = "BEAR_CALL_SPREAD"
    BULL_PUT_SPREAD = "BULL_PUT_SPREAD"
    BEAR_PUT_SPREAD = "BEAR_PUT_SPREAD"
    STRADDLE = "STRADDLE"
    STRANGLE = "STRANGLE"
    IRON_CONDOR = "IRON_CONDOR"
    BUTTERFLY = "BUTTERFLY"
    COLLAR = "COLLAR"
    SYNTHETIC_LONG = "SYNTHETIC_LONG"
    CUSTOM = "CUSTOM"


@dataclass(frozen=True)
class OptionLeg:
    contract: OptionContract
    quantity: int  # Positive for Long, Negative for Short
    entry_price: float

    def __post_init__(self):
        if self.quantity == 0:
            raise DerivativesValidationError("Leg quantity cannot be zero")
        if math.isnan(self.entry_price) or math.isinf(self.entry_price) or self.entry_price < 0.0:
            raise DerivativesValidationError(f"Invalid leg entry_price: {self.entry_price}")


@dataclass(frozen=True)
class OptionStrategySpec:
    name: str
    strategy_type: StrategyType
    legs: List[OptionLeg]
    underlying_symbol: str
    underlying_price: float

    def __post_init__(self):
        if not self.name or not self.underlying_symbol:
            raise DerivativesValidationError("Strategy name and underlying_symbol must be non-empty")
        if not self.legs:
            raise DerivativesValidationError("Strategy must contain at least one leg")
        if math.isnan(self.underlying_price) or math.isinf(self.underlying_price) or self.underlying_price <= 0.0:
            raise DerivativesValidationError(f"Invalid underlying_price: {self.underlying_price}")


@dataclass(frozen=True)
class AdvisoryOptionStrategySnapshot:
    strategy_name: str
    strategy_type: str
    net_pnl: float
    net_delta: float
    net_gamma: float
    net_vega: float
    net_theta: float
    span_margin_required: float
    timestamp_utc: str


@dataclass(frozen=True)
class StrategyBacktestResult:
    strategy_name: str
    realized_pnl: float
    unrealized_pnl: float
    total_pnl: float
    net_premium_collected: float
    total_transaction_fees: float
    total_slippage: float
    total_roll_costs: float
    final_nov: float
    span_margin_required: float
    execution_status: str
    hedge_history: List[Dict] = field(default_factory=list)
    manifest_hash: str = ""


@dataclass(frozen=True)
class StressGridReport:
    strategy_name: str
    spot_shifts: List[float]
    vol_shifts: List[float]
    grid_pnls: List[List[float]]
    max_stress_loss: float
