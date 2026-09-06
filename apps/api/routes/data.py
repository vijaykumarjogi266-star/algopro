"""Market Data and Data Quality API Endpoints."""

from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from data.schemas.contracts import OHLCVBar
from services.market_data.calendar import IndianMarketCalendar
from services.market_data.instruments import Instrument, InstrumentRegistry
from services.data_quality.engine import (
    ComprehensiveDataQualityReport,
    DataQualityEngine,
    DataQualityGateException,
)
from services.market_data.storage import DatasetManifest, ParquetMarketDataStorage

router = APIRouter(prefix="/data", tags=["Market Data & Quality"])

calendar = IndianMarketCalendar()
instruments = InstrumentRegistry()
quality_engine = DataQualityEngine(calendar=calendar, instrument_registry=instruments)
storage = ParquetMarketDataStorage()


class SessionStatusResponse(BaseModel):
    current_time_utc: datetime
    current_time_ist: str
    is_trading_day: bool
    is_regular_trading_session: bool
    session_reason: str


class DataValidationRequest(BaseModel):
    bars: List[OHLCVBar]
    enforce_session_hours: bool = True


@router.get("/session/status", response_model=SessionStatusResponse, summary="Current Indian Market session status")
async def get_session_status() -> SessionStatusResponse:
    """Returns real-time status of Indian market trading session in IST."""
    now_utc = datetime.now(timezone.utc)
    ist_dt = calendar.to_ist(now_utc)
    is_trading_day = calendar.is_trading_day(ist_dt.date())
    is_regular, reason = calendar.is_regular_trading_session(now_utc)

    return SessionStatusResponse(
        current_time_utc=now_utc,
        current_time_ist=ist_dt.strftime("%Y-%m-%d %H:%M:%S IST"),
        is_trading_day=is_trading_day,
        is_regular_trading_session=is_regular,
        session_reason=reason,
    )


@router.get("/instruments", response_model=List[Instrument], summary="List canonical instruments")
async def list_instruments(only_active: bool = False) -> List[Instrument]:
    """Returns instrument master specifications with survivorship metadata."""
    return instruments.list_instruments(only_active=only_active)


@router.post("/validate", response_model=ComprehensiveDataQualityReport, summary="Validate bar sequence across 11 dimensions")
async def validate_bars(req: DataValidationRequest) -> ComprehensiveDataQualityReport:
    """Executes full 11-dimensional data quality verification pipeline."""
    report = quality_engine.validate_dataset(
        bars=req.bars,
        enforce_session_hours=req.enforce_session_hours,
    )
    return report
