"""
Algo Lab — Stage 12 NSE SPAN Parameter File Ingestion & 16-Scenario Risk Replay Engine
"""

import hashlib
import json
import math
from datetime import datetime
from typing import Dict, List, Optional
from services.derivatives_engine.contracts import (
    SPANParameterFile,
    SPANMarginReport,
    DerivativesValidationError,
    SPANParameterError,
    MarginCallError,
)


class SPANParameterFileIngestor:
    """Ingests and validates published NSE SPAN parameter files with SHA-256 verification."""

    @staticmethod
    def compute_sha256(raw_bytes: bytes) -> str:
        return hashlib.sha256(raw_bytes).hexdigest()

    @staticmethod
    def parse_parameter_file(
        raw_content: str,
        expected_checksum: Optional[str] = None,
    ) -> SPANParameterFile:
        calculated_checksum = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()

        if expected_checksum and calculated_checksum != expected_checksum:
            raise SPANParameterError(
                f"SPAN checksum mismatch: expected {expected_checksum}, calculated {calculated_checksum}"
            )

        try:
            data = json.loads(raw_content)
        except Exception as e:
            raise SPANParameterError(f"Failed to parse SPAN parameter file JSON: {e}")

        for req in ["file_version", "effective_timestamp", "source_id", "risk_arrays"]:
            if req not in data:
                raise SPANParameterError(f"Missing required field in SPAN parameter file: '{req}'")

        if data.get("source_id") != "NSE_CLEARING":
            raise SPANParameterError(f"Invalid SPAN source_id: {data.get('source_id')}")

        return SPANParameterFile(
            file_version=data["file_version"],
            effective_timestamp=datetime.fromisoformat(data["effective_timestamp"]),
            source_id=data["source_id"],
            checksum_sha256=calculated_checksum,
            risk_arrays=data["risk_arrays"],
            price_scan_range=data.get("price_scan_range", {}),
            volatility_scan_range=data.get("volatility_scan_range", {}),
        )


class SPANMarginEngine:
    """Deterministic 16-Scenario SPAN Portfolio Margin Reconstruction Engine."""

    @staticmethod
    def calculate_margin(
        account_id: str,
        positions: List[Dict],  # List of {"symbol": str, "quantity": int, "strike": float, "underlying_price": float, "option_type": str, "nov": float}
        span_file: SPANParameterFile,
        available_collateral: float,
        timestamp: datetime,
        exposure_margin_pct: float = 0.03,
    ) -> SPANMarginReport:
        if available_collateral < 0.0 or math.isnan(available_collateral):
            raise DerivativesValidationError(f"Invalid available_collateral: {available_collateral}")

        # Reconstruct 16-scenario losses across positions
        scenario_losses = [0.0] * 16
        total_nov = 0.0
        total_contract_value = 0.0

        for pos in positions:
            sym = pos["symbol"]
            qty = pos["quantity"]
            nov = pos.get("nov", 0.0) * qty
            total_nov += nov

            und_price = pos.get("underlying_price", 100.0)
            total_contract_value += abs(qty) * und_price

            # Fetch or generate 16-scenario risk array
            if sym in span_file.risk_arrays and len(span_file.risk_arrays[sym]) == 16:
                arr = span_file.risk_arrays[sym]
            else:
                # Default 16-scenario synthetic reconstruction if symbol array not explicitly mapped
                psr = span_file.price_scan_range.get(sym, 0.05 * und_price)
                vsr = span_file.volatility_scan_range.get(sym, 0.02)
                arr = SPANMarginEngine._generate_synthetic_16_scenarios(und_price, psr, vsr)

            for i in range(16):
                scenario_losses[i] += qty * arr[i]

        span_risk_requirement = max(0.0, max(scenario_losses)) if scenario_losses else 0.0
        exposure_margin = total_contract_value * exposure_margin_pct
        total_margin_required = span_risk_requirement + abs(total_nov) + exposure_margin

        is_margin_call = total_margin_required > available_collateral

        return SPANMarginReport(
            timestamp=timestamp,
            account_id=account_id,
            span_file_version=span_file.file_version,
            span_file_checksum=span_file.checksum_sha256,
            span_risk_requirement=span_risk_requirement,
            exposure_margin=exposure_margin,
            net_option_value=abs(total_nov),
            total_margin_required=total_margin_required,
            available_collateral=available_collateral,
            is_margin_call=is_margin_call,
        )

    @staticmethod
    def _generate_synthetic_16_scenarios(spot: float, psr: float, vsr: float) -> List[float]:
        """Generates standard NSE SPAN 16 price/volatility scenario loss multipliers."""
        return [
            0.0,                       # Scenario 1: Price 0, Vol +VSR
            0.0,                       # Scenario 2: Price 0, Vol -VSR
            (1/3) * psr + vsr * spot,  # Scenario 3: +1/3 PSR, +VSR
            (1/3) * psr - vsr * spot,  # Scenario 4: +1/3 PSR, -VSR
            -(1/3) * psr + vsr * spot, # Scenario 5: -1/3 PSR, +VSR
            -(1/3) * psr - vsr * spot, # Scenario 6: -1/3 PSR, -VSR
            (2/3) * psr + vsr * spot,  # Scenario 7: +2/3 PSR, +VSR
            (2/3) * psr - vsr * spot,  # Scenario 8: +2/3 PSR, -VSR
            -(2/3) * psr + vsr * spot, # Scenario 9: -2/3 PSR, +VSR
            -(2/3) * psr - vsr * spot, # Scenario 10: -2/3 PSR, -VSR
            1.0 * psr + vsr * spot,    # Scenario 11: +1 PSR, +VSR
            1.0 * psr - vsr * spot,    # Scenario 12: +1 PSR, -VSR
            -1.0 * psr + vsr * spot,   # Scenario 13: -1 PSR, +VSR
            -1.0 * psr - vsr * spot,   # Scenario 14: -1 PSR, -VSR
            0.35 * (2.0 * psr),        # Scenario 15: +2 PSR Extreme
            0.35 * (-2.0 * psr),       # Scenario 16: -2 PSR Extreme
        ]
