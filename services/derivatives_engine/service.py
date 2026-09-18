"""
Algo Lab — Stage 12 Integrated Derivatives Engine Service Interface
"""

import ast
from dataclasses import dataclass
import hashlib
import json
import math
import os
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from services.derivatives_engine.contracts import (
    OptionContract,
    OptionGreeks,
    OptionPricingResult,
    SPANParameterFile,
    SPANMarginReport,
    DerivativesContractSpec,
    ExpiryPinRiskAlert,
    DerivativesAuditManifest,
    OptionType,
    ExerciseStyle,
    InstrumentType,
    SettlementType,
    DerivativesValidationError,
    ASTIsolationError,
)
from services.derivatives_engine.pricing_models import BSMPricingModel, CRRPricingModel
from services.derivatives_engine.greeks_analytics import OptionGreeksCalculator
from services.derivatives_engine.iv_surface import ImpliedVolatilitySolver, VolatilitySurface
from services.derivatives_engine.span_engine import SPANMarginEngine
from services.derivatives_engine.contract_registry import DerivativesContractRegistry
from services.derivatives_engine.expiry_risk import ExpiryRiskMonitor


# INV-61: Decoupled Frozen Value Objects for AI Read-Only Boundary
@dataclass(frozen=True)
class AdvisoryContractSnapshot:
    symbol: str
    underlying: str
    strike_price: float
    option_type: str
    expiry_date: str


@dataclass(frozen=True)
class AdvisoryGreeksSnapshot:
    delta: float
    gamma: float
    vega: float
    theta: float
    rho: float


@dataclass(frozen=True)
class AdvisorySPANSnapshot:
    account_id: str
    span_risk_requirement: float
    exposure_margin: float
    total_margin_required: float
    is_margin_call: bool
    scenario_losses: tuple[float, ...]


@dataclass(frozen=True)
class AdvisoryOptionSnapshot:
    contract: AdvisoryContractSnapshot
    underlying_price: float
    theoretical_price: float
    implied_volatility: float
    greeks: AdvisoryGreeksSnapshot
    span: Optional[AdvisorySPANSnapshot]
    timestamp_utc: str


PROHIBITED_MODULES = {
    "kiteconnect",
    "upstox_client",
    "smartapi",
    "socket",
    "websockets",
    "urllib",
    "requests",
    "httpx",
    "aiohttp",
    "importlib",
    "subprocess",
}

PROHIBITED_BUILTINS = {"eval", "exec"}


def _canonicalize_value(val: Any) -> Any:
    """
    Recursively canonicalizes dictionary and sequence values according to the Stage 12 audit contract:
    - Dict keys normalized to Unicode NFC and sorted lexicographically.
    - Sequences preserve order; elements canonicalized recursively.
    - Strings normalized to Unicode NFC.
    - Floats canonicalized to 8 decimal places; non-finite floats rejected.
    - Hash/signature fields ('content_hash', 'hmac_signature', 'manifest_hash_sha256') excluded.
    """
    if val is None or isinstance(val, (bool, int)):
        return val
    elif isinstance(val, float):
        if math.isnan(val) or math.isinf(val):
            raise ValueError(f"Non-finite float value detected in audit payload: {val}")
        return round(val, 8)
    elif isinstance(val, str):
        return unicodedata.normalize("NFC", val)
    elif isinstance(val, dict):
        result = {}
        for k in sorted(val.keys()):
            k_norm = unicodedata.normalize("NFC", str(k))
            if k_norm in ("content_hash", "hmac_signature", "manifest_hash_sha256"):
                continue
            result[k_norm] = _canonicalize_value(val[k])
        return result
    elif isinstance(val, (list, tuple)):
        return [_canonicalize_value(item) for item in val]
    else:
        return unicodedata.normalize("NFC", str(val))


