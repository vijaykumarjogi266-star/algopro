"""Algo Lab Paper Trading REST API Endpoints (Stage 6).

Adheres to Non-Negotiable Principles:
- Principle 13: Fail closed.
- Principle 14: Risk Engine must remain independent from Strategy/Alpha.
- Principle 25: Paper trading must remain completely separate from real-money broker execution.
  LIVE real broker execution is hard-disabled.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from services.backtest_engine.contracts import OrderSide
from services.paper_engine.session import (
    PaperTradingEngine,
    PaperSession,
    SessionStatus,
)
from services.paper_engine.adapters.credentials import ExecutionEnvironment, LIVE_TRADING_ENABLED

router = APIRouter(prefix="/paper-trading", tags=["Paper Trading Engine"])

# Global shared paper trading engine instance
paper_engine = PaperTradingEngine()


class CreatePaperSessionRequest(BaseModel):
    name: str
    strategy_id: str
    strategy_version: str = "1.0.0"
    universe: List[str]
    initial_capital: float = 1_000_000.0
    broker_connection_id: Optional[str] = None
    environment: ExecutionEnvironment = ExecutionEnvironment.PAPER


class SubmitPaperOrderRequest(BaseModel):
    symbol: str
    side: OrderSide
    quantity: int = Field(gt=0)
    price: float = Field(gt=0.0)
    stop_loss: Optional[float] = None
    target_price: Optional[float] = None


@router.post("/sessions", response_model=PaperSession, status_code=status.HTTP_201_CREATED, summary="Create paper trading session")
async def create_paper_session(req: CreatePaperSessionRequest) -> PaperSession:
    """Creates a new isolated paper trading session.
    
    Hard Security Rule: Rejects LIVE execution environment fail-closed.
    """
    if req.environment == ExecutionEnvironment.LIVE or LIVE_TRADING_ENABLED:
        if not LIVE_TRADING_ENABLED:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="LIVE trading is strictly prohibited by architectural safety policy (LIVE_TRADING_ENABLED = False).",
            )

    try:
        session = paper_engine.create_session(
            name=req.name,
            strategy_id=req.strategy_id,
            strategy_version=req.strategy_version,
            universe=req.universe,
            initial_capital=req.initial_capital,
            broker_connection_id=req.broker_connection_id,
            environment=req.environment,
        )
        return session
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.get("/sessions", response_model=List[PaperSession], summary="List all paper trading sessions")
async def list_paper_sessions() -> List[PaperSession]:
    """Lists all paper trading sessions with real-time portfolio values."""
    return paper_engine.list_sessions()


@router.get("/sessions/{session_id}", response_model=PaperSession, summary="Get paper session detail & portfolio")
async def get_paper_session(session_id: str) -> PaperSession:
    """Retrieves session state, active positions, cash balance, and execution history."""
    session = paper_engine.get_session(session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Session '{session_id}' not found")
    return session


@router.post("/sessions/{session_id}/start", response_model=PaperSession, summary="Start paper trading session")
async def start_session(session_id: str) -> PaperSession:
    """Transitions session to RUNNING state."""
    try:
        return paper_engine.start_session(session_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/sessions/{session_id}/pause", response_model=PaperSession, summary="Pause paper trading session")
async def pause_session(session_id: str) -> PaperSession:
    """Transitions session to PAUSED state."""
    try:
        return paper_engine.pause_session(session_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/sessions/{session_id}/stop", response_model=PaperSession, summary="Stop paper trading session")
async def stop_session(session_id: str) -> PaperSession:
    """Transitions session to STOPPED state."""
    try:
        return paper_engine.stop_session(session_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/sessions/{session_id}/orders", summary="Submit risk-gated paper order")
async def submit_paper_order(session_id: str, req: SubmitPaperOrderRequest):
    """Proposes an order, verifies against the independent Risk Engine, and executes paper fill."""
    try:
        order, fill = paper_engine.submit_manual_order(
            session_id=session_id,
            symbol=req.symbol,
            side=req.side,
            quantity=req.quantity,
            price=req.price,
            stop_loss=req.stop_loss,
            target_price=req.target_price,
        )
        return {
            "session_id": session_id,
            "order": order.model_dump(),
            "fill": fill.model_dump() if fill else None,
            "status": order.state.value,
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
