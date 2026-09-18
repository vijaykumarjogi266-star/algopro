"""
Algo Lab — Stage 12 Versioned Derivatives Contract Specification Registry
"""

from datetime import datetime
from typing import Dict, List, Optional
from services.derivatives_engine.contracts import (
    DerivativesContractSpec,
    ContractSpecError,
    DerivativesValidationError,
)


class DerivativesContractRegistry:
    """Registry for Point-in-Time versioned derivatives contract specifications."""

    def __init__(self):
        self._specs: Dict[str, List[DerivativesContractSpec]] = {}

    def register_spec(self, spec: DerivativesContractSpec) -> None:
        """Registers a versioned contract specification."""
        if spec.symbol not in self._specs:
            self._specs[spec.symbol] = []

        # Check for overlapping effective date ranges
        for existing in self._specs[spec.symbol]:
            if not (spec.effective_to < existing.effective_from or spec.effective_from > existing.effective_to):
                if spec.contract_version == existing.contract_version:
                    raise ContractSpecError(
                        f"Duplicate spec version {spec.contract_version} for symbol {spec.symbol}"
                    )

        self._specs[spec.symbol].append(spec)

    def get_contract_spec(self, symbol: str, timestamp: datetime) -> DerivativesContractSpec:
        """Retrieves point-in-time spec matching effective_from <= timestamp <= effective_to."""
        if symbol not in self._specs or not self._specs[symbol]:
            raise ContractSpecError(f"No contract specification registered for symbol '{symbol}'")

        matching_specs = [
            s for s in self._specs[symbol]
            if s.effective_from <= timestamp <= s.effective_to
        ]

        if not matching_specs:
            raise ContractSpecError(
                f"No contract specification valid for symbol '{symbol}' at timestamp {timestamp.isoformat()}"
            )

        # Return latest matching version
        matching_specs.sort(key=lambda s: s.effective_from, reverse=True)
        return matching_specs[0]

    def validate_order_quantity(self, spec: DerivativesContractSpec, order_quantity: int) -> bool:
        """Enforces lot-size modulo check: order_quantity % spec.lot_size == 0."""
        if order_quantity <= 0:
            raise ContractSpecError(f"Order quantity must be positive: {order_quantity}")

        if order_quantity % spec.lot_size != 0:
            raise ContractSpecError(
                f"Order quantity {order_quantity} is not an integer multiple of contract lot size {spec.lot_size} (Symbol: {spec.symbol})"
            )

        return True
