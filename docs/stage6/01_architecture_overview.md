# Algo Lab Stage 6 — Architecture Overview

## 1. Mission and Core Objectives
Algo Lab Stage 6 expands the institutional research platform into **Market Data, Historical Replay & Paper Trading**. It connects historical dataset management and point-in-time quantitative backtesting with real-time simulated order execution, while preserving all Stage 4 and Stage 5 safety, reproducibility, and risk guarantees.

### Non-Negotiable Safety Principle
> **Principle 25: Paper trading must remain completely separate from real-money broker execution.**
> Live capital deployment is hard-disabled (`LIVE_TRADING_ENABLED = False`, `REAL_BROKER_EXECUTION_ENABLED = False`). Any attempt to configure or execute in `LIVE` mode fails closed immediately with an explicit permission exception.

---

## 2. High-Level System Topology

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           HISTORICAL MARKET DATA                            │
│  CanonicalMarketDataBar ──▶ CanonicalMarketDataValidator ──▶ DatasetRegistry │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          DETERMINISTIC REPLAY                               │
│  HistoricalReplayEngine ──▶ Strict Look-Ahead Guard ──▶ Multi-Symbol Sync   │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                             STRATEGY LAYER                                  │
│  Strategy / Alpha Model ──▶ TradeCandidate / Order Proposal                 │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       INDEPENDENT RISK ENGINE (GATE)                         │
│  Evaluates Portfolio Limits, Stop-Loss, Max Capital, Drawdown               │
│  Approved ──▶ ORDER_ACCEPTED               Rejected ──▶ ORDER_REJECTED      │
│                                                          (0 Mutation)       │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       PAPER TRADING EXECUTION ENGINE                         │
│  SimulatedBrokerAdapter ──▶ Deterministic Slippage ──▶ Statutory Costs      │
│  PaperPortfolio (Cash + Market Value == Total Equity)                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Major Functional Pillars

1. **Canonical Market Data Contracts**:
   - Timezone-aware UTC normalization.
   - Mathematical OHLC consistency (`high >= max(open, close)` and `low <= min(open, close)`).
   - Zero tolerance for NaN, Infinite values, or silent repair.

2. **Dataset Registry & Cryptographic Validation**:
   - SHA-256 fingerprinting of all canonical bar sequences.
   - Automatic drift detection with fail-closed rejection (`DatasetDriftError`).
   - Quarantine lifecycle to isolate suspect data.

3. **Deterministic Historical Replay Engine**:
   - Chronological delivery sorted strictly by `(timestamp, symbol)`.
   - Strict look-ahead guard: attempting to access future timestamps throws `LookAheadBiasError`.
   - Indian market calendar enforcement (09:15 to 15:30 IST session filtering, official exchange holiday exclusion).
   - Multi-symbol portfolio synchronization without forward leakage.

4. **Order Execution Lifecycle**:
   - Granular state machine: `ORDER_PROPOSED` ──▶ `RISK_CHECK_EVALUATED` ──▶ `ORDER_ACCEPTED` / `ORDER_REJECTED` ──▶ `ORDER_SUBMITTED` ──▶ `ORDER_FILLED` / `ORDER_CANCELLED` / `ORDER_FAILED`.
   - Complete state transition audit trail with immutable timestamps and reasons.

5. **Paper Trading Engine & Portfolio Tracking**:
   - In-memory simulated broker adapter with deterministic slippage and realistic Indian statutory costs (brokerage, STT, turnover charges, SEBI fees, GST, stamp duty).
   - Multi-session concurrent management with thread-safe SQLite persistence.
   - Strict financial accounting invariant: `Starting Capital + Realized P&L + Unrealized P&L - Fees = Total Equity`.

6. **Credential Security & Masking**:
   - Zero plain-text credentials in logs, UI responses, audit ledgers, or Git commits.
   - Automatic masking (`ak****8877`) with configured boolean status flags.
