# [ADR-0001] Comprehensive Paper-Only Platform Hardening and Sovereign Risk Architecture

## Status
*Accepted*

## Date
2026-10-14

## Context
Algo Lab is designed as an institutional quantitative research and forward paper-simulation operating system for Indian capital markets. In earlier iterations, flat API keys, unversioned stage labels, synthetic market data fallback, and host-dependent build tools created risks of false positives and privilege ambiguities. A disciplined, institutional-grade architecture is required to guarantee:
1. Strict paper-only execution with zero real-money order transmission under any circumstances.
2. Sovereign risk engine isolation that cannot be bypassed by strategies, AI agents, or frontend requests.
3. Fine-grained Role-Based Access Control (`viewer`, `researcher`, `operator`, `risk_admin`, `system_admin`).
4. Point-in-time safe, versioned data governance with typed dataset manifests and explicit data lineage.
5. Deterministic, auditable backtest execution with realistic Indian market statutory costs.

## Decision
1. **Permanent Invariant Locking**: `LIVE_TRADING_ENABLED = False` and `REAL_BROKER_EXECUTION_ENABLED = False` are permanently locked at code level. Any attempt to enable them triggers fail-closed startup abort.
2. **Canonical Project State**: Establish a single source of truth in `apps.api.core.project_state` defining semantic version (`0.2.0`), build revision, lifecycle state (`forward-paper-validation`), and safety invariants.
3. **Explicit RBAC & Cryptographic Key Validation**: Implement a 5-tier role hierarchy with constant-time verification, salted key hashing at rest, key rotation, and rate-limiting.
4. **Data Governance & Manifests**: Define typed manifests (`DatasetManifest`), 5-stage data lineage (`raw -> validated -> adjusted -> feature -> experiment_input`), and pluggable market calendar interfaces.
5. **Execution Simulation Contract**: Formalize realistic execution accounting with statutory Indian taxes (STT, GST, stamp duty, exchange turnover fees) and volume participation limits.
6. **Hardened Containerization**: Enforce non-root execution (`appuser:10001`), read-only root filesystems, `no-new-privileges`, and dropped Linux capabilities.

## Consequences
### Positive
- Zero probability of accidental live capital deployment.
- High reproducibility and auditability of backtest and paper trading results.
- Robust security posture against unauthorized access, XSS, and privilege escalation.
- Clear operational runbooks and disaster recovery objectives (RPO < 24h, RTO < 5m).

### Negative / Trade-offs
- Missing or malformed data strictly aborts execution (`WAIT` or rejection) with no silent synthetic fallback.
- Additional operational rigor required to manage cryptographic API keys and role scoping.

## Compliance & Invariants
- `LIVE_TRADING_ENABLED` is validated at startup and tested in CI.
- Risk engine evaluation is independent and mandatory prior to all paper fill creations.
