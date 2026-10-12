# Algo Lab — Autonomous Quantitative Research & Strategy Decision Bot

## 1. Executive Summary & Zero-Intervention Mandate
In strict compliance with **Principle 25 (Zero Live Capital Deployment During Research/Paper Testing)** and **Principle 1 & 2 (Never force a trade; WAIT is a valid decision)**, the **Autonomous Research Bot** eliminates human discretion and emotional bias from strategy selection.

Every trading day at **15:40 IST** (post-market close and after EOD double-entry reconciliation), the bot automatically executes:
1. **EOD Trading Audit & Regime Classification**: Evaluates today's paper fills, PnL, drawdowns, and classifies market regime over rolling 20/30-day benchmark data.
2. **Multi-Strategy Comparative Backtesting**: Evaluates 4 distinct quantitative strategies across the liquid NSE universe.
3. **Statistical Significance & DSR Ranking**: Discounts backtest results using the **Deflated Sharpe Ratio (Bailey & López de Prado, 2014)** to counteract selection bias under multiple testing.
4. **Autonomous Strategy Allocation Manifest**: Selects the robust candidate strategy or falls back to `WAIT`, persists the decision to disk (`data/decisions/decision_YYYYMMDD.json`), and broadcasts an alert via multi-channel webhooks.
5. **Next-Day Consumption**: At **08:30 IST**, the `AutonomousSentinel` pre-market routine ingests the manifest and loads the chosen strategy for the 09:15–15:15 IST paper trading session.

---

## 2. Market Regime Diagnostics
The research bot categorizes market regimes using rolling price action and volatility filters:
- **`TRENDING_BULL`**: 20-day return $> +3.0\%$ and annualized volatility $\le 35\%$.
- **`TRENDING_BEAR`**: 20-day return $< -3.0\%$ and annualized volatility $\le 35\%$.
- **`HIGH_VOLATILITY_CHOP`**: Annualized volatility $> 35\%$.
- **`MEAN_REVERTING_RANGE`**: Neutral drift within $[-3\%, +3\%]$ and normal volatility.

---

## 3. Candidate Strategy Universe
The bot runs comparative hourly backtests over a 60-day historical window across top liquid NSE constituents (`RELIANCE.NS`, `TCS.NS`, `INFY.NS`, `HDFCBANK.NS`, `ICICIBANK.NS`, `SBIN.NS`):

| Strategy ID | Methodology | Target Regime | Exit Rules |
| :--- | :--- | :--- | :--- |
| `STRAT_VWAP_REVERSION` | Buys below VWAP $- 1.5\sigma$ bands | Mean-Reverting Range | Mean cross or 2% stop-loss |
| `STRAT_EMA_MOMENTUM` | EMA 9 / EMA 21 bullish crossover | Trending Bull | Death cross or 2% stop-loss |
| `STRAT_DONCHIAN_BREAKOUT` | 20-period high breakout (channel trend) | Trending Strong | 20-period low cross or 3% stop |
| `STRAT_BOLLINGER_REVERSION` | Buys below SMA 20 $- 2.0\sigma$ lower band | Range / Mean-Reverting | SMA 20 touch or 1.5% stop-loss |

---

## 4. Institutional Robustness & Selection Gates
Raw Sharpe ratios suffer from severe selection bias when comparing multiple models (data snooping / survivorship bias). The Research Bot evaluates every backtest through the **Deflated Sharpe Ratio (DSR)**:

$$DSR = PSR(SR^*)$$

where $SR^*$ is the expected maximum Sharpe ratio under the null hypothesis of zero skill given $N=4$ trials and cross-trial variance $\sigma_{SR}^2$:

$$SR^* \approx \sqrt{V} \left((1 - \gamma) Z^{-1}\left(1 - \frac{1}{N}\right) + \gamma Z^{-1}\left(1 - \frac{1}{N \cdot e}\right)\right)$$

### Robustness Gate Criteria:
A strategy candidate is marked `is_robust = True` **only if all 3 gates pass**:
1. $\mathbf{DSR \ge 0.50}$ (Greater than 50% probability of true skill after trial deflation).
2. $\mathbf{\text{Profit Factor} \ge 1.10}$ ($\text{Gross Gains} / \text{Gross Losses} \ge 1.10$).
3. $\mathbf{\text{Max Drawdown} \le 12.0\%}$ (Intraday peak-to-trough decline within strict risk bounds).

If **no** candidate passes all three gates, the system outputs:
- **`selected_strategy: WAIT`**
- **`risk_multiplier: 0.0x`**
- **Principle 2 Enforced**: Zero trading capital risked until a statistically proven edge is identified.

---

## 5. Decision Manifest Specification
Manifests are written in JSON format to `data/decisions/decision_YYYYMMDD.json`:

```json
{
  "decision_date": "2026-10-12T14:30:48.523848+00:00",
  "target_session_date": "2026-10-13",
  "market_regime": "TRENDING_BEAR",
  "selected_strategy": "STRAT_BOLLINGER_REVERSION",
  "risk_multiplier": 1.0,
  "allocation_reason": "Selected STRAT_BOLLINGER_REVERSION based on DSR=1.00, PF=1.39, WinRate=58.5%, compatible with TRENDING_BEAR market regime.",
  "candidate_evaluations": [
    {
      "strategy": "STRAT_BOLLINGER_REVERSION",
      "trades_count": 41,
      "win_rate_pct": 58.5,
      "profit_factor": 1.39,
      "sharpe_ratio": 5.38,
      "dsr": 1.0,
      "max_drawdown_pct": 6.7,
      "is_robust": true
    }
  ],
  "eod_audit": {
    "date": "2026-10-12",
    "total_sessions": 1,
    "ending_equity": 50000.0,
    "realized_pnl": 0.0,
    "open_positions": 4,
    "market_regime": "TRENDING_BEAR"
  }
}
```

---

## 6. Execution Commands & Automation
The research engine can be invoked automatically or on demand:
- **Automated Trigger**: Called every day at `15:40 IST` by `run_live_paper_daemon.py` / `AutonomousSentinel`.
- **Manual CLI Runner**:
  ```bash
  python3 run_autonomous_research_bot.py
  ```
- **Webhook Dispatch**: Instant push alerts to configured Discord, Slack, or Telegram endpoints with the full evaluation summary.
