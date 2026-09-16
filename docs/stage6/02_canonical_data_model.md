# Algo Lab Stage 6 — Canonical Market Data Model

## 1. Overview
The canonical market data model standardizes all point-in-time and replay data across Indian exchanges (NSE, BSE, MCX) and global venues. It enforces Principles 3, 4, 9, and 13:
- **Principle 3:** Bad or uncertain data must not produce a trading decision.
- **Principle 4:** No look-ahead bias.
- **Principle 9:** Every dataset must be versioned.
- **Principle 13:** Data validation must fail closed.

---

## 2. CanonicalMarketDataBar Specification

```python
class CanonicalMarketDataBar(BaseModel):
    timestamp: datetime         # UTC timezone-aware bar opening timestamp
    symbol: str                 # Normalized uppercase instrument ticker
    exchange: str = "NSE"       # Exchange identifier
    timeframe: str = "1d"       # Timeframe (e.g., 1m, 5m, 1h, 1d)

    open: float                 # Opening price (gt=0)
    high: float                 # Period high price (gt=0)
    low: float                  # Period low price (gt=0)
    close: float                # Closing price (gt=0)
    volume: float               # Traded volume in units (ge=0)

    open_interest: Optional[float] = None   # Derivative open interest (ge=0)
    trade_count: Optional[int] = None       # Total discrete trades in bar (ge=0)
    turnover: Optional[float] = None        # Total traded turnover in INR (ge=0)
    vwap: Optional[float] = None            # Volume-Weighted Average Price (gt=0)
    quality_status: DataQualityStatus = DataQualityStatus.VALID
```

---

## 3. Mathematical Consistency Invariants

Every bar undergoes post-instantiation mathematical validation:

1. **Upper Bound Consistency**:
   $$\text{high} \ge \max(\text{open}, \text{close})$$
   If $\text{high} < \max(\text{open}, \text{close})$, a `ValidationError` is raised immediately.

2. **Lower Bound Consistency**:
   $$\text{low} \le \min(\text{open}, \text{close})$$
   If $\text{low} > \min(\text{open}, \text{close})$, a `ValidationError` is raised immediately.

3. **High/Low Spread Invariant**:
   $$\text{high} \ge \text{low}$$
   Negative ranges are rejected.

4. **Numerical Sanity**:
   Prices and volumes cannot be `NaN`, `+Inf`, or `-Inf`. Any presence of non-finite floats fails closed.

---

## 4. CanonicalMarketDataValidator (Batch Engine)

The batch validator processes entire bar sequences and ensures:
- **Zero Duplicates**: No identical `(symbol, exchange, timeframe, timestamp)` entries.
- **Strict Chronological Ordering**: $t_{i} > t_{i-1}$ per instrument partition.
- **Quarantine Reporting**: Identifies corrupted or drifting records and assigns them to a quarantine list for audit investigation.
