# AGENTS.md — Algo Lab Project Operating Charter & Agent Directives

> **System Profile**: Algo Lab Quantitative Research & Autonomous Forward Trading OS  
> **Host**: Oracle Cloud Infrastructure (OCI) Linux VPS  
> **Environment**: Python 3.12 (`/home/ubuntu/algopro/.venv`)  
> **Supervision Tier**: Autonomous Zero-Human-Intervention (30-Day Forward Testing)

---

## 1. Prime Invariants & Governance Hierarchy

All agents operating in this workspace must adhere strictly to the Non-Negotiable Hierarchy:
```
Capital Preservation ──▶ Data Integrity ──▶ Research Integrity ──▶ Risk Management ──▶ Execution Quality ──▶ Performance
```

### Non-Negotiables
1. **Never force a trade**: Principle 2 (`WAIT` decision) is a completely valid state.
2. **Fail-Closed Live Safety**: Real capital trading is permanently locked (`ALLOW_LIVE_TRADING=false`).
3. **Daily Drawdown Killswitch**: Tripped if portfolio equity decays $\ge 2.5\%$ from daily starting equity. All new entry orders freeze immediately.
4. **Mandatory 15:15 IST Auto-Square-Off**: All open intraday positions MUST be squared off before regular session close (15:30 IST).
5. **Independent Risk Engine**: Strategy signals must pass independent risk filters (Max 4 positions, 5x leverage cap, 20% max allocation per trade, mandatory stop loss, and VaR filter).
6. **Reproducibility**: All backtests, datasets, and strategy decisions must produce versioned manifests in `data/decisions/` and `data/backups/`.

---

## 2. Daily Market Lifecycle (Indian Standard Time, UTC + 5:30)

| Timestamp (IST) | Routine | Action & Verification |
| :--- | :--- | :--- |
| **00:00** | **Midnight Rollover** | Resets daily counters, re-anchors daily starting equity, evaluates calendar trading day status. |
| **08:30 – 09:14** | **Pre-Market Maintenance** | Backs up SQLite DB to `data/backups/paper_trading_<YYYYMMDD>.db`, resets killswitch, loads research allocation, dispatches readiness telemetry. |
| **09:15 – 15:15** | **Live Active Session** | Scans 8 core NSE symbols every 60s, executes trailing SL / TP triggers, passes BUY setups through RiskEngine, marks portfolio to market. |
| **15:15 – 15:30** | **Square-Off Cutoff** | Mandatory auto-square-off of any lingering intraday positions; blocks all new entries. |
| **15:35** | **EOD Reconciliation** | Double-entry ledger audit, cash vs portfolio reconciliation, performance tearsheet alert. |
| **15:40** | **Quantitative Research Bot**| Backtests candidate strategies against recent market data, classifies market regime, and allocates strategy for next day. |
| **16:00** | **DB Maintenance** | SQLite `PRAGMA wal_checkpoint(TRUNCATE)` and `VACUUM`. |
| **16:15 – 08:30** | **Off-Market Standby** | Sleep mode with periodic 15-minute heartbeats to preserve CPU and network resources. |

---

## 3. System Services & Auto-Recovery Infrastructure

* **Primary Daemon**: `algolab-paper.service` (Runs `/home/ubuntu/algopro/.venv/bin/python run_live_paper_daemon.py`).
* **Watchdog Supervisor**: `algolab-watchdog.timer` (Fires `scripts/cloud/algolab-watchdog.sh` every 2 minutes).
* **Database State**: `/home/ubuntu/algopro/data/paper_trading.db`.
* **Live Log Stream**: `/home/ubuntu/algopro/data/paper_trading_live.log`.
* **Telemetry Dispatcher**: Supports Discord, Slack, and Telegram webhooks configured in `.env`.

---

## 4. Operational Runbook for Agents

When inspecting, modifying, or diagnosing this repository:
1. **Always use virtualenv Python**: `/home/ubuntu/algopro/.venv/bin/python` (and `pytest`).
2. **Preserve full test coverage**: Run `/home/ubuntu/algopro/.venv/bin/pytest tests/ -q` after any modifications; all 409 tests must pass.
3. **Service Management**:
   ```bash
   sudo systemctl status algolab-paper.service
   sudo systemctl restart algolab-paper.service
   tail -n 50 /home/ubuntu/algopro/data/paper_trading_live.log
   ```
4. **Git Sync**: Keep local changes committed and pushed to `origin/main`.
