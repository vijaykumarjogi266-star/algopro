# Algo Lab — Quantitative Investment & Trading Research OS

> **Canonical Version**: `0.2.0` | **Lifecycle State**: `forward-paper-validation` | **Execution Mode**: `PAPER-ONLY (SIMULATION)`
>
> Algo Lab is a systematic quantitative investment research, validation, and forward-simulation operating system designed for Indian equity and derivatives markets (NSE, BSE, MCX).
>
> *Algo Lab is strictly NOT an automated profit-generation bot, live broker gateway, or investment advisory system.*

---

## 1. Scope and Explicit Non-Goals

### Scope
- **Point-in-time quantitative research**: Bar-by-bar backtesting with zero lookahead, zero synthetic data injection, and realistic statutory slippage/brokerage models.
- **Independent sovereign risk engine**: Upstream capital preservation limits, portfolio drawdown breakers, and intraday session square-offs that cannot be bypassed by alpha strategies, AI/NLP models, or UI commands.
- **Forward paper simulation**: Clock-synchronized paper forward testing with double-entry accounting reconciliation and auditable decision manifests.
- **Deterministic data governance**: Versioned dataset manifests, immutable checksums, and explicit lineage stages (`RAW -> VALIDATED -> ADJUSTED -> FEATURE -> EXPERIMENT_INPUT`).

### Explicit Non-Goals
- **Zero Real-Money Execution**: Under no circumstances will Algo Lab place real orders on live exchange connections or broker accounts. Live trading is architecturally and programmatically disabled.
- **Zero Investment Advice**: Algo Lab generates quantitative simulations and research hypotheses for statistical evaluation. It does not provide financial, investment, tax, or legal recommendations.
- **Zero Synthetic Market Guessing**: If market data is missing, stale, or malformed, Algo Lab emits `WAIT` or halts. It never fabricates synthetic fills or prices in forward validation or production paths.

---

## 2. Paper-Only and Non-Investment-Advice Notice

> [!CAUTION]
> **PAPER TRADING ONLY — NO REAL MONEY AT RISK**
>
> `LIVE_TRADING_ENABLED` is permanently locked to `False`.  
> `REAL_BROKER_EXECUTION_ENABLED` is permanently locked to `False`.  
> Startup validation and CI immediately abort with `RuntimeError` if any configuration attempts to enable live execution.
>
> All orders, fills, positions, and PnL metrics are computed within an in-memory double-entry paper ledger or local simulation database. No network packets capable of placing live market orders will ever be dispatched by this codebase.

> [!NOTE]
> **REGULATORY & NON-INVESTMENT ADVICE DISCLAIMER**
>
> The materials, algorithms, models, and backtest results presented in Algo Lab are solely for academic and quantitative research purposes. They do not constitute financial advice or solicitation under SEBI (Research Analysts) Regulations, 2014, or any equivalent international regulatory framework.

---

## 3. Safety Invariants

Algo Lab operates under ten non-negotiable architectural invariants:

1. **`LIVE_TRADING_ENABLED` must remain false**: Hardcoded in `apps.api.core.project_state` and validated at app bootstrap.
2. **`REAL_BROKER_EXECUTION_ENABLED` must remain false**: Injected into all broker abstractions to guarantee paper-simulation mode.
3. **Fail-Closed Startup**: Any configuration setting `LIVE_TRADING_ENABLED=True` or `REAL_BROKER_EXECUTION_ENABLED=True` triggers instant termination.
4. **Sovereign Risk Engine**: Hard risk constraints, drawdown thresholds, and killswitches evaluate independently of strategy logic, AI models, and UI requests.
5. **Zero Risk Bypass**: No strategy, AI reasoning agent, sentiment indicator, or frontend API call can bypass risk limits or execute directly.
6. **No Synthetic Fallback**: Missing, stale (>900s), malformed, future-dated, or unverified market data forces a `WAIT` decision or rejection.
7. **Auditability and Point-in-Time Safety**: Backtests and paper sessions produce immutable manifests, complete audit logs, and deterministic state re-creations.
8. **No Live Order Routing Network Actions**: Outbound connections to broker order endpoints are blocked; test fixtures are isolated.
9. **Zero Credential or PII Leakage**: API keys and tokens are SHA-256 hashed at rest; sensitive broker parameters are redacted from logs and error traces.
10. **Backward-Compatible Versioning**: Breaking changes are documented in ADRs and `CHANGELOG.md` with semantic versioning compliance.

---

## 4. Architecture Overview

