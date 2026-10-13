"""Algo Lab Paper Trading Engine & Session Management (Stage 6).

Adheres to Non-Negotiable Principles:
- Principle 13: Data validation must fail closed.
- Principle 14: Risk Engine must remain independent from Strategy/Alpha.
- Principle 15: AI must never override hard risk controls.
- Principle 19: Performance must be evaluated after realistic costs and slippage.
- Principle 25: Paper trading must remain completely separate from real-money broker execution.
  LIVE trading execution is hard-disabled.
"""

from datetime import datetime, timezone
from enum import Enum
import json
import sqlite3
import threading
from typing import Any, Dict, List, Optional, Tuple
import uuid
from pydantic import BaseModel, Field

from data.schemas.canonical_market_data import CanonicalMarketDataBar
from services.backtest_engine.contracts import OrderSide, OrderType
from services.backtest_engine.execution_lifecycle import (
    ExecutionLifecycleManager,
    ExecutionOrder,
    ExecutionFill,
    OrderLifecycleState,
)
from services.paper_engine.adapters.credentials import (
    ExecutionEnvironment,
    LIVE_TRADING_ENABLED,
)
from services.paper_engine.adapters.base import (
    PaperExecutionProvider,
    SimulatedBrokerAdapter,
)
from services.execution_gateway.circuit_breaker import CircuitBreakerEngine
from services.execution_gateway.contracts import (
    CircuitBreakerTripped,
    OrderPayload,
    RateLimitExceededError,
)
from apps.api.core.logging import get_logger

logger = get_logger(__name__)


class SessionStatus(str, Enum):
    CREATED = "CREATED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class PositionDetail(BaseModel):
    """Detailed position tracking for a paper trading portfolio."""

    symbol: str
    side: OrderSide = OrderSide.BUY
    quantity: int = Field(ge=0)
    average_entry_price: float = Field(gt=0.0)
    current_price: float = Field(gt=0.0)
    cost_basis: float = Field(ge=0.0)
    market_value: float = Field(ge=0.0)
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    fees_paid: float = 0.0
    slippage_paid: float = 0.0
    opened_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def mark_to_market(self, price: float):
        self.current_price = price
        self.market_value = self.quantity * price
        if self.side == OrderSide.BUY:
            self.unrealized_pnl = (price - self.average_entry_price) * self.quantity
        else:
            self.unrealized_pnl = (self.average_entry_price - price) * self.quantity
        self.updated_at = datetime.now(timezone.utc)


