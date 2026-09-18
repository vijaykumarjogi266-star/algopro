"""
Algo Lab — Stage 12 Integrated Derivatives Engine Service Interface
"""

import ast
import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional
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

    def generate_audit_manifest(
        self,
        manifest_id: str,
        pricing_results: List[OptionPricingResult],
        margin_report: Optional[SPANMarginReport] = None,
        model_version: str = "v12.0",
        dataset_version: str = "v2026.1",
    ) -> DerivativesAuditManifest:
        """Generates a canonical cryptographic audit manifest with SHA-256 digest."""
        pricing_summary = {}
        for res in pricing_results:
            pricing_summary[res.contract.symbol] = round(res.theoretical_price, 6)

        span_summary = {}
        if margin_report:
            span_summary = {
                "account_id": margin_report.account_id,
                "span_risk_requirement": round(margin_report.span_risk_requirement, 6),
                "exposure_margin": round(margin_report.exposure_margin, 6),
                "total_margin_required": round(margin_report.total_margin_required, 6),
                "is_margin_call": margin_report.is_margin_call,
            }

        timestamp_str = datetime.now(timezone.utc).isoformat()
        canonical_dict = {
            "dataset_version": dataset_version,
            "manifest_id": manifest_id,
            "model_version": model_version,
            "pricing_results_summary": pricing_summary,
            "span_margin_summary": span_summary,
            "timestamp": timestamp_str,
        }

        canonical_json = json.dumps(canonical_dict, sort_keys=True, separators=(",", ":"))
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
