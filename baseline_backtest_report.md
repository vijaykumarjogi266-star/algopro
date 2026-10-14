# Baseline Backtest Report: Intraday Pivot Breakout Strategy (MIS)

**Task Workspace**: `/opt/ai-builder/workspaces/TASK-INTRA-SCAN-01/algolab`  
**Execution Timestamp**: 2026-10-11  
**Status**: Gate B Reproducible Baseline Established (VERIFIED)  
**Safety Mandate**: Strictly Paper Trading Only (`ALLOW_LIVE_TRADING=false`, `REAL_MONEY_RISK_PAISE=0`)

---

## 1. Executive Summary & Objective

The objective of Phase B is to establish a strictly reproducible, scientifically honest baseline for the existing intraday equity trading strategy before attempting modifications. 

The baseline strategy executes classical Floor Pivot Breakouts on 5-minute bars across the Nifty 50 universe with MIS intraday statutory costs applied on every fill.

### Key Headline Metrics

| Metric | Baseline Value | Interpretation |
| :--- | :--- | :--- |
| **Initial Capital** | ₹100,000.00 | Standard retail paper capital base |
| **Backtest Horizon** | 2026-07-16 to 2026-10-09 (~60 trading days) | 5-minute bar frequency |
| **Total Trades Executed** | **1,327** | Severe over-trading (~22.1 trades/day) |
| **Win Rate** | **23.51%** (312 Wins / 1,015 Losses) | Strategy fails 3 out of 4 times |
| **Gross P&L** | **₹-4,033.30** | Unprofitable before costs |
| **Statutory Friction (Brokerage + Taxes)** | **₹61,549.11** | Massive churn friction |
| **Net Realized P&L** | **₹-65,582.41** | **-65.58% account destruction** |
| **Profit Factor** | **0.951** | Gross wins fail to cover gross losses |
| **Net Expectancy per Trade** | **₹-49.42** | Every signal loses ₹49.42 on average |
| **Maximum Drawdown** | **₹66,651.72 (66.65%)** | Unacceptable risk of ruin |
| **Average Holding Duration** | **80.4 minutes** | Trades hold ~1.3 hours before failing |

---

## 2. Dataset & Universe Specification

- **Universe**: Nifty 50 constituent equities (50 symbols) managed via `Nifty50UniverseManager`.
- **Bar Timeframe**: 5-Minute (M5) OHLCV candles.
- **Cache Storage**: Parquet snapshots in `/opt/ai-builder/workspaces/TASK-INTRA-SCAN-01/algolab/data/cache_intraday_5m/`.
- **Total Bars Analyzed**: 219,660 5-minute bars (average 4,393.2 bars per symbol).
- **Data Quality & Continuity Audit**:
  - Missing File Count: 0 (all 50 symbols successfully cached).
  - NaN Price Bars: 0 detected across all symbols.
  - Zero-Volume Bars: Confined to pre-market / exchange test ticks, filtered automatically.
  - Timestamps: Fully localized to Asia/Kolkata (`+05:30`).

---

## 3. Statutory Cost & Friction Modeling

All simulations use `IndianStatutoryCostModel` enforcing exact Zerodha Equity Intraday MIS fee structures:
1. **Brokerage**: Flat ₹20 per executed order leg.
2. **STT (Securities Transaction Tax)**: 0.025% on Sell turnover.
3. **Exchange Turnover Charges (NSE)**: 0.00345% on Buy + Sell turnover.
4. **GST**: 18% on (Brokerage + Exchange Charges + SEBI Charges).
5. **SEBI Charges**: ₹10 per crore (0.0001%).
6. **Stamp Duty**: 0.003% on Buy turnover.

On 1,327 trades (2,654 executed order legs), total statutory friction amounted to **₹61,549.11**, averaging **₹46.38 per round-trip trade**.

---

## 4. In-Depth Performance Breakdown

### 4.1. Exit Reason Attribution

| Exit Reason | Trades | % of Total | Win Rate | Net P&L (₹) |
| :--- | :--- | :--- | :--- | :--- |
| **STOP_LOSS** | 918 | 69.18% | 0.0% | ₹-122,887.02 |
| **TAKE_PROFIT (R2)** | 305 | 22.98% | 82.95% | ₹+50,090.65 |
| **HARD_EXIT_15_15** | 104 | 7.84% | 56.73% | ₹+7,213.96 |
| **Total** | **1,327** | **100.0%** | **23.51%** | **₹-65,582.41** |

### 4.2. Performance by Time of Day (Entry Time)