class PaperPortfolio(BaseModel):
    """Encapsulates cash, active positions, realized/unrealized P&L and financial accounting invariants."""

    initial_capital: float = Field(gt=0.0)
    cash: float = Field(ge=0.0)
    positions: Dict[str, PositionDetail] = Field(default_factory=dict)
    total_realized_pnl: float = 0.0
    total_unrealized_pnl: float = 0.0
    total_fees_paid: float = 0.0
    total_slippage_paid: float = 0.0
    peak_equity: float = Field(gt=0.0)
    max_drawdown_pct: float = 0.0
    day_start_equity: float = 0.0
    daily_pnl: float = 0.0
    cumulative_pnl: float = 0.0
    high_water_mark: float = 0.0
    lifetime_trades: int = 0

    @classmethod
    def initialize(cls, capital: float) -> "PaperPortfolio":
        return cls(
            initial_capital=capital,
            cash=capital,
            peak_equity=capital,
            high_water_mark=capital,
            day_start_equity=capital,
            daily_pnl=0.0,
            cumulative_pnl=0.0,
            lifetime_trades=0,
        )

    @property
    def market_value_of_positions(self) -> float:
        return sum(pos.market_value for pos in self.positions.values())

    @property
    def total_equity(self) -> float:
        """Cash + Open Positions Value."""
        return round(self.cash + self.market_value_of_positions, 4)

    def reset_daily_metrics(self, session_open_equity: Optional[float] = None):
        """Resets daily-scoped metrics at session open boundary, while preserving lifetime metrics."""
        eq = session_open_equity if session_open_equity is not None else self.total_equity
        self.day_start_equity = eq
        self.daily_pnl = 0.0

    def _update_pnl_and_hwm(self):
        current_eq = self.total_equity
        if self.high_water_mark <= 0.0 and self.peak_equity > 0.0:
            self.high_water_mark = self.peak_equity
        if current_eq > self.high_water_mark:
            self.high_water_mark = current_eq
        if current_eq > self.peak_equity:
            self.peak_equity = current_eq

        if self.high_water_mark > 0:
            dd = (self.high_water_mark - current_eq) / self.high_water_mark
            if dd > self.max_drawdown_pct:
                self.max_drawdown_pct = round(dd, 4)

        self.cumulative_pnl = round(current_eq - self.initial_capital, 4)
        if self.day_start_equity > 0:
            self.daily_pnl = round(current_eq - self.day_start_equity, 4)
        else:
            self.daily_pnl = round(current_eq - self.initial_capital, 4)

    def mark_to_market(self, prices: Dict[str, float]):
        """Updates prices and marks all active positions to market."""
        total_unrealized = 0.0
        for sym, pos in list(self.positions.items()):
            if sym in prices and pos.quantity > 0:
                pos.mark_to_market(prices[sym])
                total_unrealized += pos.unrealized_pnl

        self.total_unrealized_pnl = round(total_unrealized, 4)
        self._update_pnl_and_hwm()

    def on_fill(self, fill: ExecutionFill):
        """Applies an execution fill to the portfolio maintaining financial accounting invariants.
        
        Slippage arithmetic:
        - Deducted once on cash flow (cash outflow = quantity * base_price + transaction_costs + slippage_cost).
        - Not double-counted inside position cost basis (cost basis = quantity * base_price).
        """
        sym = fill.symbol.upper()
        self.total_fees_paid = round(self.total_fees_paid + fill.transaction_costs, 4)
        self.total_slippage_paid = round(self.total_slippage_paid + fill.slippage_cost, 4)
        self.lifetime_trades += 1

        base_price = getattr(fill, "base_price", fill.fill_price)

        if fill.side == OrderSide.BUY:
            total_outflow = round((fill.quantity * base_price) + fill.transaction_costs + fill.slippage_cost, 4)
            if self.cash < total_outflow:
                raise ValueError(
                    f"Defensive cash invariant violation: Available cash INR {self.cash:.2f} "
                    f"is insufficient for required outflow INR {total_outflow:.2f}"
                )
            self.cash = round(self.cash - total_outflow, 4)

            pos = self.positions.get(sym)
            if pos is None or pos.quantity == 0:
                self.positions[sym] = PositionDetail(
                    symbol=sym,
                    side=OrderSide.BUY,
                    quantity=fill.quantity,
                    average_entry_price=base_price,
                    current_price=fill.fill_price,
                    cost_basis=round(fill.quantity * base_price, 4),
                    market_value=round(fill.quantity * fill.fill_price, 4),
                    fees_paid=fill.transaction_costs,
                    slippage_paid=fill.slippage_cost,
                )
            else:
                # Average into existing long
                new_qty = pos.quantity + fill.quantity
                new_cost = pos.cost_basis + (fill.quantity * base_price)
                pos.average_entry_price = round(new_cost / new_qty, 4)
                pos.quantity = new_qty
                pos.cost_basis = round(new_cost, 4)
                pos.market_value = round(new_qty * fill.fill_price, 4)
                pos.current_price = fill.fill_price
                pos.fees_paid = round(pos.fees_paid + fill.transaction_costs, 4)
                pos.slippage_paid = round(pos.slippage_paid + fill.slippage_cost, 4)
        else:
            # SELL side (closing or reducing long)
            pos = self.positions.get(sym)
            if pos is not None and pos.quantity > 0:
                closed_qty = min(pos.quantity, fill.quantity)
                cost_of_closed = closed_qty * pos.average_entry_price
                proceeds = closed_qty * base_price
                realized_gross = proceeds - cost_of_closed
                self.total_realized_pnl = round(self.total_realized_pnl + realized_gross, 4)

                net_inflow = (fill.quantity * base_price) - fill.slippage_cost - fill.transaction_costs
                self.cash = round(self.cash + net_inflow, 4)

                rem_qty = pos.quantity - closed_qty
                if rem_qty == 0:
                    del self.positions[sym]
                else:
                    pos.quantity = rem_qty
                    pos.cost_basis = round(rem_qty * pos.average_entry_price, 4)
                    pos.market_value = round(rem_qty * fill.fill_price, 4)
                    pos.current_price = fill.fill_price
            else:
                # Zero existing position, receive proceeds
                net_inflow = (fill.quantity * base_price) - fill.slippage_cost - fill.transaction_costs
                self.cash = round(self.cash + net_inflow, 4)

        self._update_pnl_and_hwm()


