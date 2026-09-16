"""Algo Lab Deterministic Historical Market Replay API Endpoints (Stage 6).

Adheres to Non-Negotiable Principles:
- Principle 4: No look-ahead bias.
- Principle 7: Every backtest must be reproducible.
- Principle 13: Data validation must fail closed.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from data.schemas.canonical_market_data import CanonicalMarketDataBar
from services.backtest_engine.replay import (
    HistoricalReplayEngine,
    ReplayConfig,
    ReplayEvent,
    LookAheadBiasError,
)

router = APIRouter(prefix="/replay", tags=["Historical Market Replay"])

_replay_runs: Dict[str, Dict[str, Any]] = {}


class ReplayRunRequest(BaseModel):
    bars: List[CanonicalMarketDataBar]
    symbols: Optional[List[str]] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    filter_holidays: bool = True
    enforce_session_hours: bool = False


class ReplayRunResponse(BaseModel):
    replay_id: str
    status: str
    total_events: int
    events_processed: int
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    symbols: List[str]
    completed_at: datetime


@router.post("/run", response_model=ReplayRunResponse, summary="Execute deterministic historical replay simulation")
async def run_replay(req: ReplayRunRequest) -> ReplayRunResponse:
    """Executes a deterministic historical market replay with strict look-ahead guard."""
    if not req.bars:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Replay dataset cannot be empty.")

    replay_id = f"rpl_{uuid.uuid4().hex[:10]}"
    symbols = req.symbols or sorted(list({b.symbol for b in req.bars}))

    try:
        cfg = ReplayConfig(
            symbols=symbols,
            start_time=req.start_time,
            end_time=req.end_time,
            filter_holidays=req.filter_holidays,
            enforce_session_hours=req.enforce_session_hours,
        )
        engine = HistoricalReplayEngine(bars=req.bars, config=cfg)
        processed = engine.run()

        run_info = {
            "replay_id": replay_id,
            "status": "COMPLETED",
            "total_events": engine.total_events,
            "events_processed": processed,
            "start_time": req.start_time,
            "end_time": req.end_time,
            "symbols": symbols,
            "completed_at": datetime.now(timezone.utc),
        }
        _replay_runs[replay_id] = run_info
        return ReplayRunResponse(**run_info)

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except LookAheadBiasError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))


@router.get("/status/{replay_id}", response_model=ReplayRunResponse, summary="Get historical replay run status")
async def get_replay_status(replay_id: str) -> ReplayRunResponse:
    """Retrieves status and metadata of completed historical replay simulation."""
    info = _replay_runs.get(replay_id)
    if not info:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Replay run '{replay_id}' not found")
    return ReplayRunResponse(**info)
