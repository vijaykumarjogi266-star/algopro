# Algo Lab — Formal Interface Contracts (Stage 1)

## 1. Data Contracts (`data/schemas/contracts.py`)

### `OHLCVBar`
- **Fields**:
  - `symbol`: string ticker
  - `exchange`: `NSE`, `BSE`, `MCX`
  - `timeframe`: `1m`, `3m`, `5m`, `15m`, `30m`, `1h`, `1d`, `1w`
  - `market_timestamp`: UTC datetime of the bar close
  - `open`, `high`, `low`, `close`: float prices (> 0)
  - `volume`: float volume (>= 0)
  - `turnover`: total INR traded value
  - `vwap`: Volume Weighted Average Price
  - `quality_status`: `VALID`, `SUSPECT`, `CORRUPTED`, `INCOMPLETE`, `REJECTED`
- **Invariants**:
  - `high >= max(open, close)`
  - `low <= min(open, close)`
  - `open, high, low, close > 0`
  - `is_usable_for_trading()` returns `False` if status is `CORRUPTED` or `REJECTED` or critical check failed.

---

## 2. Data Quality Validator (`services/data-quality/validator.py`)
- **Checks**:
  - Duplicate timestamp detection
  - Monotonic timestamp ordering (strict point-in-time guard)
  - Excessive stale bar sequences
  - Volume outlier anomalies
- **Enforcement**: Any critical failure flags `has_critical_failures=True` and sets `status=REJECTED`. The Strategy engine is prohibited from executing against rejected data series.

---

## 3. Indicator Contract (`quant/indicators/base.py`)
- **Base Class**: `IndicatorContract`
- **Principles Enforced**:
  - **Deterministic Output**: Always produces identical numerical series for identical inputs.
  - **Evidence-Only Rule**: Indicators produce evidentiary metrics (`get_evidence()`), never autonomous BUY/SELL execution directives.
  - **RSI Safeguard**: RSI indicates momentum regime and exhaustion, strictly barred from single-indicator trade triggers.

---

## 4. Strategy Contract (`quant/strategies/base.py`)
- **Base Class**: `BaseStrategy`
- **Method**: `evaluate(current_bar, history, data_quality) -> StrategyDecision`
- **Decision Payload (`StrategyDecision`)**:
  - `signal`: `BUY`, `SELL`, `WAIT`, `EXIT`
  - `confidence`: float between 0.0 and 1.0
  - `reason`: explainable narrative citing underlying evidence
  - `evidence`: dictionary snapshot of indicators at decision point
  - `stop_loss`: mandatory protective stop
- **Invariants**:
  - `WAIT` is treated as a first-class operational decision and logged.
  - Slicing of `history` must not contain any data points ahead of `current_bar.market_timestamp`.

---

## 5. Risk Engine Contract (`services/risk-engine/contracts.py`)
- **Interface**: `IRiskEngine`
- **Hard Guardrails (`HardRiskLimits`)**:
  - Max capital allocation per position: default 5%
  - Max portfolio drawdown ceiling: default 15% (circuit breaker)
  - Max daily loss limit: default 3% (session freeze)
  - Max open positions: default 10
  - Mandatory stop-loss: required on every proposed order
  - Leverage multiplier: locked at 1.0x (no margin borrowing in Stage 1)
- **Authority**: Decoupled from Strategy/Alpha. Neither strategy logic nor AI analysts can override hard limits.

---

## 6. Backtesting Contracts (`services/backtest-engine/contracts.py`)
- **Cost Model**: Realistic Indian market taxation and friction:
  - STT: 0.1% for equity delivery, 0.025% intraday
  - Brokerage: ₹20 / executed order
  - Exchange transaction charges: 0.00345%
  - GST: 18% on fees
  - Stamp duty: 0.015%
- **Metrics Suite**:
  - Total Return, CAGR, Win Rate, Profit Factor, Expectancy, Max Drawdown, Sharpe Ratio, Sortino Ratio, Exposure, Transaction Cost Impact, Worst Trade, Worst Day.
- **Reproducibility Contract (`ReproducibilityRecord`)**:
  - Stores Git commit hash, dataset version, strategy version, indicator parameters, cost config, slippage config, random seed, and cryptographic reproducibility hash.

---

## 7. Paper Trading Contract (`services/paper-engine/contracts.py`)
- **Interface**: `ISimulatedBroker`
- **Guarantee**: Isolated in-memory simulator. Zero communication with external broker APIs or real capital systems.