class DerivativesService:
    """Integrated Research & Risk Replay Interface for Derivatives Analytics."""

    def __init__(self, environment: str = "RESEARCH"):
        if environment == "LIVE":
            raise PermissionError("Derivatives Engine firewall explicitly blocks LIVE execution environment")
        self.environment = environment
        self.contract_registry = DerivativesContractRegistry()
        self.expiry_monitor = ExpiryRiskMonitor()

    @staticmethod
    def verify_ast_isolation(target_dir: str = "/root/sandbox/algopro/services/derivatives_engine") -> bool:
        """Parses AST nodes of all Python files in derivatives engine directory to enforce execution firewall."""
        if not os.path.exists(target_dir):
            return True

        for root, _, files in os.walk(target_dir):
            for f in files:
                if f.endswith(".py"):
                    full_path = os.path.join(root, f)
                    with open(full_path, "r", encoding="utf-8") as file_handle:
                        content = file_handle.read()

                    try:
                        tree = ast.parse(content, filename=full_path)
                    except SyntaxError as e:
                        raise ASTIsolationError(f"Syntax error during AST isolation scan: {e}")

                    for node in ast.walk(tree):
                        # 1. Prohibited module imports
                        if isinstance(node, ast.Import):
                            for alias in node.names:
                                mod_root = alias.name.split(".")[0]
                                if mod_root in PROHIBITED_MODULES:
                                    raise ASTIsolationError(
                                        f"Prohibited broker/network module import '{alias.name}' detected in {f}"
                                    )
                        elif isinstance(node, ast.ImportFrom):
                            if node.module:
                                mod_root = node.module.split(".")[0]
                                if mod_root in PROHIBITED_MODULES:
                                    raise ASTIsolationError(
                                        f"Prohibited broker/network import from '{node.module}' detected in {f}"
                                    )
                        # 2. Prohibited builtins (eval, exec)
                        elif isinstance(node, ast.Call):
                            if isinstance(node.func, ast.Name):
                                if node.func.id in PROHIBITED_BUILTINS:
                                    raise ASTIsolationError(
                                        f"Prohibited call '{node.func.id}' detected in {f}"
                                    )
        return True

    def price_option(
        self,
        contract: OptionContract,
        underlying_price: float,
        time_to_expiry_years: float,
        risk_free_rate: float,
        dividend_yield: float,
        volatility: float,
        pricing_model: str = "BSM",
        crr_steps: int = 100,
    ) -> OptionPricingResult:
        """Prices an option contract using BSM analytical or CRR tree pricing engine."""
        if pricing_model == "BSM":
            theoretical_price = BSMPricingModel.calculate_price(
                underlying_price,
                contract.strike_price,
                time_to_expiry_years,
                risk_free_rate,
                dividend_yield,
                volatility,
                contract.option_type,
            )
            greeks = OptionGreeksCalculator.calculate_greeks_analytical(
                underlying_price,
                contract.strike_price,
                time_to_expiry_years,
                risk_free_rate,
                dividend_yield,
                volatility,
                contract.option_type,
            )
        elif pricing_model == "CRR":
            theoretical_price = CRRPricingModel.calculate_price(
                underlying_price,
                contract.strike_price,
                time_to_expiry_years,
                risk_free_rate,
                dividend_yield,
                volatility,
                contract.option_type,
                contract.exercise_style,
                steps=crr_steps,
            )
            greeks = OptionGreeksCalculator.calculate_greeks_finite_difference(
                underlying_price,
                contract.strike_price,
                time_to_expiry_years,
                risk_free_rate,
                dividend_yield,
                volatility,
                contract.option_type,
            )
        else:
            raise DerivativesValidationError(f"Unknown pricing model: '{pricing_model}'")

        return OptionPricingResult(
            contract=contract,
            underlying_price=underlying_price,
            time_to_expiry_years=time_to_expiry_years,
            risk_free_rate=risk_free_rate,
            dividend_yield=dividend_yield,
            volatility=volatility,
            theoretical_price=theoretical_price,
            greeks=greeks,
            pricing_model_used=pricing_model,
        )

    def create_advisory_snapshot(
        self,
        result: OptionPricingResult,
        margin_report: Optional[SPANMarginReport] = None,
    ) -> AdvisoryOptionSnapshot:
        """Generates a deeply frozen, decoupled value snapshot for AI advisory consumers (INV-61)."""
        contract_snap = AdvisoryContractSnapshot(
            symbol=result.contract.symbol,
            underlying=result.contract.underlying_symbol,
            strike_price=result.contract.strike_price,
            option_type=result.contract.option_type.value if hasattr(result.contract.option_type, "value") else str(result.contract.option_type),
            expiry_date=result.contract.expiration_date.isoformat() if hasattr(result.contract.expiration_date, "isoformat") else str(result.contract.expiration_date),
        )
        greeks_snap = AdvisoryGreeksSnapshot(
            delta=result.greeks.delta,
            gamma=result.greeks.gamma,
            vega=result.greeks.vega,
            theta=result.greeks.theta,
            rho=result.greeks.rho,
        )
        span_snap = None
        if margin_report:
            span_snap = AdvisorySPANSnapshot(
                account_id=margin_report.account_id,
                span_risk_requirement=margin_report.span_risk_requirement,
                exposure_margin=margin_report.exposure_margin,
                total_margin_required=margin_report.total_margin_required,
                is_margin_call=margin_report.is_margin_call,
                scenario_losses=tuple([0.0] * 16),
            )

        timestamp_str = datetime.now(timezone.utc).isoformat()
        return AdvisoryOptionSnapshot(
            contract=contract_snap,
            underlying_price=result.underlying_price,
            theoretical_price=result.theoretical_price,
            implied_volatility=result.volatility,
            greeks=greeks_snap,
            span=span_snap,
            timestamp_utc=timestamp_str,
        )

    def generate_audit_manifest(
        self,
        manifest_id: str,
        pricing_results: List[OptionPricingResult],
        margin_report: Optional[SPANMarginReport] = None,
        model_version: str = "v12.0",
        dataset_version: str = "v2026.1",
    ) -> DerivativesAuditManifest:
        """Generates a canonical cryptographic audit manifest with SHA-256 digest (INV-62)."""
        pricing_summary = {}
        for res in pricing_results:
            pricing_summary[res.contract.symbol] = res.theoretical_price

        span_summary = {}
        if margin_report:
            span_summary = {
                "account_id": margin_report.account_id,
                "span_risk_requirement": margin_report.span_risk_requirement,
                "exposure_margin": margin_report.exposure_margin,
                "total_margin_required": margin_report.total_margin_required,
                "is_margin_call": margin_report.is_margin_call,
            }

        timestamp_str = datetime.now(timezone.utc).isoformat()
        raw_dict = {
            "dataset_version": dataset_version,
            "manifest_id": manifest_id,
            "model_version": model_version,
            "pricing_results_summary": pricing_summary,
            "span_margin_summary": span_summary,
            "timestamp": timestamp_str,
        }

        canonical_dict = _canonicalize_value(raw_dict)
        canonical_json = json.dumps(canonical_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

        return DerivativesAuditManifest(
            manifest_id=manifest_id,
            timestamp=timestamp_str,
            model_version=model_version,
            dataset_version=dataset_version,
            pricing_results_summary=pricing_summary,
            span_margin_summary=span_summary,
            manifest_hash_sha256=digest,
        )

    @staticmethod
    def verify_manifest(manifest: DerivativesAuditManifest) -> bool:
        """Re-computes canonical SHA-256 digest and verifies audit manifest integrity."""
        raw_dict = {
            "dataset_version": manifest.dataset_version,
            "manifest_id": manifest.manifest_id,
            "model_version": manifest.model_version,
            "pricing_results_summary": manifest.pricing_results_summary,
            "span_margin_summary": manifest.span_margin_summary,
            "timestamp": manifest.timestamp,
        }

        try:
            canonical_dict = _canonicalize_value(raw_dict)
            canonical_json = json.dumps(canonical_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            expected_digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
            return expected_digest == manifest.manifest_hash_sha256
        except Exception:
            return False
