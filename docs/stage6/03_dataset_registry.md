# Algo Lab Stage 6 — Dataset Registry & Cryptographic Validation

## 1. Overview
The Dataset Registry provides an immutable catalog of versioned market data partitions and multi-asset universes. Every dataset registered in Algo Lab is cryptographically fingerprinted using SHA-256 to guarantee complete backtest reproducibility (Principle 7 & 9).

---

## 2. DatasetRecord Schema

```python
class DatasetRecord(BaseModel):
    dataset_id: str             # Unique partition identifier
    name: str                   # Human-readable title
    version: str = "v1.0.0"     # Semantic partition version
    exchange: str = "NSE"
    asset_class: str = "EQUITY"
    timeframe: str = "1d"
    symbols: List[str]          # Symbol universe
    start_date: datetime        # Start of coverage (UTC)
    end_date: datetime          # End of coverage (UTC)
    bar_count: int              # Total bar count
    sha256_checksum: str        # 64-char hexadecimal SHA-256 hash
    quality_status: DataQualityStatus
    storage_path: Optional[str]
    metadata: Dict[str, Any]
    created_at: datetime
    updated_at: datetime
```

---

## 3. Cryptographic Checksum Computation

The checksum function sorts all canonical bars deterministically by `(symbol, timestamp)` before hashing. Each bar is converted into an exact text representation:

$$\text{digest} = \text{SHA256}\left(\sum_{i} \text{Symbol}_i \parallel \text{Timestamp}_i \parallel \text{OHLCV}_i \parallel \text{OI}_i \parallel \text{Trades}_i\right)$$

This guarantees invariant hashing regardless of the initial order in which records were ingested from parquet partitions or external feeds.

---

## 4. Fail-Closed Drift Detection

Before any replay or experiment simulation runs against a registered dataset, `DatasetRegistryStore.verify_dataset_integrity()` computes the checksum of the active bar sequence:

- **Matching Checksum**: Data integrity verified, backtest proceeds.
- **Mismatched Checksum**: If any price, volume, trade count, or timestamp differs by even 0.000001, execution fails closed with a `DatasetDriftError`.
- **Quarantined Status**: If a dataset was marked as `CORRUPTED` or `REJECTED`, verification raises `DatasetIntegrityError` to prevent unsafe decisions.
