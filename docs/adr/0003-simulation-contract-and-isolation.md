# ADR-0003: Simulator Execution Contract and Sovereign Risk Isolation

## Context
Backtest realism requires explicitly modeled market friction, volume caps, and statutory taxes. Furthermore, safety invariant #4 and #5 mandate that the risk engine must remain sovereign: no strategy, AI agent, or user interface command may directly submit orders or bypass risk limits.

## Decision
1. Implement a formalized `SimulatorContract` governing signal time, order submission time, fill time, spread/slippage models, statutory transaction costs (STT, SEBI turnover, exchange fees, stamp duty, GST), and volume participation caps.
2. Mandate that all execution assumptions are exported in backtest experiment manifests.
3. Enforce sovereign risk isolation via architectural AST analysis in unit tests (`tests/unit/test_architecture_isolation.py`), ensuring that strategy implementations and AI agents do not import or directly invoke broker execution adapters or order submission methods.

## Status
Accepted

## Consequences
- Research metrics reflect real-world Indian market frictions and institutional statutory taxes.
- Eliminates risk-bypass vectors and guarantees that all order proposals flow through sovereign risk evaluation.
