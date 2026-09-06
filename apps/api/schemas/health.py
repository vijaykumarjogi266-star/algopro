"""Health and System Status Schemas."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = Field(..., description="Overall service status (healthy, degraded, unhealthy)")
    version: str = Field(..., description="Service version")
    environment: str = Field(..., description="Operating environment")
    timestamp: datetime = Field(..., description="Current system timestamp in UTC")


class ReadinessResponse(BaseModel):
    status: str = Field(..., description="Readiness status (ready, not_ready)")
    version: str = Field(..., description="Service version")
    timestamp: datetime = Field(..., description="Current system timestamp in UTC")
    database: Dict[str, Any] = Field(..., description="Database connectivity status")
    checks: Dict[str, str] = Field(..., description="Individual subsystem readiness states")


class SafetyStatusResponse(BaseModel):
    allow_live_trading: bool
    allow_real_broker_execution: bool
    require_data_validation: bool
    enforce_strict_lookahead_protection: bool
    stage: str
    active_guardrails: List[str]


class SystemInfoResponse(BaseModel):
    name: str
    version: str
    environment: str
    timestamp: datetime
    safety_status: SafetyStatusResponse
    core_principles_count: int
