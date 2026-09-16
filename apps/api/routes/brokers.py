"""Algo Lab Broker & Market Data Connections API Endpoints (Stage 6).

Adheres to Non-Negotiable Principles:
- Security: Raw credentials (API keys, secrets) are NEVER returned in plain text via GET endpoints.
- Safety: LIVE real execution is strictly disabled.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from services.paper_engine.adapters.credentials import (
    BrokerConnectionConfig,
    BrokerCredentialStore,
    ExecutionEnvironment,
    LIVE_TRADING_ENABLED,
)

router = APIRouter(prefix="/brokers", tags=["Broker Connections & Adapters"])

# Shared credential store
credential_store = BrokerCredentialStore()


class SaveConnectionRequest(BaseModel):
    broker_name: str
    environment: ExecutionEnvironment = ExecutionEnvironment.PAPER
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    extra_params: Dict[str, Any] = {}
    is_active: bool = True


@router.get("/connections", response_model=List[Dict[str, Any]], summary="List broker connections (masked credentials)")
async def list_connections() -> List[Dict[str, Any]]:
    """Returns configured broker connections with all secrets strictly masked."""
    return credential_store.list_connections(masked=True)


@router.post("/connections", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED, summary="Create or update broker connection")
async def save_connection(req: SaveConnectionRequest) -> Dict[str, Any]:
    """Saves a broker adapter configuration.
    
    Hard Security Check: Rejects LIVE environment fail-closed.
    """
    if req.environment == ExecutionEnvironment.LIVE or LIVE_TRADING_ENABLED:
        if not LIVE_TRADING_ENABLED:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="LIVE broker execution is strictly prohibited by architectural policy.",
            )

    try:
        config = BrokerConnectionConfig(
            broker_name=req.broker_name,
            environment=req.environment,
            api_key=req.api_key,
            api_secret=req.api_secret,
            extra_params=req.extra_params,
            is_active=req.is_active,
        )
        saved = credential_store.save_connection(config)
        # Always return masked dictionary
        return saved.to_safe_dict()
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.get("/connections/{connection_id}", response_model=Dict[str, Any], summary="Get connection details (masked)")
async def get_connection(connection_id: str) -> Dict[str, Any]:
    """Retrieves connection configuration with all secrets strictly masked."""
    config = credential_store.get_connection(connection_id)
    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Connection '{connection_id}' not found")
    return config.to_safe_dict()


@router.post("/connections/{connection_id}/test", summary="Test broker adapter connection")
async def test_connection(connection_id: str):
    """Executes connectivity test with broker adapter."""
    res = credential_store.test_connection(connection_id)
    if res.get("status") == "NOT_FOUND":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=res["message"])
    return res


@router.delete("/connections/{connection_id}", summary="Delete broker connection")
async def delete_connection(connection_id: str):
    """Deletes connection configuration."""
    deleted = credential_store.delete_connection(connection_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Connection '{connection_id}' not found")
    return {"connection_id": connection_id, "deleted": True}
