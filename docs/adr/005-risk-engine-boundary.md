# ADR-005: Sovereign Risk Engine Boundary & AST Isolation

## Context
Safety Invariants #4 and #5 mandate that the risk engine must evaluate state authoritatively and remain independent of all strategies, AI reasoning components, news/NLP sentiment feeds, and user interface actions. No component may bypass risk controls or directly instantiate order fills.

## Decision
1. Decouple strategy logic from execution routing: strategies only emit trade proposals (`SignalEvent` / `IntentEvent`).
2. Order proposals must flow through the sovereign Risk Engine before reaching the simulated execution gateway:
   ```
   Strategy / AI Proposal ──> Sovereign Risk Engine ──> Paper Execution Gateway ──> Double-Entry Ledger
   ```
3. Implement static AST architecture isolation tests (`tests/unit/test_architecture_isolation.py`) ensuring no strategy or AI component directly imports broker execution adapters or invokes order placement methods.
4. Log all rejected proposals with structured diagnostic reasons.

## Status
Accepted

## Consequences
- Guaranteed preservation of capital and hard risk limit enforcement.
- Eliminates risk bypass vulnerabilities across all current and future quantitative strategies.
