"""System status and safety guardrails endpoints."""

from datetime import datetime, timezone
from typing import List
from fastapi import APIRouter
from apps.api.core.config import settings
from apps.api.schemas.health import SafetyStatusResponse, SystemInfoResponse

router = APIRouter(prefix="/system", tags=["System"])

NON_NEGOTIABLE_PRINCIPLES: List[str] = [
    "1. Never force a trade.",
    "2. WAIT is a valid decision.",
    "3. Bad or uncertain data must not produce a trading decision.",
    "4. No look-ahead bias.",
    "5. No data leakage.",
    "6. No survivorship bias where applicable.",
    "7. Every backtest must be reproducible.",
    "8. Every strategy must be versioned.",
    "9. Every dataset must be versioned.",
    "10. Every experiment must be auditable.",
    "11. Indicators are evidence, not automatic trading decisions.",
    "12. RSI must never independently generate BUY/SELL decisions.",
    "13. Multiple correlated indicators must not be treated as independent evidence.",
    "14. Risk Engine must remain independent from Strategy/Alpha.",
    "15. AI must never override hard risk controls.",
    "16. AI must never silently modify production strategies.",
    "17. AI must never directly control unrestricted order execution.",
    "18. All trading decisions must be explainable through evidence.",
    "19. Performance must be evaluated after realistic costs and slippage.",
    "20. Optimize for robustness, not maximum historical return.",
    "21. Evaluate portfolio-level risk, not only individual trades.",
    "22. Record rejected trades, WAIT decisions and missed opportunities.",
    "23. Simple UI; sophisticated engineering underneath.",
    "24. Reliability is more important than feature count.",
    "25. No live capital deployment during the initial development stages.",
]


@router.get("/info", response_model=SystemInfoResponse, summary="Get system status and safety locks")
async def get_system_info() -> SystemInfoResponse:
    return SystemInfoResponse(
        name=settings.PROJECT_NAME,
        version=settings.PROJECT_VERSION,
        environment=settings.ENVIRONMENT,
        timestamp=datetime.now(timezone.utc),
        safety_status=SafetyStatusResponse(
            allow_live_trading=settings.ALLOW_LIVE_TRADING,
            allow_real_broker_execution=settings.ALLOW_REAL_BROKER_EXECUTION,
            require_data_validation=settings.REQUIRE_DATA_VALIDATION,
            enforce_strict_lookahead_protection=settings.ENFORCE_STRICT_LOOKAHEAD_PROTECTION,
            stage="Stage 1: Foundation",
            active_guardrails=[
                "HARD_LOCK: Live Trading Disabled",
                "HARD_LOCK: Real Broker Execution Disabled",
                "MANDATORY: Data Quality Verification",
                "MANDATORY: Strict Look-ahead Protection",
                "AUDIT: Full Decision & Rejection Logging",
            ],
        ),
        core_principles_count=len(NON_NEGOTIABLE_PRINCIPLES),
    )


@router.get("/principles", response_model=List[str], summary="List 25 non-negotiable quantitative principles")
async def get_principles() -> List[str]:
    """Returns the immutable 25 principles governing all Algo Lab research and engines."""
    return NON_NEGOTIABLE_PRINCIPLES
