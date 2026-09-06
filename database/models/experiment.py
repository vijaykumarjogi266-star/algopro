"""Algo Lab Experiment & Trade Record Database Models.

Stores full metadata, versioning, parameters, and trade records
for auditability and reproducibility of backtests and paper runs.
"""

from datetime import datetime, timezone
import uuid
from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base, TimestampMixin


class Experiment(Base, TimestampMixin):
    """Encapsulates a backtest or research experiment configuration and outcomes."""

    __tablename__ = "experiments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    experiment_id: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    git_commit: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset_version: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    strategy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    indicator_versions: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    universe: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    timeframe: Mapped[str] = mapped_column(String(16), nullable=False)
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    initial_capital: Mapped[float] = mapped_column(Float, nullable=False)
    cost_model: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    slippage_model: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    parameters: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)
    reproducibility_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    trades: Mapped[list["TradeRecordModel"]] = relationship(
        "TradeRecordModel", back_populates="experiment", cascade="all, delete-orphan"
    )


class TradeRecordModel(Base, TimestampMixin):
    """Database record for every simulated or paper trade."""

    __tablename__ = "trade_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    experiment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("algolab.experiments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    trade_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    strategy_name: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(16), nullable=False)  # BUY, SELL
    entry_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exit_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    exit_price: Mapped[float] = mapped_column(Float, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    stop_loss: Mapped[float] = mapped_column(Float, nullable=True)
    target_price: Mapped[float] = mapped_column(Float, nullable=True)
    gross_pnl: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    costs: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    slippage: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    net_pnl: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    holding_time_seconds: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    entry_reason: Mapped[str] = mapped_column(Text, nullable=False)
    exit_reason: Mapped[str] = mapped_column(Text, nullable=True)

    experiment: Mapped["Experiment"] = relationship("Experiment", back_populates="trades")
