"""Algo Lab Risk Engine Implementation.

Adheres to Non-Negotiable Principles:
- Principle 14: Risk Engine must remain independent from Strategy/Alpha.
- Principle 15: AI must never override hard risk controls.
- Principle 21: Evaluate portfolio-level risk, not only individual trades.
"""

from datetime import datetime, timezone
from typing import Optional
from services.risk_engine.contracts import (
    IRiskEngine,
    HardRiskLimits,
    RiskEvaluationResult,
    RiskRejectionCode,
)


class RiskEngine(IRiskEngine):
    """Concrete independent Risk Engine enforcing hard risk limits."""

    def __init__(self, limits: Optional[HardRiskLimits] = None):
        self.limits = limits or HardRiskLimits()

    def evaluate(
        self,
        symbol: str,
        price: float,
        proposed_quantity: int,
        stop_loss: Optional[float],
        current_portfolio_value: float,
        current_daily_loss_pct: float,
        current_drawdown_pct: float,
        current_open_positions_count: int,
    ) -> RiskEvaluationResult:
        """Evaluates an order proposal against hard portfolio & asset-level limits."""
        now = datetime.now(timezone.utc)

        # 1. Price and quantity sanity
        if price <= 0 or proposed_quantity <= 0:
            return RiskEvaluationResult(
                is_approved=False,
                rejection_code=RiskRejectionCode.EXCEEDS_MAX_CAPITAL,
                rejection_reason=f"Invalid price ({price}) or quantity ({proposed_quantity})",
                approved_quantity=0,
                timestamp=now,
            )

        # 2. Mandatory stop loss check
        if self.limits.enforce_mandatory_stop_loss and (stop_loss is None or stop_loss <= 0):
            return RiskEvaluationResult(
                is_approved=False,
                rejection_code=RiskRejectionCode.MISSING_STOP_LOSS,
                rejection_reason="Mandatory stop loss missing or invalid",
                approved_quantity=0,
                timestamp=now,
            )

        # 3. Maximum capital per trade check
        trade_value = proposed_quantity * price
        max_allowed_capital = current_portfolio_value * self.limits.max_capital_per_trade_pct
        if trade_value > max_allowed_capital:
            return RiskEvaluationResult(
                is_approved=False,
                rejection_code=RiskRejectionCode.EXCEEDS_MAX_CAPITAL,
                rejection_reason=f"Trade value INR {trade_value:.2f} exceeds max trade limit INR {max_allowed_capital:.2f}",
                approved_quantity=0,
                timestamp=now,
            )

        # 4. Daily loss limit breach check
        if current_daily_loss_pct >= self.limits.max_daily_loss_pct:
            return RiskEvaluationResult(
                is_approved=False,
                rejection_code=RiskRejectionCode.DAILY_LOSS_LIMIT_BREACHED,
                rejection_reason=f"Daily loss {current_daily_loss_pct*100:.2f}% breached max daily limit {self.limits.max_daily_loss_pct*100:.2f}%",
                approved_quantity=0,
                timestamp=now,
            )

        # 5. Portfolio drawdown limit breach check
        if current_drawdown_pct >= self.limits.max_portfolio_drawdown_pct:
            return RiskEvaluationResult(
                is_approved=False,
                rejection_code=RiskRejectionCode.DRAWDOWN_LIMIT_BREACHED,
                rejection_reason=f"Drawdown {current_drawdown_pct*100:.2f}% breached max limit {self.limits.max_portfolio_drawdown_pct*100:.2f}%",
                approved_quantity=0,
                timestamp=now,
            )

        # 6. Max open positions limit check
        if current_open_positions_count >= self.limits.max_open_positions:
            return RiskEvaluationResult(
                is_approved=False,
                rejection_code=RiskRejectionCode.MAX_POSITIONS_REACHED,
                rejection_reason=f"Open positions count ({current_open_positions_count}) reached maximum limit ({self.limits.max_open_positions})",
                approved_quantity=0,
                timestamp=now,
            )

        # Approved
        return RiskEvaluationResult(
            is_approved=True,
            rejection_code=RiskRejectionCode.APPROVED,
            rejection_reason=None,
            approved_quantity=proposed_quantity,
            adjusted_stop_loss=stop_loss,
            timestamp=now,
        )
