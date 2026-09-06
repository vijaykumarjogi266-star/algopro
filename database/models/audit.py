"""Algo Lab Audit and Decision Models.

Persists system audit logs, decisions (including WAIT decisions and rejected trades),
and risk trip events to maintain total reproducibility and compliance.
"""

from datetime import datetime, timezone
import uuid
from sqlalchemy import DateTime, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, TimestampMixin


class AuditLog(Base, TimestampMixin):
    """Audit trail for all platform events, risk breaches, and policy decisions."""

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), default="INFO", nullable=False)
    component: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=True, index=True)
    git_commit: Mapped[str] = mapped_column(String(64), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class DecisionRecord(Base, TimestampMixin):
    """Records every decision produced by a strategy, specifically including WAIT and REJECT.
    
    Adheres to Principle 2: WAIT is a valid decision.
    Adheres to Principle 22: Record rejected trades, WAIT decisions and missed opportunities.
    """

    __tablename__ = "decision_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    strategy_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    strategy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)  # BUY, SELL, WAIT, REJECT
    evidence_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    rejection_reason: Mapped[str] = mapped_column(Text, nullable=True)
