# Algo Lab — System Architecture Overview

## 1. Project Definition
Algo Lab is a professional quantitative investment and trading research operating system specifically designed for Indian markets (NSE, BSE, MCX).

**Algo Lab is NOT an AI trading bot.**

It is a systematic research and decision platform prioritizing:
> **Capital Preservation → Data Integrity → Research Integrity → Risk Management → Execution Quality → Performance**

---

## 2. Core Architectural Principles
1. **Never force a trade**: A trading model should only act when statistically significant confluence exists.
2. **WAIT is a valid decision**: Inaction during adverse regimes preserves capital.
3. **Bad or uncertain data must not produce a trading decision**: Failed quality checks abort signal evaluation immediately.
4. **No look-ahead bias**: Temporal bar slicing is strictly point-in-time.
5. **No data leakage**: Indicators and transformations must never incorporate future statistics.
6. **No survivorship bias**: Historical universes must account for delisted and suspended instruments.
7. **Every backtest must be reproducible**: Git commit, dataset hash, indicator version, and parameters are permanently recorded.
8. **Every strategy must be versioned**: Strategy contracts declare immutable semver tags.
9. **Every dataset must be versioned**: Raw and processed data partitions carry deterministic version tags.
10. **Every experiment must be auditable**: Inputs, outputs, and rejected decisions are persisted in PostgreSQL.
11. **Indicators are evidence, not automatic trading decisions**: Raw indicators are contextual signals, not execution triggers.
12. **RSI must never independently generate BUY/SELL decisions**: Oversold/overbought thresholds are momentum states, not automated orders.
13. **Multiple correlated indicators must not be treated as independent evidence**: Confluence must be structurally orthogonal.
14. **Risk Engine must remain independent from Strategy/Alpha**: Strategies cannot override portfolio or asset-level risk parameters.
15. **AI must never override hard risk controls**: Circuit breakers and drawdown limits are immutable code invariants.
16. **AI must never silently modify production strategies**: Human approval and versioned pull requests are strictly required.
17. **AI must never directly control unrestricted order execution**: All orders flow through validated risk barriers.
18. **All trading decisions must be explainable through evidence**: Decisions log quantitative evidence snapshots.
19. **Performance must be evaluated after realistic costs and slippage**: STT, exchange fees, SEBI charges, GST, stamp duty, and slippage are mandatory.
20. **Optimize for robustness, not maximum historical return**: Curve-fitting is actively penalized.
21. **Evaluate portfolio-level risk, not only individual trades**: Correlation risk, factor exposure, and drawdown clustering are assessed.
22. **Record rejected trades, WAIT decisions and missed opportunities**: Negative feedback is crucial for model calibration.
23. **Simple UI; sophisticated engineering underneath**: Clean web dashboard exposing deep quant plumbing.
24. **Reliability is more important than feature count**: Determinism and stability take absolute precedence.
25. **No live capital deployment during initial development stages**: Live broker order transmission is hard-disabled.

---

## 3. High-Level System Architecture

```
                                  [ Data Sources (NSE/BSE) ]
                                              │
                                              ▼
                                 [ Data Quality Engine ]
                                  ├── Missing Check
                                  ├── Duplicate Check
                                  ├── Monotonicity Check
                                  └── OHLC/Volume Sanity
                                              │
                                      (Pass / Reject)
                                              │
                                              ▼
                                [ Quant Indicators Library ]
                                  ├── Deterministic Math (Polars/NumPy)
                                  └── Evidence Extractors (No auto BUY/SELL)
                                              │
                                              ▼
                                    [ Strategy Framework ]
                                  ├── BaseStrategy Contract
                                  ├── Signal Generation (BUY/SELL/WAIT/EXIT)
                                  └── Explainable Reason & Snapshot
                                              │
                                              ▼
                                   [ Independent Risk Engine ]
                                  ├── Hard Portfolio Drawdown Limit (15%)
                                  ├── Daily Stop Loss (3%)
                                  ├── Max Capital per Trade (5%)
                                  └── Mandatory Stop Loss
                                              │
                                      (Approve / Block)
                                              │
                         ┌────────────────────┴────────────────────┐
                         ▼                                         ▼
                [ Backtest Engine ]                       [ Paper Trading Engine ]
           ├── Historical Point-in-Time             ├── Simulated In-Memory Broker
           ├── Realistic Cost Models (STT/GST)      ├── Realistic Fill & Slippage
           └── Reproducibility Hash & Metrics       └── Virtual Balance & P&L
                         │                                         │
                         └────────────────────┬────────────────────┘
                                              │
                                              ▼
                                 [ PostgreSQL / Audit Log ]
                                  ├── Experiment Records
                                  ├── Decision Records (WAIT / REJECT)
                                  └── Trade Records
                                              │
                                              ▼
                                [ Next.js Web Shell / API ]
                                  └── Simple UI for Quant Research
```

---

## 4. Master 15-Stage Roadmap
- **Stage 1: Foundation (CURRENT)**: Base directory structure, FastAPI app, Next.js web shell, PostgreSQL config, contracts (Data, Indicators, Strategy, Risk, Backtest, Paper).
- **Stage 2: Data & Data Quality**: Multi-timeframe historical loaders, corporate actions adjustment, tick streaming.
- **Stage 3: Indicators & Quant Library**: Full suite of mathematical indicators, factor libraries, statistical tests.
- **Stage 4: Backtesting Engine**: Event-driven simulation engine, multi-asset portfolio backtests, vector execution.
- **Stage 5: Strategy Framework**: Production strategies (ORB, VWAP Reversion, Trend Pullback), regime detection.
- **Stage 6: Research & Validation**: Walk-forward validation, Monte Carlo simulations, combinatorial cross-validation.
- **Stage 7: Paper Trading**: Live tick ingestion, real-time paper matching, live order simulation.
- **Stage 8: Market Intelligence**: Market breadth, FII/DII institutional flows, sector rotation.
- **Stage 9: Opportunity & Proof**: Real-time scanner, setup scoring, evidence attribution.
- **Stage 10: Portfolio & Risk**: Modern portfolio theory, Black-Litterman, CVaR, risk parity.
- **Stage 11: Options Lab**: Option pricing models, Greeks, volatility smile, margin calculation.
- **Stage 12: Intraday & Expiry**: Expiry-day 0DTE models, gamma scalping, pin risk hedging.
- **Stage 13: AI Research Analyst**: RAG over quantitative filings, explainability engine, strategy diagnostics.
- **Stage 14: Execution & Operations**: Smart order routing, TWAP/VWAP algorithms, reconciliation.
- **Stage 15: Oracle Production & Scale**: High-availability clustering, failover, disaster recovery.
