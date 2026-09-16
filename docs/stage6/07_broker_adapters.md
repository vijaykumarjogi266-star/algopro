# Algo Lab Stage 6 — Broker & Market Data Adapters

## 1. Overview
Stage 6 establishes standard provider abstraction layers for market data feeds and paper execution venues. This decouples core simulation and research from external broker-specific API schemas.

---

## 2. Abstract Provider Interfaces

### `MarketDataProvider`
Provides historical and real-time canonical market data:
- `provider_name: str`
- `get_bars(symbol, timeframe, start, end) -> List[CanonicalMarketDataBar]`
- `get_latest_bar(symbol) -> Optional[CanonicalMarketDataBar]`
- `test_connection() -> Dict[str, Any]`

### `PaperExecutionProvider`
Simulates paper order submission and lifecycle management:
- `provider_name: str`
- `submit_paper_order(order, execution_price) -> Tuple[ExecutionOrder, ExecutionFill]`
- `cancel_paper_order(order_id, reason) -> ExecutionOrder`
- `get_order(order_id) -> Optional[ExecutionOrder]`
- `test_connection() -> Dict[str, Any]`

---

## 3. Reference Implementations

1. **`MockMarketDataProvider`**:
   - In-memory deterministic feed for unit and integration testing.
   - Allows seeding custom bars and simulating latency or connectivity interruptions.

2. **`SimulatedBrokerAdapter`**:
   - Executes paper orders using `ExecutionLifecycleManager`.
   - Incorporates realistic Indian market taxes and slippage models.
   - **Fail-Closed Safety:** If instantiated or invoked with `environment == ExecutionEnvironment.LIVE`, it raises an immediate `PermissionError`.
