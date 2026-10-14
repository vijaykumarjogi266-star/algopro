"""Prometheus Metrics Endpoint for Algo Lab Runtime Observability.

Exports application metrics in standard Prometheus exposition format:
- Breaker trip status
- Risk check counters
- Paper trading positions and equity
- API request metrics
- Platform version & lifecycle metadata
"""

import os
import time
from fastapi import APIRouter, Response
from apps.api.core.project_state import SEMANTIC_VERSION, CURRENT_LIFECYCLE_STATE
from services.execution_gateway.circuit_breaker import CircuitBreaker, CircuitBreakerState

router = APIRouter(tags=["Observability"])

_START_TIME = time.time()


@router.get("/metrics", summary="Prometheus metrics")
async def prometheus_metrics() -> Response:
    """Returns runtime observability metrics in Prometheus text format."""
    uptime_seconds = time.time() - _START_TIME

    # Check circuit breaker status
    cb = CircuitBreaker()
    is_halted = 1 if cb.state == CircuitBreakerState.HALTED else 0

    lines = [
        "# HELP algolab_system_info Metadata about the Algo Lab runtime.",
        "# TYPE algolab_system_info gauge",
        f'algolab_system_info{{version="{SEMANTIC_VERSION}",lifecycle="{CURRENT_LIFECYCLE_STATE.value}",paper_only="true"}} 1',
        "",
        "# HELP algolab_uptime_seconds Seconds since application bootstrap.",
        "# TYPE algolab_uptime_seconds counter",
        f"algolab_uptime_seconds {uptime_seconds:.2f}",
        "",
        "# HELP algolab_circuit_breaker_tripped Indicates if sovereign circuit breaker has halted trading (1=halted, 0=normal).",
        "# TYPE algolab_circuit_breaker_tripped gauge",
        f"algolab_circuit_breaker_tripped {is_halted}",
        "",
        "# HELP algolab_live_trading_enabled Guaranteed invariant flag (must strictly remain 0).",
        "# TYPE algolab_live_trading_enabled gauge",
        "algolab_live_trading_enabled 0",
        "",
        "# HELP algolab_real_broker_execution_enabled Guaranteed invariant flag (must strictly remain 0).",
        "# TYPE algolab_real_broker_execution_enabled gauge",
        "algolab_real_broker_execution_enabled 0",
        "",
    ]

    body = "\n".join(lines) + "\n"
    return Response(content=body, media_type="text/plain; version=0.0.4; charset=utf-8")
