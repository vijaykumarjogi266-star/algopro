"""
Integrated Execution Gateway Service Interface.

Orchestrates execution safety, multi-broker position reconciliation, real-time risk circuit breakers,
and cryptographic audit provenance.
"""

from datetime import datetime, timezone
import hashlib
import json
import os
from typing import Dict, List, Optional

from services.execution_gateway.contracts import (
    GatewayState,
    CircuitBreakerConfig,
    BrokerPositionRecord,
    ReconciliationReport,
    GatewayAuditManifest,
    OrderPayload,
)
from services.execution_gateway.circuit_breaker import CircuitBreakerEngine
from services.execution_gateway.reconciliation_engine import MultiBrokerReconciliationEngine
from services.execution_gateway.safety_gateway import ExecutionSafetyGateway, StaticASTIsolationScanner


class ExecutionGatewayService:
    """
    Primary Service Interface for Stage 11 Execution Gateway.
    """

    def __init__(
        self,
        config: Optional[CircuitBreakerConfig] = None,
        environment: str = "PAPER",
        initial_cash: float = 1_000_000.0,
        state_file_path: Optional[str] = None,
    ):
        self.config = config or CircuitBreakerConfig()
        self.circuit_breaker = CircuitBreakerEngine(
            config=self.config,
            state_file_path=state_file_path,
            initial_equity=initial_cash,
        )
        self.reconciliation_engine = MultiBrokerReconciliationEngine()
        self.safety_gateway = ExecutionSafetyGateway(
            circuit_breaker=self.circuit_breaker,
            environment=environment,
            available_cash=initial_cash,
        )
        self.ast_scanner = StaticASTIsolationScanner()
        self._last_reconciliation_report: Optional[ReconciliationReport] = None

    @property
    def gateway_state(self) -> GatewayState:
        return self.circuit_breaker.state

    def record_heartbeat(self) -> None:
        self.circuit_breaker.record_heartbeat()

    def update_session_open_equity(self, session_equity: float, session_day: Optional[str] = None) -> None:
        self.circuit_breaker.update_session_open_equity(session_equity, session_day)

    def update_portfolio_equity(self, current_equity: float) -> GatewayState:
        return self.circuit_breaker.update_equity(current_equity)

    def submit_order(self, payload: OrderPayload) -> bool:
        return self.safety_gateway.validate_and_process_order(payload)

    def reconcile_positions(
        self,
        account_id: str,
        tracked_positions: Dict[str, int],
        broker_records: List[BrokerPositionRecord],
        recon_timestamp: datetime,
    ) -> ReconciliationReport:

        # Check circuit breaker before reconciliation
        if self.circuit_breaker.is_halted:
            from services.execution_gateway.contracts import CircuitBreakerTripped
            raise CircuitBreakerTripped("Gateway in EMERGENCY_HALT state")

        report = self.reconciliation_engine.reconcile_account(
            account_id=account_id,
            tracked_positions=tracked_positions,
            broker_records=broker_records,
            recon_timestamp=recon_timestamp,
        )
        self._last_reconciliation_report = report
        return report

    def run_security_scan(self) -> bool:
        gateway_dir = os.path.dirname(__file__)
        return self.ast_scanner.scan_directory(gateway_dir)

    def get_audit_manifest(self) -> GatewayAuditManifest:
        now_utc = datetime.now(timezone.utc)
        manifest_id = f"MAN-GW-{int(now_utc.timestamp())}"

        recon_hash = "0" * 64
        if self._last_reconciliation_report:
            report_json = json.dumps(
                {
                    "account_id": self._last_reconciliation_report.account_id,
                    "drift": self._last_reconciliation_report.position_drift,
                    "status": self._last_reconciliation_report.reconciliation_status,
                },
                sort_keys=True,
            )
            recon_hash = hashlib.sha256(report_json.encode("utf-8")).hexdigest()

        manifest_data = {
            "manifest_id": manifest_id,
            "timestamp": now_utc.isoformat(),
            "gateway_state": self.gateway_state.value,
            "circuit_breaker_active": self.circuit_breaker.is_halted,
            "trip_reasons": self.circuit_breaker.trip_reasons,
            "recon_hash": recon_hash,
        }
        manifest_json = json.dumps(manifest_data, sort_keys=True)
        manifest_hash = hashlib.sha256(manifest_json.encode("utf-8")).hexdigest()

        return GatewayAuditManifest(
            manifest_id=manifest_id,
            timestamp=now_utc,
            gateway_state=self.gateway_state,
            circuit_breaker_active=self.circuit_breaker.is_halted,
            manifest_hash=manifest_hash,
            reconciliation_summary_hash=recon_hash,
        )
