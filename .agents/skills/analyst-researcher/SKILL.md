---
name: analyst-researcher
description: >-
  Quantitative Financial Analyst & Market Data Research Skill for backtesting validation,
  dataset provenance verification, risk engine policy enforcement, causality checking,
  and multi-day ledger accounting.
---

# Quantitative Analyst & Market Data Research Skill

## Core Principles
1. **Strict Provenance & Checksum Verification**: Every backtest and market data simulation must run against registered, immutably checksummed datasets. No ad-hoc synthetic bar generation in production/backtest pipelines.
2. **Causality & Lookahead Prevention**: Orders and executions must maintain strict intrabar causality. Bar open executions precede bar high/low stop valuations.
3. **Double-Entry Economic Accounting**: Fills, fees, and slippages must obey strict balance sheet invariants. Slippage is an execution quality metric, not a double cash deduction.
4. **Independent Benchmark vs Executable Policy**: Benchmarks (e.g. Buy & Hold) must state their explicit asset weights and cash reserves, while active strategies strictly adhere to hard risk limits.
