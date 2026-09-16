"""Algo Lab Experiment Management API Routes.

Exposes REST endpoints for:
- Experiment validation (dry-run)
- Experiment creation & retrieval
- Experiment execution submission (idempotent)
- Run status and research results
- Immutable audit trail exploration
"""

import json
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from services.backtest_engine.contracts import (
    ExperimentDefinition,
    ExperimentStatus,
)
from services.backtest_engine.service import BacktestService
from apps.api.schemas.experiments import (
    ExperimentCreateRequest,
    ExperimentValidateRequest,
    ExperimentValidationResponse,
    ExperimentResponse,
    ExperimentListResponse,
    RunSubmitResponse,
    RunStatusResponse,
    RunResultResponse,
    AuditEventResponse,
)

router = APIRouter(prefix="/experiments", tags=["experiments"])

# Global / injectable service instance
_service: Optional[BacktestService] = None


def get_service() -> BacktestService:
    global _service
    if _service is None:
        _service = BacktestService()
    return _service


def set_service(service: BacktestService) -> None:
    global _service
    _service = service


# Recognized strategies and datasets
KNOWN_STRATEGIES = {"Canonical_SMA", "ORB", "VWAP_Reversion", "SMA_Cross", "Canonical_BuyAndHold"}
KNOWN_DATASETS = {"NSE_NIFTY50_DAILY", "NSE_NIFTY50_INTRADAY", "NSE_EQUITIES_DAILY"}


def validate_experiment_payload(req: ExperimentCreateRequest) -> ExperimentValidationResponse:
    """Performs deep validation of experiment configuration against governance rules."""
    errors: List[str] = []
    warnings: List[str] = []

    # 1. Strategy check
    if req.strategy_id not in KNOWN_STRATEGIES:
        errors.append(f"Invalid strategy '{req.strategy_id}'. Supported: {sorted(list(KNOWN_STRATEGIES))}")

    # 2. Dataset check
    if req.dataset_id not in KNOWN_DATASETS:
        errors.append(f"Unknown or missing dataset '{req.dataset_id}'. Supported: {sorted(list(KNOWN_DATASETS))}")

    # 3. Checksum sanity (must be 64-char SHA-256)
    if len(req.dataset_checksum) != 64 or not all(c in "0123456789abcdefABCDEF" for c in req.dataset_checksum):
        errors.append("dataset_checksum must be a valid 64-character SHA-256 hexadecimal string")

    # 4. Date range check
    if req.start_date >= req.end_date:
        errors.append(f"start_date ({req.start_date.isoformat()}) must be strictly before end_date ({req.end_date.isoformat()})")

    # 5. Universe validation
    if not req.universe or len(req.universe) == 0:
        errors.append("universe cannot be empty")
    elif any(not isinstance(s, str) or not s.strip() for s in req.universe):
        errors.append("all universe symbols must be non-empty strings")

    # 6. Initial capital
    if req.initial_capital <= 0:
        errors.append("initial_capital must be strictly positive")

    # 7. Parameter integrity
    params = req.parameters or {}
    if "fast_period" in params and "slow_period" in params:
        if params["fast_period"] >= params["slow_period"]:
            errors.append(f"fast_period ({params['fast_period']}) must be strictly less than slow_period ({params['slow_period']})")

    if errors:
        return ExperimentValidationResponse(is_valid=False, errors=errors, warnings=warnings, fingerprint=None)

    # Calculate deterministic fingerprint if valid
    dummy_def = ExperimentDefinition(
        experiment_id="temp_validation_id",
        name=req.name,
        description=req.description or "",
        strategy_id=req.strategy_id,
        strategy_version=req.strategy_version,
        dataset_id=req.dataset_id,
        dataset_version=req.dataset_version,
        dataset_checksum=req.dataset_checksum,
        universe=req.universe,
        timeframe=req.timeframe,
        start_date=req.start_date,
        end_date=req.end_date,
        parameters=params,
        risk_policy_version=req.risk_policy_version,
        cost_model=req.cost_model,
        slippage_model=req.slippage_model,
        initial_capital=req.initial_capital,
        seed=req.seed,
        code_revision=req.code_revision,
    )

    return ExperimentValidationResponse(
        is_valid=True,
        errors=[],
        warnings=warnings,
        fingerprint=dummy_def.fingerprint,
    )


@router.post("/validate", response_model=ExperimentValidationResponse, summary="Validate experiment configuration (dry-run)")
def validate_experiment(req: ExperimentValidateRequest):
    return validate_experiment_payload(req)


