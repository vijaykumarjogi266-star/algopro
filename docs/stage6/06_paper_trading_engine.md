# Algo Lab Stage 6 — Paper Trading Engine & Portfolio Tracking

## 1. Overview
The `PaperTradingEngine` manages isolated, real-time simulated trading sessions. It maintains realistic portfolio accounting, tracks positions, applies mark-to-market valuations, and ensures that simulated executions behave according to institutional financial principles without real capital exposure.

---

## 2. Session Lifecycle States

```
   ┌───────────┐
   │  CREATED  │
   └─────┬─────┘
         │ start()
         ▼
   ┌───────────┐  pause()   ┌───────────┐
   │  RUNNING  ├───────────▶│   PAUSED  │
   └─────┬─────┤◀───────────┤           │
         │     │  start()   └───────────┘
         │ stop()
         ▼
   ┌───────────┐
   │  STOPPED  │
   └───────────┘
```

Sessions support:
- Multiple concurrent instances across different strategies or instrument universes.
- Persisting state, orders, and fills to SQLite using thread-safe `RLock`.

---

## 3. Financial Accounting Invariants

The `PaperPortfolio` model satisfies fundamental quantitative accounting equalities at all times:

1. **Total Liquidation Equity**:
   $$\text{Total Equity} = \text{Cash Balance} + \sum_{i} (\text{Quantity}_i \times \text{Current Price}_i)$$

2. **PnL & Friction Consistency**:
   $$\text{Total Equity} = \text{Starting Capital} + \text{Realized PnL} + \text{Unrealized PnL} - \text{Total Fees Paid}$$

3. **Position Averaging**:
   When scaling into an existing position, the new average entry price is computed:
   $$\bar{P}_{\text{new}} = \frac{\text{Previous Cost Basis} + (Q_{\text{fill}} \times P_{\text{fill}})}{Q_{\text{previous}} + Q_{\text{fill}}}$$

---

## 4. Mark-to-Market Valuation

Upon processing every new market data bar:
- Position `current_price` updates to the bar's `close`.
- Position `unrealized_pnl` recalculates.
- Portfolio peak equity and drawdown are tracked continuously.
