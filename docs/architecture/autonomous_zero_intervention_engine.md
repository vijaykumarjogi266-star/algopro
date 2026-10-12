# Algo Lab — Zero-Human-Intervention Autonomous Paper Trading Architecture

## Overview

This specification details the **100% autonomous, zero-human-intervention** operating architecture for **Algo Lab** during its 30-day forward-testing phase on **Oracle Cloud Infrastructure (OCI)**. 

The system operates unattended Monday through Friday, enforcing strict financial accounting invariants, statutory Indian market microstructure rules, and fail-closed safety guardrails.

---

## 1. Autonomous Daily Lifecycle Timeline (Indian Standard Time - IST)

```
08:30 IST ───► Pre-Market Maintenance (Token refresh, SQLite backup, health audit)
09:00 IST ───► NSE Holiday & Universe Check (Skip trading if market is closed)
09:15 IST ───► Market Open: Launch live scanning & execution loop (60s cycles)
15:15 IST ───► Mandatory Intraday Auto-Square-Off (Liquidate positions, block BUYs)
15:35 IST ───► EOD Reconciliation & Tearsheet Dispatch (Audit PnL, webhook report)
16:00 IST ───► Nightly Database Maintenance (SQLite WAL checkpoint & VACUUM)
```

| Time (IST) | Event | Autonomous Action Executed |
| :--- | :--- | :--- |
| **08:30** | Pre-Market Readiness | • Resets daily killswitch flag.<br>• Copies `data/paper_trading.db` to timestamped backup in `data/backups/`.<br>• Emits Discord/Slack/Telegram readiness ping. |
| **09:00** | Market Calendar Gate | • Queries `NSE_HOLIDAYS_2026` calendar.<br>• If weekend or NSE trading holiday, sleeps until next morning. |
| **09:15** | Market Open Ingestion | • Begins 60-second scanning cycle across Nifty universe (`RELIANCE`, `TCS`, `INFY`, etc.).<br>• Evaluates `RiskEngine` limits before submitting any candidate orders. |
| **15:15** | Mandatory Square-Off | • Closes all open intraday positions at prevailing market prices.<br>• Cancels all working bracket stop-loss and target orders.<br>• Hard-blocks all subsequent `BUY` orders. |
| **15:35** | EOD Audit & Tearsheet | • Reconciles ending equity and realized PnL via `DoubleEntryLedgerReconciler`.<br>• Dispatches EOD performance summary to configured webhooks. |
| **16:00** | Database Maintenance | • Executes `PRAGMA wal_checkpoint(TRUNCATE)` and `VACUUM`. |

---

## 2. Hard Risk Failsafes & Circuit Breakers

### A. Maximum Daily Drawdown Killswitch (-2.5%)
* Calculated relative to daily opening equity:
  $$\text{Drawdown}_{\text{daily}} = \frac{\text{Equity}_{\text{open}} - \text{Equity}_{\text{current}}}{\text{Equity}_{\text{open}}}$$
* If $\text{Drawdown}_{\text{daily}} \ge 2.5\%$ (e.g., losing ₹1,250 on ₹50,000 buying power):
  1. The `AutonomousSentinel` trips the killswitch flag.
  2. All pending orders are cancelled.
  3. All new `BUY` signals are blocked.
  4. An emergency critical alert is dispatched via webhook.
  5. The system remains frozen until 08:30 IST the next morning.

### B. Broker Gateway Rate Limiter (3 req/sec)
* `ZerodhaKiteAdapter` enforces a sliding timestamp window preventing `HTTP 429` rate-limit errors.
* Multi-leg option baskets are executed atomically via `execute_multi_leg_basket`.

---

## 3. Self-Healing & Crash Recovery Architecture

* **Supervision by `systemd`:**
  * Process failures or unexpected kernel reboots trigger automated recovery within 5 seconds (`Restart=always`, `RestartSec=5s`).
* **Non-Volatile SQLite WAL Persistence:**
  * SQLite configured with `PRAGMA journal_mode = WAL` and `PRAGMA busy_timeout = 10000`.
  * Every order fill and mark-to-market snapshot is committed to disk immediately.
  * On restart, the daemon automatically discovers existing `SessionStatus.RUNNING` sessions and resumes without duplicating orders or losing cost basis history.

---

## 4. Zero-Intervention Webhook Telemetry

Configured via environment variables in `.env`:
* `DISCORD_WEBHOOK_URL` (Discord Channel Webhook)
* `SLACK_WEBHOOK_URL` (Slack Incoming Webhook)
* `TELEGRAM_BOT_TOKEN` & `TELEGRAM_CHAT_ID` (Telegram Bot)

### Automated Alerts Dispatched:
1. **08:30 IST:** Morning System Readiness Ping.
2. **Real-Time:** Order Executed (Symbol, Quantity, Fill Price, Stop-Loss, Target).
3. **15:15 IST:** Mandatory Auto-Square-Off Confirmation.
4. **15:35 IST:** EOD Performance Summary (Equity, Daily PnL, Win Rate).
5. **Real-Time:** Critical Drawdown Killswitch Alert (if triggered).
