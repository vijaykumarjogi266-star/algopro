# Algo Lab — Quantitative Investment & Trading Research OS

> **A professional quantitative investment and trading research operating system for Indian markets (NSE, BSE, MCX).**
>
> *Algo Lab is NOT an AI trading bot.* It is a systematic research, validation, and decision platform.

---

## Non-Negotiable Hierarchy

```
Capital preservation → Data integrity → Research integrity → Risk management → Execution quality → Performance
```

---

## Core Principles (Summary)

1. **Never force a trade.**
2. **WAIT is a valid decision.**
3. **Bad or uncertain data must not produce a trading decision.**
4. **No look-ahead bias.**
5. **No data leakage.**
6. **No survivorship bias where applicable.**
7. **Every backtest must be reproducible.**
8. **Every strategy must be versioned.**
9. **Every dataset must be versioned.**
10. **Every experiment must be auditable.**
11. **Indicators are evidence, not automatic trading decisions.**
12. **RSI must never independently generate BUY/SELL decisions.**
13. **Multiple correlated indicators must not be treated as independent evidence.**
14. **Risk Engine must remain independent from Strategy/Alpha.**
15. **AI must never override hard risk controls.**
16. **AI must never silently modify production strategies.**
17. **AI must never directly control unrestricted order execution.**
18. **All trading decisions must be explainable through evidence.**
19. **Performance must be evaluated after realistic costs and slippage.**
20. **Optimize for robustness, not maximum historical return.**
21. **Evaluate portfolio-level risk, not only individual trades.**
22. **Record rejected trades, WAIT decisions and missed opportunities.**
23. **Simple UI; sophisticated engineering underneath.**
24. **Reliability is more important than feature count.**
25. **No live capital deployment during the initial development stages.**

---

## Directory Architecture

```
algo-lab/
├── apps/
│   ├── web/                    # Next.js 14 TypeScript Web Shell
│   └── api/                    # FastAPI High-Performance Backend
│
├── services/
│   ├── market-data/            # Market data ingestion & streaming (Stage 2)
│   ├── data-quality/           # Data quality validator & anomaly detection
│   ├── backtest-engine/        # Backtest engine contracts & metrics suite
│   ├── paper-engine/           # Simulated in-memory paper trading broker
│   ├── risk-engine/            # Independent hard risk limits & guardrails
│   └── execution-engine/       # Execution engine (Stage 14)
│
├── quant/
│   ├── indicators/             # Deterministic indicator library (SMA, RSI, ATR)
│   ├── strategies/             # Unified BaseStrategy contracts & signals
│   ├── factors/                # Factor definitions (Stage 3)
│   └── portfolio/              # Portfolio construction & allocation (Stage 10)
│
├── research/
│   ├── experiments/            # Auditable experiment manifests
│   ├── datasets/               # Versioned dataset catalogs
│   ├── reports/                # Performance & tear-sheet exports
│   └── notebooks/              # Quantitative research scratchpads
│
├── data/
│   ├── raw/                    # Immutable raw market feeds
│   ├── processed/              # Cleaned & verified point-in-time data
│   ├── features/               # Computed feature stores
│   └── schemas/                # OHLCV, ticks, and validation schemas
│
├── database/
│   ├── migrations/             # Alembic migration scripts
│   └── models/                 # SQLAlchemy models (Experiments, Decisions, Audit)
│
├── tests/
│   ├── unit/                   # Health, API, & module tests
│   ├── contracts/              # Contract invariant & data validation tests
│   └── integration/            # Multi-component pipeline tests
│
├── docker/                     # Dockerfiles & container assets
├── docs/                       # Architecture, strategy, and risk documentation
├── .github/workflows/          # Automated GitHub Actions CI pipeline
├── docker-compose.yml          # PostgreSQL & API container orchestration
└── README.md
```

---

## Tech Stack

- **Backend**: Python 3.12, FastAPI, Pydantic v2, Pydantic-Settings
- **Quant & Data**: Polars, NumPy, DuckDB, PyArrow, Parquet
- **Database**: PostgreSQL 16 (asyncpg, SQLAlchemy 2.0, Alembic)
- **Frontend**: Next.js 14, TypeScript, Tailwind CSS, Lucide React
- **Testing**: pytest, pytest-asyncio, pytest-cov, httpx
- **Infra & DevOps**: Docker, Docker Compose, GitHub Actions CI

---

## Quickstart

### 1. Setup Environment
```bash
cp .env.example .env
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

### 2. Run Database
```bash
docker compose up -d postgres
```

### 3. Run FastAPI Backend
```bash
uvicorn apps.api.main:app --reload --port 8000
```
Interactive documentation: [http://localhost:8000/docs](http://localhost:8000/docs)

### 4. Run Next.js Web Shell
```bash
cd apps/web
npm install
npm run dev
```
Web application: [http://localhost:3000](http://localhost:3000)

### 5. Run Test Suite
```bash
pytest tests/ -v
```

---

### 5. Run Test Suite & Institutional Dry Run
```bash
# Run unit & contract test suite
pytest tests/ -v

