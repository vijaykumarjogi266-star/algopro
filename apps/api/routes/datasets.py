"""Algo Lab Dataset Registry API Endpoints (Stage 6).

Adheres to Non-Negotiable Principles:
- Principle 3: Bad or uncertain data must not produce a trading decision.
- Principle 9: Every dataset must be versioned.
- Principle 13: Data validation must fail closed.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from data.schemas.canonical_market_data import CanonicalMarketDataBar
from services.market_data.registry import (
    DatasetRecord,
    DatasetRegistryStore,
    DatasetDriftError,
    DatasetIntegrityError,
    DatasetNotFoundError,
    compute_dataset_checksum,
)

router = APIRouter(prefix="/datasets", tags=["Dataset Registry"])

# Module-level registry store
registry_store = DatasetRegistryStore()


class RegisterDatasetRequest(BaseModel):
    dataset_id: str
    name: str
    version: str = "v1.0.0"
    exchange: str = "NSE"
    asset_class: str = "EQUITY"
    timeframe: str = "1d"
    symbols: List[str]
    start_date: Any
    end_date: Any
    bar_count: int
    sha256_checksum: str
    metadata: Dict[str, Any] = {}


class VerifyDatasetRequest(BaseModel):
    bars: List[CanonicalMarketDataBar]


class QuarantineDatasetRequest(BaseModel):
    reason: str


@router.get("", response_model=List[DatasetRecord], summary="List all registered datasets")
async def list_datasets() -> List[DatasetRecord]:
    """Returns all registered datasets with versions and checksums."""
    return registry_store.list_datasets()


@router.post("/register", response_model=DatasetRecord, status_code=status.HTTP_201_CREATED, summary="Register a versioned dataset")
async def register_dataset(req: RegisterDatasetRequest) -> DatasetRecord:
    """Registers a dataset partition with cryptographic SHA-256 checksum."""
    record = DatasetRecord(
        dataset_id=req.dataset_id,
        name=req.name,
        version=req.version,
        exchange=req.exchange,
        asset_class=req.asset_class,
        timeframe=req.timeframe,
        symbols=[s.upper() for s in req.symbols],
        start_date=req.start_date,
        end_date=req.end_date,
        bar_count=req.bar_count,
        sha256_checksum=req.sha256_checksum,
        metadata=req.metadata,
    )
    return registry_store.register_dataset(record)


@router.get("/{dataset_id}", response_model=DatasetRecord, summary="Get dataset metadata")
async def get_dataset(dataset_id: str) -> DatasetRecord:
    """Retrieves dataset manifest by ID."""
    record = registry_store.get_dataset(dataset_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Dataset '{dataset_id}' not found")
    return record


@router.post("/{dataset_id}/verify", summary="Verify dataset cryptographic integrity (drift detection)")
async def verify_dataset(dataset_id: str, req: VerifyDatasetRequest):
    """Verifies incoming canonical bars against registered SHA-256 hash. Fails closed on drift."""
    try:
        registry_store.verify_dataset_integrity(dataset_id, req.bars, fail_closed=True)
        return {
            "dataset_id": dataset_id,
            "status": "VERIFIED",
            "message": "Dataset integrity verified. Zero drift detected.",
            "sha256_checksum": compute_dataset_checksum(req.bars),
            "bars_count": len(req.bars),
        }
    except DatasetNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except (DatasetDriftError, DatasetIntegrityError) as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.post("/{dataset_id}/quarantine", response_model=DatasetRecord, summary="Quarantine corrupted dataset")
async def quarantine_dataset(dataset_id: str, req: QuarantineDatasetRequest) -> DatasetRecord:
    """Quarantines dataset, preventing any future trading decision."""
    try:
        return registry_store.quarantine_dataset(dataset_id, reason=req.reason)
    except DatasetNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
