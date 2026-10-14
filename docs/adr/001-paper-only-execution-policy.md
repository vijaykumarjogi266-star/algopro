# ADR-001: Paper-Only Execution Policy & Hard Invariants

## Context
Algo Lab is designed strictly as a quantitative research, backtesting, and forward paper-simulation operating system. Real capital deployment, broker live order transmission, and real money routing introduce substantial financial risk and regulatory liability that are completely outside the project's scope.

## Decision
1. Permanently lock `LIVE_TRADING_ENABLED = False` and `REAL_BROKER_EXECUTION_ENABLED = False` in `apps.api.core.project_state`.
2. Fail closed during application bootstrap (`apps.api.main:lifespan`): if any environment variable or configuration attempts to enable live execution, abort startup with `RuntimeError`.
3. In all broker adapters, order routing must fail closed if non-simulated order placement is invoked.
4. Pre-commit hooks, CI checks, and automated AST scans must reject any pull request attempting to unlock live execution.

## Status
Accepted

## Consequences
- Guaranteed zero financial capital risk.
- Deterministic simulation of order execution without external broker order routing.
- Eliminates attack surface related to live exchange order tampering.
