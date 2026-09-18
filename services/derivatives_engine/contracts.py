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