@router.post("", response_model=ExperimentResponse, status_code=status.HTTP_201_CREATED, summary="Create experiment definition")
def create_experiment(
    req: ExperimentCreateRequest,
    service: BacktestService = Depends(get_service),
):
    val = validate_experiment_payload(req)
    if not val.is_valid:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"errors": val.errors})

    exp_id = f"exp_{uuid.uuid4().hex[:12]}"
    exp_def = ExperimentDefinition(
        experiment_id=exp_id,
        name=req.name,
        description=req.description or "",
        strategy_id=req.strategy_id,
        strategy_version=req.strategy_version,
        dataset_id=req.dataset_id,
        dataset_version=req.dataset_version,
        dataset_checksum=req.dataset_checksum,
        universe=req.universe,
        timeframe=req.timeframe,
        start_date=req.start_date,
        end_date=req.end_date,
        parameters=req.parameters,
        risk_policy_version=req.risk_policy_version,
        cost_model=req.cost_model,
        slippage_model=req.slippage_model,
        initial_capital=req.initial_capital,
        seed=req.seed,
        code_revision=req.code_revision,
    )

    try:
        service.store.save_experiment(exp_def)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Persistence failure: {str(e)}")

    return exp_def


@router.get("", response_model=ExperimentListResponse, summary="List experiment definitions")
def list_experiments(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: Optional[str] = Query(default=None),
    strategy_id: Optional[str] = Query(default=None),
    service: BacktestService = Depends(get_service),
):
    exps = service.store.list_experiments(limit=limit, offset=offset, status=status, strategy_id=strategy_id)
    return ExperimentListResponse(
        experiments=[ExperimentResponse(**e.model_dump()) for e in exps],
        total=len(exps),
        limit=limit,
        offset=offset,
    )


@router.get("/{experiment_id}", response_model=ExperimentResponse, summary="Get experiment definition")
def get_experiment(
    experiment_id: str,
    service: BacktestService = Depends(get_service),
):
    exp = service.store.get_experiment(experiment_id)
    if not exp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Experiment '{experiment_id}' not found")
    return exp


@router.post("/{experiment_id}/submit", response_model=RunSubmitResponse, summary="Submit experiment for execution")
def submit_experiment(
    experiment_id: str,
    idempotent: bool = Query(default=True, description="Enforce idempotency to prevent duplicate executions"),
    service: BacktestService = Depends(get_service),
):
    exp = service.store.get_experiment(experiment_id)
    if not exp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Experiment '{experiment_id}' not found")

    res = service.submit_experiment(exp, idempotent=idempotent)
    return RunSubmitResponse(**res)


@router.get("/{experiment_id}/runs/{run_id}", response_model=RunStatusResponse, summary="Get backtest run status")
def get_run_status(
    experiment_id: str,
    run_id: str,
    service: BacktestService = Depends(get_service),
):
    run = service.store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Run '{run_id}' not found")

    metrics_dict = json.loads(run["metrics_json"]) if run["metrics_json"] else None
    return RunStatusResponse(
        run_id=run["experiment_id"],
        experiment_id=experiment_id,
        status=run["status"],
        reproducibility_hash=run["reproducibility_hash"],
        metrics=metrics_dict,
        trades_count=run.get("trades_count", 0) or 0,
        rejected_trades_count=run.get("rejected_trades_count", 0) or 0,
        created_at=run["created_at"],
    )


@router.get("/{experiment_id}/runs/{run_id}/results", response_model=RunResultResponse, summary="Get research results")
def get_run_results(
    experiment_id: str,
    run_id: str,
    service: BacktestService = Depends(get_service),
):
    run = service.store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Run '{run_id}' not found")

    metrics_dict = json.loads(run["metrics_json"]) if run["metrics_json"] else None
    repro_dict = json.loads(run["reproducibility_json"]) if run["reproducibility_json"] else None

    return RunResultResponse(
        experiment_id=experiment_id,
        run_id=run_id,
        status=run["status"],
        metrics=metrics_dict,
        reproducibility=repro_dict,
        trades_count=run.get("trades_count", 0) or 0,
        rejected_trades_count=run.get("rejected_trades_count", 0) or 0,
    )


@router.get("/{experiment_id}/runs/{run_id}/audit", response_model=List[AuditEventResponse], summary="Get strictly ordered audit trail")
def get_run_audit_trail(
    experiment_id: str,
    run_id: str,
    service: BacktestService = Depends(get_service),
):
    run = service.store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Run '{run_id}' not found")

    events = service.get_audit_trail(run_id)
    return [AuditEventResponse(**e) for e in events]
