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
    """Deterministic 16-Scenario SPAN Portfolio Margin Reconstruction Engine (Fail-Closed)."""

    @staticmethod
    def calculate_margin(
        account_id: str,
        positions: List[Dict],  # List of {"symbol": str, "quantity": int, "strike": float, "underlying_price": float, "option_type": str, "nov": float}
        span_file: SPANParameterFile,
        available_collateral: float,
        timestamp: datetime,
        exposure_margin_pct: float = 0.03,
    ) -> SPANMarginReport:
        if available_collateral < 0.0 or math.isnan(available_collateral) or math.isinf(available_collateral):
            raise DerivativesValidationError(f"Invalid available_collateral: {available_collateral}")

        # Reconstruct 16-scenario losses across positions
        scenario_losses = [0.0] * 16
        total_nov = 0.0
        total_contract_value = 0.0

        for pos in positions:
            sym = pos.get("symbol")
            if not sym or sym not in span_file.risk_arrays:
                raise SPANParameterError(f"FAIL CLOSED: Missing SPAN risk array for symbol '{sym}'")

            arr = span_file.risk_arrays[sym]
            if not isinstance(arr, list) or len(arr) != 16:
                raise SPANParameterError(
                    f"FAIL CLOSED: Invalid scenario array length for symbol '{sym}'. Expected 16, got {len(arr) if isinstance(arr, list) else type(arr)}"
                )

            for idx, val in enumerate(arr):
                if not isinstance(val, (int, float)) or math.isnan(val) or math.isinf(val):
                    raise SPANParameterError(
                        f"FAIL CLOSED: Non-finite or invalid scenario value at index {idx} for symbol '{sym}': {val}"
                    )

            qty = pos["quantity"]
            nov = pos.get("nov", 0.0) * qty
            total_nov += nov

            und_price = pos.get("underlying_price", 100.0)
            total_contract_value += abs(qty) * und_price

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