| Time Window (IST) | Trades Executed | Win Rate | Gross P&L (₹) | Total Friction (₹) | Net P&L (₹) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **09:45 – 10:30** | 259 | 23.17% | ₹-5,233.64 | ₹12,018.00 | ₹-17,251.64 |
| **10:30 – 11:30** | 341 | 27.27% | ₹+3,168.05 | ₹15,816.17 | ₹-12,648.12 |
| **11:30 – 12:30** | 379 | 22.43% | ₹+661.62 | ₹17,592.46 | ₹-16,930.84 |
| **12:30 – 13:30** | 348 | 21.26% | ₹-2,629.33 | ₹16,122.48 | ₹-18,751.81 |

> **Key Observation**: Mid-day breakouts (11:30 to 13:30) suffered the highest churn and lowest win rates (21.26%–22.43%), generating ₹34,714 in friction alone.

### 4.3. Performance by Day of Week

| Day of Week | Trades | Win Rate | Net P&L (₹) |
| :--- | :--- | :--- | :--- |
| **Monday** | 303 | 22.77% | ₹-12,959.94 |
| **Tuesday** | 200 | 26.00% | ₹-9,976.00 |
| **Wednesday** | 246 | 23.58% | ₹-12,513.79 |
| **Thursday** (Expiry) | 269 | 23.05% | ₹-17,323.58 |
| **Friday** | 309 | 22.98% | ₹-12,809.10 |

All weekdays exhibited severe net losses. Thursday (weekly derivatives expiry) experienced the deepest drawdown (₹-17,323.58) due to heightened intraday chop.

### 4.4. Symbol Extremes (Best vs. Worst Constituents)

- **Top 5 Constituents**:
  1. `GRASIM`: ₹+1,809.46 (Win Rate: 33.3%)
  2. `INDIGO`: ₹+704.38 (Win Rate: 30.8%)
  3. `SBILIFE`: ₹+595.72 (Win Rate: 29.2%)
  4. `ADANIENT`: ₹+569.82 (Win Rate: 28.0%)
  5. `HDFCLIFE`: ₹+521.59 (Win Rate: 31.8%)

- **Bottom 5 Constituents**:
  1. `TECHM`: ₹-3,821.94 (Win Rate: 16.7%)
  2. `COALINDIA`: ₹-3,331.32 (Win Rate: 18.2%)
  3. `M&M`: ₹-2,926.82 (Win Rate: 17.6%)
  4. `JIOFIN`: ₹-2,871.59 (Win Rate: 19.4%)
  5. `BAJAJ-AUTO`: ₹-2,759.60 (Win Rate: 20.0%)

---

## 5. Root-Cause Analysis of Strategy Failure

1. **Absence of Higher Timeframe (Daily) Trend Filter**:
   - The baseline strategy enters long breakouts on 5-minute bars even when the stock is in a confirmed daily downtrend below its 20 EMA, fighting institutional selling pressure.
2. **Terrible Risk-to-Reward Ratio on Fixed R1/R2 Targets**:
   - In classical floor pivots, R2 is often only 0.2%–0.5% above R1, while the stop-loss (placed at the entry candle low) is often 0.8%–1.5% away. This creates an inverted R:R (e.g. 0.3:1), directly violating Vikram Prabhu's explicit rule of maintaining $\ge 1:2$ profit-to-loss ratio.
3. **Severe Over-trading & Churn Friction**:
   - By taking every breakout without a daily limit, the system averaged 22 trades per day. Vikram Prabhu Chapter 8 explicitly dictates: *"Have a rule of not trading more than 2 trades/day. Shut down the system after 2 trades irrespective of profit or loss."*
4. **Execution Bias & Optimistic Collision Bug**:
   - The baseline engine filled entries at bar close rather than next bar open.
   - When High $\ge$ Target and Low $\le$ Stop Loss on the same bar, the baseline optimistically credited Take Profit first.

---

## 6. Audit Trail & Machine-Readable Artifacts

The following machine-readable audit artifacts are saved in `/opt/ai-builder/workspaces/TASK-INTRA-SCAN-01/algolab/artifacts/`:
- `baseline_metrics.json` — Aggregated metrics and performance statistics.
- `baseline_trades.csv` — Full trade logs for all 1,327 trades with timestamps, fill prices, and fees.
- `baseline_trades.json` — JSON format of executed trades.
- `baseline_scanner_rejections.json` — Sample of 1,000 candidate rejections with reasons.
- `data_quality_report.json` — Parquet data quality verification across all 50 symbols.
