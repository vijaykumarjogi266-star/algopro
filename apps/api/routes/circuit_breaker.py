"""Algo Lab Circuit Breaker Administrative Control Route."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from apps.api.core.auth import Role, require_administrator
from services.execution_gateway.circuit_breaker import CircuitBreakerEngine, GatewayState

router = APIRouter(prefix="/circuit-breaker", tags=["Circuit Breaker Administration"])

_circuit_breaker: CircuitBreakerEngine = CircuitBreakerEngine()


def get_circuit_breaker() -> CircuitBreakerEngine:
    return _circuit_breaker


def set_circuit_breaker(cb: CircuitBreakerEngine) -> None:
    global _circuit_breaker
    _circuit_breaker = cb


class RearmRequest(BaseModel):
    rearm_token: str


class RearmResponse(BaseModel):
    status: str
    message: str


@router.post(
    "/rearm",
    response_model=RearmResponse,
    summary="Administrative rearm of emergency halted circuit breaker",
)
def rearm_circuit_breaker(
    req: RearmRequest,
    cb: CircuitBreakerEngine = Depends(get_circuit_breaker),
    _role: Role = Depends(require_administrator),
) -> RearmResponse:
    """Restores the circuit breaker from EMERGENCY_HALT to NORMAL.
    
    Security:
    - Requires authenticated administrator role.
    - Requires valid rearm token verified with constant-time cryptographic hash.
    - Never logs submitted tokens.
    """
    success = cb.admin_rearm(req.rearm_token)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Circuit breaker rearm rejected: invalid token or rearm configuration missing.",
        )

    return RearmResponse(
        status="NORMAL",
        message="Circuit breaker successfully restored to NORMAL.",
    )


@router.get("/status", summary="Get circuit breaker runtime status")
def get_circuit_breaker_status(
    cb: CircuitBreakerEngine = Depends(get_circuit_breaker),
):
    """Returns runtime health and state of the circuit breaker."""
    return {
        "gateway_state": cb.state.value,
        "trip_reasons": cb.trip_reasons,
        "is_halted": cb.state == GatewayState.EMERGENCY_HALT,
    }