# Run 6-module institutional safety & integration verification
python3 test_dry_run_institutional.py
```

---

## Oracle Cloud Infrastructure (OCI) Deployment & Operations

Algo Lab is designed for **30-day unsupervised forward paper testing on Oracle Cloud Infrastructure (OCI)** with **zero human intervention**.

### 1. One-Line Setup on OCI Ubuntu Server
```bash
# 1. Clone repository
git clone https://github.com/vijaykumarjogi266-star/algopro.git /home/ubuntu/algopro
cd /home/ubuntu/algopro

# 2. Run automated server setup (packages, firewall, systemd registration)
bash scripts/cloud/setup_vps.sh

# 3. Create virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install yfinance pyotp

# 4. Configure environment
cp .env.example .env
nano .env
```

### 2. Operating the 24/7 Systemd Background Daemon
```bash
# Start paper trading daemon
sudo systemctl start algolab-paper

# Check service status & uptime
sudo systemctl status algolab-paper

# Stream live real-time trading logs
tail -f data/paper_trading_live.log

# Graceful stop (liquidates open positions and writes SQLite WAL checkpoint)
sudo systemctl stop algolab-paper

# Restart after pulling latest updates
git pull origin main
sudo systemctl restart algolab-paper
```

---

## Autonomous Zero-Human-Intervention Daily Schedule (IST)

The platform runs on a fully automated, clock-synchronized daily schedule adhering strictly to **Principle 1 (Never force a trade)** and **Principle 2 (WAIT is a valid decision)**:

```
[08:30 IST] Pre-Market Sentinel
       │  • Loads yesterday's strategy decision manifest from data/decisions/
       │  • Runs DB backup to data/backups/ & system health probe
       │  • Dispatches pre-market readiness webhook
       ▼
[09:15 - 15:15 IST] Live Autonomous Paper Engine
       │  • Scans NSE market every 60 seconds
       │  • Enforces 5x buying power, ATR stop-loss, and target profit
       │  • Trips -2.5% daily drawdown killswitch if breached (freezes entries)
       ▼
[15:15 IST] Mandatory Intraday Square-Off Cutoff
       │  • Auto-squares off all open intraday positions at market
       │  • Strictly prohibits new entries after 15:15 IST
       ▼
[15:35 IST] Post-Market Double-Entry Reconciliation & Tearsheet
       │  • Audits Cash + Cost Basis + Realized PnL + Fees + Slippage == Initial Equity
       │  • Dispatches EOD performance report via multi-channel webhooks
       ▼
[15:40 IST] Autonomous Quantitative Research Bot (EOD Cycle)
       │  • Classifies market regime (Bull, Bear, High-Vol Chop, Mean-Reverting Range)
       │  • Backtests 4 candidate strategies over rolling 60-day window
       │  • Discounts backtests using Deflated Sharpe Ratio (DSR, Bailey & López de Prado)
       │  • Enforces Robustness Gates (DSR ≥ 0.50, Profit Factor ≥ 1.10, Drawdown ≤ 12%)
       │  • Emits WAIT (0.0x risk) if no candidate passes gate
       │  • Writes decision manifest to data/decisions/decision_YYYYMMDD.json
       ▼
[16:00 IST] Database Maintenance
       │  • Executes SQLite WAL checkpoint and VACUUM
       ▼
[Standby Sleep] Off-Market Standby Mode
          • Engine sleeps cleanly with zero API spam until tomorrow 08:30 IST
```

---

## Institutional Safety & Fault-Tolerance Controls

1. **Network Connectivity Guard (`NetworkConnectivityGuard`)**: Low-latency WAN socket monitor. If connection drops, freezes all trade proposals, buffers alerts, and executes automatic 15:15 IST square-off upon recovery.
2. **Double-Entry Ledger Reconciler**: Mathematical proof of zero cash leakage across order fills, brokerage fees, and slippage.
3. **Whalley-Wilmott Asymptotic Hedging**: Non-linear no-trade bandwidth $H$ eliminating transaction churn during delta/gamma hedging.
4. **Static AST Isolation Scanner**: Pre-execution AST firewall intercepting unauthorized network sockets, subprocess spawns, or hardcoded secrets.
5. **Zerodha Kite Rate Limiter**: 3 req/sec sliding window rate limiter complying with broker API terms.

---

## Documentation Index

- [Oracle Cloud Infrastructure (OCI) Deployment Guide](docs/deployment/oracle_cloud_deployment.md)
- [Autonomous Zero-Intervention Engine Architecture](docs/architecture/autonomous_zero_intervention_engine.md)
- [Autonomous Quantitative Research & Decision Bot Specification](docs/architecture/autonomous_research_and_decision_bot.md)
- [Failure Modes, Root Causes & Institutional Remediations](docs/architecture/failure_modes_and_remediations.md)
