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

## Current Status: Stage 1 Foundation Complete

Stage 1 establishes the rock-solid architectural core, formal contracts, and safety barriers.
- [x] Directory structure with clear domain boundaries
- [x] FastAPI application with structured JSON logging and health probes
- [x] Next.js TypeScript web shell with clean quant design
- [x] Docker Compose with PostgreSQL 16
- [x] Pydantic settings with immutable safety validator (prohibits live trading)
- [x] Initial database models for experiments, decision audit (WAIT/REJECT), and trades
- [x] Core contracts for OHLCV, Data Quality Validator, Indicators, Strategy, Risk, Backtest, and Paper Broker
- [x] Full unit and contract test suite (14 passing tests)
- [x] GitHub Actions CI workflow
- [x] Architecture documentation

**Next Step**: Stage 2 (Data & Data Quality Engine).