class PaperSession(BaseModel):
    """A managed paper trading session instance."""

    session_id: str = Field(default_factory=lambda: f"sess_{uuid.uuid4().hex[:12]}")
    name: str
    strategy_id: str
    strategy_version: str = "1.0.0"
    universe: List[str]
    initial_capital: float = 1_000_000.0
    portfolio: PaperPortfolio
    status: SessionStatus = SessionStatus.CREATED
    broker_connection_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None
    events_count: int = 0
    orders: List[ExecutionOrder] = Field(default_factory=list)
    fills: List[ExecutionFill] = Field(default_factory=list)
    error_message: Optional[str] = None

    @property
    def ledger_entries(self) -> List[ExecutionFill]:
        """Immutable historical ledger of executed fills."""
        return list(self.fills)


class PaperTradingEngine:
    """Thread-safe orchestration engine for real-time paper trading sessions."""

    def __init__(
        self,
        db_path: str = ":memory:",
        lifecycle_manager: Optional[ExecutionLifecycleManager] = None,
        broker_adapter: Optional[PaperExecutionProvider] = None,
        circuit_breaker: Optional[CircuitBreakerEngine] = None,
    ):
        self.db_path = db_path
        self._lock = threading.RLock()
        if db_path == ":memory:":
            self._persistent_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._persistent_conn.row_factory = sqlite3.Row
            self._persistent_conn.execute("PRAGMA foreign_keys = ON")
        else:
            self._persistent_conn = None

        self.lifecycle_manager = lifecycle_manager or ExecutionLifecycleManager()
        self.broker_adapter = broker_adapter or SimulatedBrokerAdapter()
        self.circuit_breaker = circuit_breaker
        self._sessions: Dict[str, PaperSession] = {}
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if self._persistent_conn is not None:
            return self._persistent_conn
        conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        if self.db_path != ":memory:":
            try:
                conn.execute("PRAGMA journal_mode = WAL")
                conn.execute("PRAGMA synchronous = NORMAL")
            except Exception:
                pass
        conn.execute("PRAGMA busy_timeout = 10000")
        return conn

    def _init_db(self):
        with self._lock:
            conn = self._get_connection()
            if self.db_path != ":memory:":
                try:
                    conn.execute("PRAGMA journal_mode = WAL")
                    conn.execute("PRAGMA synchronous = NORMAL")
                except Exception:
                    pass
            with conn:
                conn.execute("""
                CREATE TABLE IF NOT EXISTS paper_sessions (
                    session_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    strategy_id TEXT NOT NULL,
                    strategy_version TEXT NOT NULL,
                    universe TEXT NOT NULL,
                    initial_capital REAL NOT NULL,
                    status TEXT NOT NULL,
                    broker_connection_id TEXT,
                    portfolio_data TEXT NOT NULL,
                    events_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    stopped_at TEXT,
                    error_message TEXT,
                    orders_data TEXT,
                    fills_data TEXT
                )
                """)
                cursor = conn.execute("PRAGMA table_info(paper_sessions)")
                cols = [r[1] for r in cursor.fetchall()]
                if "orders_data" not in cols:
                    conn.execute("ALTER TABLE paper_sessions ADD COLUMN orders_data TEXT")
                if "fills_data" not in cols:
                    conn.execute("ALTER TABLE paper_sessions ADD COLUMN fills_data TEXT")


    def create_session(
        self,
        name: str,
        strategy_id: str,
        universe: List[str],
        initial_capital: float = 1_000_000.0,
        strategy_version: str = "1.0.0",
        broker_connection_id: Optional[str] = None,
        environment: ExecutionEnvironment = ExecutionEnvironment.PAPER,
    ) -> PaperSession:
        """Creates a new paper trading session.
        
        Fail-Closed Safety Guard: Rejects LIVE environment unconditionally.
        """
        if environment == ExecutionEnvironment.LIVE or LIVE_TRADING_ENABLED:
            if not LIVE_TRADING_ENABLED:
                raise PermissionError("LIVE trading session creation is strictly prohibited.")

        if initial_capital <= 0:
            raise ValueError("initial_capital must be positive.")
        if not universe:
            raise ValueError("universe cannot be empty.")

        portfolio = PaperPortfolio.initialize(initial_capital)
        session = PaperSession(
            name=name,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            universe=[s.upper() for s in universe],
            initial_capital=initial_capital,
            portfolio=portfolio,
            status=SessionStatus.CREATED,
            broker_connection_id=broker_connection_id,
        )

        with self._lock:
            self._sessions[session.session_id] = session
            self._persist_session(session)

        return session

    def start_session(self, session_id: str) -> PaperSession:
        with self._lock:
            session = self.get_session(session_id)
            if not session:
                raise ValueError(f"Session {session_id} not found.")
            session.status = SessionStatus.RUNNING
            session.started_at = datetime.now(timezone.utc)
            self._persist_session(session)
            return session

    def pause_session(self, session_id: str) -> PaperSession:
        with self._lock:
            session = self.get_session(session_id)
            if not session:
                raise ValueError(f"Session {session_id} not found.")
            session.status = SessionStatus.PAUSED
            self._persist_session(session)
            return session

    def stop_session(self, session_id: str) -> PaperSession:
        with self._lock:
            session = self.get_session(session_id)
            if not session:
                raise ValueError(f"Session {session_id} not found.")
            session.status = SessionStatus.STOPPED
            session.stopped_at = datetime.now(timezone.utc)
            self._persist_session(session)
            return session

    def get_session(self, session_id: str) -> Optional[PaperSession]:
        with self._lock:
            if session_id in self._sessions:
                return self._sessions[session_id]
            conn = self._get_connection()
            cursor = conn.execute("SELECT * FROM paper_sessions WHERE session_id = ?", (session_id,))
            row = cursor.fetchone()
            if not row:
                return None
            session = self._row_to_session(row)
            self._sessions[session_id] = session
            return session

    def list_sessions(self) -> List[PaperSession]:
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute("SELECT * FROM paper_sessions ORDER BY created_at DESC")
            return [self._row_to_session(r) for r in cursor.fetchall()]

    def list_orders(self, session_id: str) -> List[ExecutionOrder]:
        """Return all execution orders for the given session."""
        session = self.get_session(session_id)
        return list(session.orders) if session else []

    def reset_daily_metrics(
        self, session_id: str, session_open_equity: Optional[float] = None
    ) -> PaperSession:
        """Reset daily PnL and daily baseline at session open boundary."""
        with self._lock:
            session = self.get_session(session_id)
            if not session:
                raise ValueError(f"Session {session_id} not found.")
            session.portfolio.reset_daily_metrics(session_open_equity)
            self._persist_session(session)
            return session

    def submit_manual_order(
        self,
        session_id: str,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: float,
        stop_loss: Optional[float] = None,
        target_price: Optional[float] = None,
    ) -> Tuple[ExecutionOrder, Optional[ExecutionFill]]:
        """Proposes, risk-evaluates, and executes an order in the session portfolio.
        
        Zero portfolio mutation occurs if risk evaluation rejects the order.
        """
        with self._lock:
            session = self.get_session(session_id)
            if not session:
                raise ValueError(f"Session {session_id} not found.")

            if session.status != SessionStatus.RUNNING:
                raise ValueError(f"Cannot submit order to session in state {session.status}")

            # 1. Validate against Execution Gateway Circuit Breaker if attached
            if self.circuit_breaker is not None:
                payload = OrderPayload(
                    order_id=f"ord_{uuid.uuid4().hex[:8]}",
                    account_id=session.broker_connection_id or session.session_id,
                    symbol=symbol,
                    quantity=quantity if side == OrderSide.BUY else -quantity,
                    price=price,
                    timestamp=datetime.now(timezone.utc),
                    strategy_id=session.strategy_id,
                )
                self.circuit_breaker.validate_order(payload)

            # 2. Propose order
            order = self.lifecycle_manager.propose_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=price,
                stop_loss=stop_loss,
                target_price=target_price,
            )

            # 3. Risk check against session portfolio metrics & cash solvency
            evaluated = self.lifecycle_manager.evaluate_risk(
                order,
                current_portfolio_value=session.portfolio.total_equity,
                current_daily_loss_pct=0.0,
                current_drawdown_pct=session.portfolio.max_drawdown_pct,
                current_open_positions_count=len(session.portfolio.positions),
                available_cash=session.portfolio.cash,
            )

            session.orders.append(evaluated)

            # 4. If rejected, ZERO mutation occurs
            if evaluated.state == OrderLifecycleState.ORDER_REJECTED:
                self._persist_session(session)
                return evaluated, None

            # 5. Fill via adapter
            filled_order, fill = self.broker_adapter.submit_paper_order(evaluated, execution_price=price)
            session.fills.append(fill)

            # 6. Mutate portfolio with fill
            session.portfolio.on_fill(fill)
            if self.circuit_breaker is not None:
                self.circuit_breaker.update_equity(session.portfolio.total_equity)
            self._persist_session(session)

            return filled_order, fill

    def process_bar(self, session_id: str, bar: CanonicalMarketDataBar):
        """Processes incoming market data bar and updates marked-to-market positions."""
        with self._lock:
            session = self.get_session(session_id)
            if not session or session.status != SessionStatus.RUNNING:
                return

            session.events_count += 1
            session.portfolio.mark_to_market({bar.symbol: bar.close})
            self._persist_session(session)

    def _persist_session(self, session: PaperSession):
        conn = self._get_connection()
        orders_json = json.dumps([o.model_dump(mode="json") for o in session.orders])
        fills_json = json.dumps([f.model_dump(mode="json") for f in session.fills])
        with conn:
            conn.execute("""
            INSERT INTO paper_sessions (
                session_id, name, strategy_id, strategy_version, universe,
                initial_capital, status, broker_connection_id, portfolio_data,
                events_count, created_at, started_at, stopped_at, error_message,
                orders_data, fills_data
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                status = excluded.status,
                portfolio_data = excluded.portfolio_data,
                events_count = excluded.events_count,
                started_at = excluded.started_at,
                stopped_at = excluded.stopped_at,
                error_message = excluded.error_message,
                orders_data = excluded.orders_data,
                fills_data = excluded.fills_data
            """, (
                session.session_id,
                session.name,
                session.strategy_id,
                session.strategy_version,
                json.dumps(session.universe),
                session.initial_capital,
                session.status.value,
                session.broker_connection_id,
                session.portfolio.model_dump_json(),
                session.events_count,
                session.created_at.isoformat(),
                session.started_at.isoformat() if session.started_at else None,
                session.stopped_at.isoformat() if session.stopped_at else None,
                session.error_message,
                orders_json,
                fills_json,
            ))

    def _row_to_session(self, row: sqlite3.Row) -> PaperSession:
        keys = row.keys()
        orders = []
        if "orders_data" in keys and row["orders_data"]:
            try:
                orders = [ExecutionOrder.model_validate(o) for o in json.loads(row["orders_data"])]
            except Exception:
                orders = []
        fills = []
        if "fills_data" in keys and row["fills_data"]:
            try:
                fills = [ExecutionFill.model_validate(f) for f in json.loads(row["fills_data"])]
            except Exception:
                fills = []

        return PaperSession(
            session_id=row["session_id"],
            name=row["name"],
            strategy_id=row["strategy_id"],
            strategy_version=row["strategy_version"],
            universe=json.loads(row["universe"]),
            initial_capital=row["initial_capital"],
            portfolio=PaperPortfolio.model_validate_json(row["portfolio_data"]),
            status=SessionStatus(row["status"]),
            broker_connection_id=row["broker_connection_id"],
            events_count=row["events_count"],
            orders=orders,
            fills=fills,
            created_at=datetime.fromisoformat(row["created_at"]),
            started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
            stopped_at=datetime.fromisoformat(row["stopped_at"]) if row["stopped_at"] else None,
            error_message=row["error_message"],
        )

