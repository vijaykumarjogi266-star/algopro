"""
Algo Lab — Stage 12 0DTE Expiry Session & Pin Risk Management System
"""

from datetime import datetime, time, timedelta, timezone
from typing import Optional, Tuple
import math
from services.derivatives_engine.contracts import (
    OptionContract,
    SettlementType,
    InstrumentType,
    ExpiryPinRiskAlert,
    SettlementRuleError,
    DerivativesValidationError,
)

# IST Timezone (UTC + 05:30)
IST = timezone(timedelta(hours=5, minutes=30))


class ExpiryRiskMonitor:
    """Monitors 0DTE IST trading session state, pin risk, and physical settlement assignment risks."""

    def __init__(self, max_pin_risk_distance_pct: float = 0.005):
        self.max_pin_risk_distance_pct = max_pin_risk_distance_pct

    @staticmethod
    def is_ist_session_active(timestamp: datetime) -> bool:
        """Evaluates whether timestamp falls within NSE IST trading session (09:15 - 15:30 IST)."""
        # Convert to IST if naive or in another timezone
        if timestamp.tzinfo is None:
            ist_time = timestamp.replace(tzinfo=IST)
        else:
            ist_time = timestamp.astimezone(IST)

        session_start = time(9, 15, 0)
        session_end = time(15, 30, 0)
        t_current = ist_time.time()

        return session_start <= t_current <= session_end

    def evaluate_pin_risk(
        self,
        contract: OptionContract,
        underlying_price: float,
        current_timestamp: datetime,
        settlement_type: SettlementType = SettlementType.CASH,
    ) -> ExpiryPinRiskAlert:
        """Evaluates 0DTE pin risk and settlement assignment risks."""
        if math.isnan(underlying_price) or math.isinf(underlying_price) or underlying_price <= 0.0:
            raise DerivativesValidationError(f"Invalid underlying price: {underlying_price}")

        if current_timestamp.tzinfo is None:
            ist_current = current_timestamp.replace(tzinfo=IST)
        else:
            ist_current = current_timestamp.astimezone(IST)

        if contract.expiration_date.tzinfo is None:
            ist_expiry = contract.expiration_date.replace(tzinfo=IST)
        else:
            ist_expiry = contract.expiration_date.astimezone(IST)

        is_0dte = (ist_current.date() == ist_expiry.date())
        time_to_close_seconds = (
            datetime.combine(ist_current.date(), time(15, 30, 0), tzinfo=IST) - ist_current
        ).total_seconds()

        d_pin = abs(underlying_price - contract.strike_price) / contract.strike_price

        is_itm = False
        if contract.option_type.name == "CALL":
            is_itm = underlying_price > contract.strike_price
        elif contract.option_type.name == "PUT":
            is_itm = underlying_price < contract.strike_price

        # Pin Risk Level Determination
        pin_level = "LOW"
        action = "MONITOR"

        if is_0dte:
            if d_pin <= self.max_pin_risk_distance_pct and time_to_close_seconds <= 1800.0 and time_to_close_seconds >= 0.0:
                pin_level = "CRITICAL"
                action = "CLOSE_POSITION_IMMEDIATELY"
            elif d_pin <= self.max_pin_risk_distance_pct:
                pin_level = "WARNING"
                action = "PREPARE_EXPIRY_HEDGE"

        if settlement_type == SettlementType.PHYSICAL and is_itm and is_0dte:
            action += " | PHYSICAL_ASSIGNMENT_ALERT"

        return ExpiryPinRiskAlert(
            timestamp=ist_current,
            contract=contract,
            underlying_price=underlying_price,
            distance_to_strike_pct=d_pin,
            is_0dte=is_0dte,
            is_itm=is_itm,
            settlement_type=settlement_type,
            pin_risk_level=pin_level,
            action_recommended=action,
        )

    @staticmethod
    def enforce_settlement_rule(
        instrument_type: InstrumentType,
        declared_settlement: SettlementType,
    ) -> SettlementType:
        """Enforces NSE index cash settlement vs stock physical settlement rules."""
        if instrument_type in (InstrumentType.OPTIDX, InstrumentType.FUTIDX):
            if declared_settlement != SettlementType.CASH:
                raise SettlementRuleError(
                    f"Index contract {instrument_type} must be CASH settled, got {declared_settlement}"
                )
            return SettlementType.CASH
        elif instrument_type in (InstrumentType.OPTSTK, InstrumentType.FUTSTK):
            if declared_settlement not in (SettlementType.PHYSICAL, SettlementType.CASH):
                raise SettlementRuleError(f"Unsupported settlement type: {declared_settlement}")
            return declared_settlement
        else:
            raise SettlementRuleError(f"Unknown instrument type: {instrument_type}")
