# Algo Lab — Failure Modes & Architectural Remediations

## Overview

This document formalizes the systematic failure mode analysis and corresponding architectural remediations implemented for **Algo Lab** in production and simulated execution environments, specifically targeting the Indian derivatives markets (NSE, BSE, MCX) and edge compute runtimes (such as Android/Termux and containerized Linux).

---

## 1. Concurrency & Database Contention (SQLite WAL Hardening)

### Failure Mode
- Under high market throughput and multi-session paper trading, simultaneous read/write operations against the paper trading database resulted in `sqlite3.OperationalError: database is locked`.
- Default SQLite journal mode (`DELETE`) locks the entire database file during writes, stalling active market scanners.

### Remediation Implemented
- **Write-Ahead Logging (WAL):** Enabled `PRAGMA journal_mode = WAL` and `PRAGMA synchronous = NORMAL`.
- **Busy Timeout:** Configured `PRAGMA busy_timeout = 10000` (10-second wait window before rejecting).
- **Non-blocking Reads:** In WAL mode, concurrent readers execute simultaneously without acquiring write locks or being blocked by the paper daemon.

---

## 2. Broker Gateway Rate Limiting & Unhedged Leg Risk (Zerodha Kite Connect)

### Failure Mode
- Zerodha Kite Connect 3.0 strictly enforces a 3 requests/second rate limit.
- In multi-leg option strategies (e.g., Straddles, Strangles, Iron Condors), submitting legs in burst triggered `HTTP 429 Too Many Requests`.
- Partial execution caused "leg risk" (one option leg filled, while counter-balancing hedge legs were rejected), exposing the portfolio to unhedged directional tail risk.

### Remediation Implemented
- **Sliding-Window Rate Limiter:** Implemented in `ZerodhaKiteAdapter` enforcing a strict $\le 3\text{ req/sec}$ sliding timestamp window with adaptive backoff.
- **Atomic Multi-Leg Basket Executor (`execute_multi_leg_basket`):** Bundles multi-leg option orders with fail-closed safety semantics. If any leg fails, execution halts immediately and triggers compensatory alerts to eliminate naked exposure.

---

## 3. Background Process Keep-Alive & Graceful State Persistence

### Failure Mode
- On mobile/edge Linux environments (Android/Termux), aggressive OS power management (Low Memory Killer / Phantom Process Killer) terminates long-running background trading daemons without warning.
- Abrupt `SIGKILL` / `SIGTERM` caused incomplete state persistence and corrupted active paper sessions.

### Remediation Implemented
- **Termux Wake-Lock Integration:** Added automatic `termux-wake-lock` acquisition in `start_paper_daemon.sh` and cleanup via `termux-wake-unlock` in `stop_paper_daemon.sh`.
- **Graceful Signal Handling:** Added `SIGINT` and `SIGTERM` listeners in `run_live_paper_daemon.py`. The daemon catches termination signals, marks-to-market open positions, commits full portfolio equity state to the database, and exits cleanly.

---

## 4. Indian Market Specific Risk Guardrails

- **Stock Option Physical Delivery (`OPTSTK`):** Compulsory physical delivery obligations near monthly expiry are quarantined.
- **Statutory Friction & Costs:** All paper and backtest fills account for Indian Securities Transaction Tax (STT), Stamp Duty, GST, and exchange transaction fees.
