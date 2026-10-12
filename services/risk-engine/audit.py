"""Algo Lab Continuous Risk Audit Module.

Principle 14: Risk Engine must remain independent from Strategy/Alpha.
Principle 21: Evaluate portfolio-level risk, not only individual trades.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from services.risk_engine.contracts import HardRiskLimits


class AuditComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    WARNING = "WARNING"
    BREACHED = "BREACHED"


class RiskAuditReport(BaseModel):
    audit_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: AuditComplianceStatus
    realized_daily_pnl_pct: float
    max_drawdown_pct: float
    total_positions: int
    portfolio_equity: float
    violations: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ContinuousRiskAuditor:
    """Performs scheduled reconciliations comparing portfolio state against hard limits."""

    def __init__(self, limits: Optional[HardRiskLimits] = None):
        self.limits = limits or HardRiskLimits()

    def audit_portfolio(
        self,
        portfolio_equity: float,
        realized_daily_loss_pct: float,
        current_drawdown_pct: float,
        open_positions: List[Dict[str, Any]],
        audit_id_prefix: str = "AUDIT",
    ) -> RiskAuditReport:
        """Audits current portfolio state, detecting drift and limit breaches."""
        now = datetime.now(timezone.utc)
        violations = []
        warnings = []

        # 1. Daily Loss Audit
        if realized_daily_loss_pct >= self.limits.max_daily_loss_pct:
            violations.append(
                f"Daily loss limit breached: {realized_daily_loss_pct*100:.2f}% >= {self.limits.max_daily_loss_pct*100:.2f}%"
            )
        elif realized_daily_loss_pct >= (self.limits.max_daily_loss_pct * 0.8):
            warnings.append(
                f"Daily loss near limit threshold (80% buffer): {realized_daily_loss_pct*100:.2f}%"
            )

        # 2. Maximum Drawdown Audit
        if current_drawdown_pct >= self.limits.max_portfolio_drawdown_pct:
            violations.append(
                f"Portfolio drawdown limit breached: {current_drawdown_pct*100:.2f}% >= {self.limits.max_portfolio_drawdown_pct*100:.2f}%"
            )
        elif current_drawdown_pct >= (self.limits.max_portfolio_drawdown_pct * 0.85):
            warnings.append(
                f"Drawdown approaching critical limit (85% buffer): {current_drawdown_pct*100:.2f}%"
            )

        # 3. Position Count & Concentration Audit
        if len(open_positions) > self.limits.max_open_positions:
            violations.append(
                f"Open position count ({len(open_positions)}) exceeds hard limit ({self.limits.max_open_positions})"
            )

        # Check individual position sizes
        for pos in open_positions:
            symbol = pos.get("symbol", "UNKNOWN")
            value = pos.get("market_value", 0.0)
            weight = (value / portfolio_equity) if portfolio_equity > 0 else 0.0
            if weight > self.limits.max_capital_per_trade_pct:
                violations.append(
                    f"Position concentration breach in {symbol}: {weight*100:.2f}% > {self.limits.max_capital_per_trade_pct*100:.2f}%"
                )

        if violations:
            status = AuditComplianceStatus.BREACHED
        elif warnings:
            status = AuditComplianceStatus.WARNING
        else:
            status = AuditComplianceStatus.COMPLIANT

        return RiskAuditReport(
            audit_id=f"{audit_id_prefix}_{int(now.timestamp())}",
            timestamp=now,
            status=status,
            realized_daily_pnl_pct=realized_daily_loss_pct,
            max_drawdown_pct=current_drawdown_pct,
            total_positions=len(open_positions),
            portfolio_equity=portfolio_equity,
            violations=violations,
            warnings=warnings,
        )