```
                                    +------------------------------------------+
                                    |         Next.js 14 Web Shell             |
                                    | (Role-Aware UI: Viewer/Researcher/Admin) |
                                    +--------------------+---------------------+
                                                         | HTTPS / REST
                                                         v
+----------------------------------------------------------------------------------------------------------------+
|                                           FastAPI Backend Service                                              |
|                                                                                                                |
|  [Security & Auth Middleware]                                                                                 |
|  - 5-Tier Scoped RBAC (Viewer, Researcher, Operator, Risk Admin, System Admin)                                 |
|  - Cryptographic Nonce-based CSP & HSTS | In-memory Rate Limiting | SHA-256 KeyStore Verification              |
|                                                                                                                |
|  [API Routes]                                                                                                 |
|  - /api/v1/system (Canonical Status)     - /api/v1/experiments (Research)    - /api/v1/datasets (Governance)     |
|  - /api/v1/circuit-breaker (Admin)       - /api/v1/credentials (Encrypted)   - /metrics (Prometheus Telemetry)    |
+----------------------------------------------------+-----------------------------------------------------------+
                                                     |
                         +---------------------------+---------------------------+
                         |                                                       |
                         v                                                       v
+---------------------------------------------------+   +---------------------------------------------------+
|               Sovereign Risk Engine               |   |            Quantitative Research Engine           |
|                                                   |   |                                                   |
| - Pre-Trade Capital & Position Checks             |   | - Factor Library & Deterministic Indicators       |
| - Max Daily Drawdown Killswitch (-2.5%)           |   | - Unified BaseStrategy Framework                  |
| - 15:15 IST Mandatory Intraday Square-Off        |   | - Deflated Sharpe Ratio (DSR) Robustness Gates    |
| - Signed HMAC Circuit Breaker State               |   | - Regime Detection & Walk-Forward Validation      |
+------------------------+--------------------------+   +-------------------------+-------------------------+
                         |                                                       |
                         +---------------------------+---------------------------+
                                                     |
                                                     v
+----------------------------------------------------------------------------------------------------------------+
|                                       Execution Gateway & Paper Engine                                         |
|                                                                                                                |
|  - Point-in-Time Bar Execution Simulator                                                                       |
|  - Statutory Cost Model (STT, Exchange Turnover Fees, GST, Stamp Duty, Slippage)                               |
|  - Double-Entry Ledger Reconciler (Cash + Cost Basis + Realized PnL + Fees == Initial Equity)                   |
|  - Paper-Only Broker Adapters (Mock, Zerodha Kite Paper Emulator)                                              |
+----------------------------------------------------+-----------------------------------------------------------+
                                                     |
                         +---------------------------+---------------------------+
                         |                                                       |
                         v                                                       v
+---------------------------------------------------+   +---------------------------------------------------+
|             Data Governance & Manifests           |   |            Storage & Backup Subsystem             |
|                                                   |   |                                                   |
| - Typed Dataset Manifests & Lineage Tracking      |   | - PostgreSQL 16 (Relational Entities & Runs)      |
| - Checksum Verification & Data Quality Anomaly    |   | - Parquet / DuckDB (Tick & Bar Features)          |
| - Versioned Calendar Provider (Exchange Hours/Hol)|   | - Encrypted AES-256 DB Backups (Automated Verify) |
+---------------------------------------------------+   +---------------------------------------------------+
```

---

## 5. Local Setup

### Prerequisites
- Python 3.11+ (Python 3.12 recommended)
- Node.js 18+ (Node 20 LTS recommended)
- PostgreSQL 16 (optional for local SQLite/fixture mode)
- Docker & Docker Compose (optional for containerized setup)

### Step-by-Step Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/vijaykumarjogi266-star/algopro.git
   cd algopro
   ```

2. **Configure environment**:
   ```bash
   cp .env.example .env
   ```

3. **Set up Python virtual environment**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   pip install -e .
   ```

4. **Verify locked dependencies and safety flags**:
   ```bash
   python3 scripts/verify_locks.py
   ```

5. **Start backend API**:
   ```bash
   uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
   ```
   API interactive documentation will be available at `http://127.0.0.1:8000/docs`.

6. **Start web shell** (in a separate terminal):
   ```bash
   cd apps/web
   npm install
   npm run dev
   ```
   Web interface accessible at `http://localhost:3000`.

---

## 6. Fixture-Based Demo

Algo Lab includes deterministic, self-contained fixtures allowing complete evaluation of research pipelines without any live network access or external broker credentials.

### Run Institutional Smoke Test & Dry Run
```bash
python3 test_dry_run_institutional.py
```
This runs a 6-module institutional validation checking:
1. Canonical project status (`0.2.0`, `forward-paper-validation`)
2. Sovereign risk limits & -2.5% daily drawdown killswitch
3. Point-in-time backtest simulation with fee calculation
4. Double-entry ledger accounting reconciliation
5. Rate limit and credential store encryption
6. Stored XSS defense and CSP nonce injection

### Run Replay Backtest with Fixture Data
```bash
python3 run_standalone_backtest.py --dataset fixtures/sample_nifty50_daily.parquet --strategy smacross --capital 1000000
```

---

## 7. Data Governance

All quantitative datasets within Algo Lab conform to explicit schemas and point-in-time auditability:

- **Lineage Classification**:
  - `RAW`: Immutable raw vendor or exchange feeds.
  - `VALIDATED`: Verified against null values, positive OHLC bounds, volume sanity, and duplicate timestamps.
  - `ADJUSTED`: Split and dividend adjusted using documented corporate action provenance.
  - `FEATURE`: Deterministically computed mathematical features.
  - `EXPERIMENT_INPUT`: Fixed snapshot referenced by hash in experiment manifests.
