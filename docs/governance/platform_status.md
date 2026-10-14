# Algo Lab — Canonical Platform Status & Governance Document

> **Authoritative Specification**: This document is the single source of truth for Algo Lab project status, versioning, supported capabilities, safety invariants, and operational boundaries.

---

## 1. Executive Metadata

| Attribute | Canonical Value |
| :--- | :--- |
| **Product Name** | Algo Lab (algopro) |
| **Semantic Version** | `0.2.0` |
| **Lifecycle State** | `forward-paper-validation` |
| **Execution Policy** | **STRICTLY PAPER-TRADING ONLY (SIMULATION)** |
| **Source of Truth Module** | [`apps/api/core/project_state.py`](file:///root/algopro/apps/api/core/project_state.py) |
| **Release Gate Command** | `make release-check` |
| **Active Remediation Branch**| `feature/platform-hardening` |

---

## 2. Platform Lifecycle Definitions

Algo Lab adheres to four formal lifecycle states:

```
[prototype] ──> [research] ──> [forward-paper-validation] ──> [release-candidate]
                                          ▲
                                   CURRENT STATE
```

- **`prototype`**: Experimental scripts and ad-hoc backtests. Safety controls may be incomplete.
- **`research`**: Point-in-time backtesting, deterministic factor libraries, and offline dataset registries verified.
- **`forward-paper-validation` (CURRENT)**: Clock-synchronized daily paper forward trading, sovereign circuit breakers, double-entry ledger reconciliation, 5-tier scoped RBAC, and encrypted backups.
- **`release-candidate`**: Complete CI evidence package, audited disaster recovery restore drill, automated container vulnerability scans, and external security sign-off.

---

## 3. Supported Markets & Instruments

| Market / Exchange | Asset Classes | Operational Mode | Execution Gateway |
| :--- | :--- | :---: | :--- |
| **NSE (National Stock Exchange)** | Equity (Cash), Index Futures | Paper Simulation | `PaperEngine` / Zerodha Kite Paper Emulator |
| **BSE (Bombay Stock Exchange)** | Equity (Cash) | Paper Simulation | `PaperEngine` / Mock Adapter |
| **MCX (Multi Commodity Exchange)**| Commodities | Research & Backtest | Point-in-Time Historical Replay |

---

## 4. Explicitly Excluded Capabilities (Non-Goals)

Under no circumstances does Algo Lab support or permit:
1. **Real-Money Order Placement**: No outbound network packet capable of transmitting a live exchange order will ever be dispatched.
2. **Broker Account Fund Management**: No withdrawal, transfer, or balance alteration on external broker gateways.
3. **Synthetic Market Bar Fabrication**: In forward paper or production runs, missing or corrupted market data results in `WAIT` or rejection, never synthetic price hallucination.
4. **Autonomous Risk Bypass**: No strategy, AI reasoning agent, NLP sentiment model, or UI route can bypass sovereign risk controls or directly instantiate fills.
5. **Investment Advisory**: Algo Lab generates quantitative hypotheses for statistical evaluation. It is not a SEBI-registered Research Analyst or Investment Adviser.

---

## 5. Non-Negotiable Safety Invariants

```python
# Permanent, immutable architectural locks in apps.api.core.project_state
LIVE_TRADING_ENABLED: bool = False
REAL_BROKER_EXECUTION_ENABLED: bool = False
```

- **Fail-Closed Startup**: Application bootstrap in `apps.api.main:lifespan` verifies these flags and aborts with `RuntimeError` if either is `True`.
- **CI Enforcement**: Pre-commit and GitHub Actions jobs fail if any commit modifies or tries to set either flag to `True`.
- **AST Architecture Isolation**: Automated AST tests in `tests/unit/test_architecture_isolation.py` inspect strategy and agent source code to prevent broker adapter imports.

---

## 6. Implementation Maturity Matrix

| Component / Subsystem | Maturity Status | Evidence & Test Location |
| :--- | :---: | :--- |
| **Project State & Version** | ✅ Implemented | `apps/api/core/project_state.py`, `tests/integration/test_python312_startup.py` |
| **5-Tier Scoped RBAC** | ✅ Implemented | `apps/api/core/auth.py`, `tests/integration/test_authorization.py` |
| **Cryptographic KeyStore** | ✅ Implemented | `apps/api/core/auth.py`, `tests/integration/test_authorization_enforcement.py` |
| **CSP Nonce & Web Security** | ✅ Implemented | `apps/api/main.py`, `tests/browser/test_stored_xss.py` |
| **Typed Dataset Manifests** | ✅ Implemented | `services/market-data/manifest.py`, `tests/unit/test_data_governance_lineage.py` |
| **Versioned Calendar Provider** | ✅ Implemented | `services/market-data/calendar_provider.py`, `tests/unit/test_data_governance_lineage.py` |
| **Execution Simulator Contract**| ✅ Implemented | `services/backtest-engine/simulator_contract.py`, `tests/unit/test_architecture_isolation.py` |
| **Double-Entry Reconciliation** | ✅ Implemented | `services/execution_gateway/reconciliation_engine.py`, `test_dry_run_institutional.py` |
| **Sovereign Circuit Breaker** | ✅ Implemented | `services/execution_gateway/circuit_breaker.py`, `tests/unit/test_circuit_breaker_state_integrity.py` |
| **Encrypted Backup & Restore** | ✅ Implemented | `scripts/backup_database.py`, `tests/unit/test_backup_restore_encryption.py` |
| **Prometheus Observability** | ✅ Implemented | `apps/api/routes/metrics.py`, `tests/unit/test_batch_f_config_and_breaker.py` |
| **CycloneDX 1.5 SBOM** | ✅ Implemented | `scripts/generate_sbom.py`, `scripts/verify_locks.py` |
| **Hardened Container Profile** | ✅ Implemented | `docker/Dockerfile.api`, `docker/nginx.conf`, `docker-compose.prod.yml` |

---

## 7. Known Host Limitations

- **Android Termux ARM64 Environment**:
  - Next.js native SWC compiler does not publish precompiled binaries for Termux ARM64; full web shell builds are validated in Linux x86_64 CI (`.github/workflows/ci.yml`).
  - Docker daemon is not run directly on Android Termux; container builds and layer canary scans are executed in CI.

---

## 8. Current Verification & Test Summary

- **Repository Test Suite**: 753 passed baseline tests + 27 passed platform hardening tests = **780 passed tests (0 failures)**.
- **Institutional Dry Run**: **6/6 modules passed (100%)** (`test_dry_run_institutional.py`).
- **Static Security Scan**: Bandit SAST: **21,666 lines scanned, 0 issues identified**.
