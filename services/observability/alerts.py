"""Algo Lab Observability Alert Engine.

Evaluates metric thresholds, detects pipeline lags, risk breaches, and latency spikes,
emitting actionable structured alert notifications.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from pydantic import BaseModel, Field

from apps.api.core.logging import get_logger

logger = get_logger(__name__)


class AlertSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AlertNotification(BaseModel):
    alert_id: str
    rule_name: str
    severity: AlertSeverity
    message: str
    current_value: float
    threshold_value: float
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AlertRule(BaseModel):
    name: str
    metric_name: str
    threshold: float
    operator: str  # '>', '>=', '<', '<=', '=='
    severity: AlertSeverity
    description: str


class ObservabilityAlertEngine:
    """Manages rules and threshold-based anomaly evaluation."""

    def __init__(self):
        self._rules: Dict[str, AlertRule] = {}
        self._alerts_history: List[AlertNotification] = []

    def register_rule(self, rule: AlertRule) -> None:
        self._rules[rule.name] = rule
        logger.info(f"Registered alert rule: {rule.name} on {rule.metric_name}")

    def evaluate_metric(
        self,
        metric_name: str,
        current_value: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[AlertNotification]:
        """Evaluates value against registered rules matching metric_name."""
        triggered = []
        now = datetime.now(timezone.utc)
        meta = metadata or {}

        for rule in self._rules.values():
            if rule.metric_name != metric_name:
                continue

            breached = False
            if rule.operator == ">" and current_value > rule.threshold:
                breached = True
            elif rule.operator == ">=" and current_value >= rule.threshold:
                breached = True
            elif rule.operator == "<" and current_value < rule.threshold:
                breached = True
            elif rule.operator == "<=" and current_value <= rule.threshold:
                breached = True
            elif rule.operator == "==" and current_value == rule.threshold:
                breached = True

            if breached:
                alert = AlertNotification(
                    alert_id=f"{rule.name}_{int(now.timestamp())}",
                    rule_name=rule.name,
                    severity=rule.severity,
                    message=f"Threshold breached: {rule.name} ({current_value} {rule.operator} {rule.threshold})",
                    current_value=current_value,
                    threshold_value=rule.threshold,
                    timestamp=now,
                    metadata=meta,
                )
                self._alerts_history.append(alert)
                triggered.append(alert)
                logger.warning(
                    f"OBSERVABILITY ALERT [{alert.severity.value}] {alert.message}",
                    extra={"alert": alert.model_dump()},
                )

        return triggered

    @property
    def alerts_history(self) -> List[AlertNotification]:
        return list(self._alerts_history)