- **Strict Data Validation Invariant**:
  - If a bar is missing, future-dated, or violates $Low \le Open, Close \le High$, the ingest engine halts and rejects.
  - **No synthetic fill or price extrapolation** is permitted in production or forward validation.
- **Versioned Market Calendar**:
  - Market session schedules, trading hours (09:15–15:30 IST), and exchange holidays are handled through a typed, versioned `CalendarProvider` (`services.market_data.calendar_provider`).

---

## 8. Research and Backtest Workflow

1. **Dataset Ingestion & Manifest Registration**:
   Register new datasets via `services/market_data/manifest.py` to produce a cryptographic SHA-256 manifest.
2. **Strategy Definition**:
   Implement strategies inheriting from `quant.strategies.base.BaseStrategy`. Strategies only output trade proposals (`SignalEvent` or `IntentEvent`).
3. **Execution Simulator**:
   Proposals are evaluated by `services/backtest_engine/simulator_contract.py` which applies:
   - Bar open / next-tick fill assumptions
   - Statutory Indian transaction costs (STT, SEBI turnover, exchange fees, GST, stamp duty)
   - Volume participation limits and slippage models
4. **Experiment Manifest Generation**:
   Every backtest outputs a JSON manifest containing strategy code hash, parameter lock, dataset checksum, and comprehensive performance metrics (Sharpe, Sortino, Calmar, CVaR 95/99, Max Drawdown).

---

## 9. Forward Paper-Simulation Workflow

The forward paper simulation runs unsupervised on market days following a strict clock-synchronized schedule:

```
[08:30 IST] Pre-Market Sentinel
       │  • Loads approved strategy decision manifest from data/decisions/
       │  • Executes encrypted database backup and runs health probe
       ▼
[09:15 - 15:15 IST] Autonomous Paper Engine
       │  • Evaluates live market snapshots against sovereign risk constraints
       │  • Simulates fills with realistic slippage and fee deduction
       │  • Monitors daily drawdown killswitch (-2.5%) and position exposure
       ▼
[15:15 IST] Mandatory Intraday Square-Off
       │  • Liquidates all open intraday positions at simulated market price
       │  • Rejects any new order proposals submitted after 15:15 IST
       ▼
[15:35 IST] Post-Market Double-Entry Reconciliation
       │  • Verifies: Cash + Position Cost Basis + Realized PnL - Fees == Initial Balance
       │  • Emits signed reconciliation report and daily tearsheet
       ▼
[15:40 IST] Quantitative Research & Regime Classification
       │  • Tests candidate strategies over rolling window; applies DSR gates
       │  • Emits WAIT if robustness criteria are not satisfied
       ▼
[16:00 IST] Off-Market Standby Mode
       │  • Database checkpoint and quiet sleep until next trading day 08:30 IST
```

---

## 10. Deployment

### Production Hardening Guidelines
- **Containerization**: Use `docker/Dockerfile.api` which enforces non-root execution (`uid=10001`), read-only root filesystem with tmpfs `/tmp`, `no-new-privileges`, and dropped Linux capabilities.
- **Network Isolation**: The backend API binds strictly to `127.0.0.1` and sits behind an Nginx reverse proxy with TLS 1.3 termination, rate limiting, and security headers.
- **Secrets Management**: Secrets are injected via environment variables at runtime. Credentials are never written to disk, images, or log output.
- **Automated Backup & Restore**:
  - Run encrypted backup: `python3 scripts/backup_database.py --encrypt`
  - Automated restore verification test: `pytest tests/unit/test_backup_restore_encryption.py`
  - Target RPO: $\le 15\text{ minutes}$; Target RTO: $\le 5\text{ minutes}$.

---

## 11. Incident Response

In the event of an anomaly, data corruption, or threshold breach:

1. **Circuit Breaker Trip**:
   - The system transitions automatically to `EMERGENCY_HALT` if daily loss exceeds 2.5%, feed connection drops during active positions, or HMAC verification fails.
   - Manual breaker trip via admin CLI:
     ```bash
     python3 -m services.execution_gateway.circuit_breaker --trip --reason "Manual investigation"
     ```
2. **Post-Halt Recovery**:
   - Inspect signed breaker state in `data/circuit_breaker_state.json`.
   - Verify ledger integrity with `python3 -m services.execution_gateway.reconciliation_engine`.
   - Reset breaker with multi-party authorized token:
     ```bash
     python3 -m services.execution_gateway.circuit_breaker --reset --token <SECRET_RESET_TOKEN>
     ```

---

## 12. Contributing and Security Reporting

- **Contributing**: Please review [CONTRIBUTING.md](file:///root/algopro/CONTRIBUTING.md) for pull request guidelines, coding standards, and branch policies.
- **Security Inquiries**: To report security vulnerabilities or invariant violations, consult [SECURITY.md](file:///root/algopro/SECURITY.md).
- **Code Ownership**: Code ownership mappings are defined in [CODEOWNERS](file:///root/algopro/.github/CODEOWNERS).
- **Release Verification**: All code must pass `make release-check` prior to submission.
