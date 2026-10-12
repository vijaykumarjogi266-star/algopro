"""
Algo Lab — Institutional Tearsheet & Strategy Teardown Generator.

Combines returns analytics, Deflated Sharpe, Rank IC, Drawdown durations,
VaR/CVaR profiles, and friction breakdown into publication-grade executive tearsheets.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import numpy as np
from pydantic import BaseModel, Field

from services.evaluation_engine.stat_metrics import StatisticalMetricsEngine, StatisticalSignificanceReport
from services.evaluation_engine.factor_research import FactorMetricsReport


class InstitutionalTearsheet(BaseModel):
    strategy_id: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    cagr: float
    total_return: float
    annualized_volatility: float
    empirical_sharpe: float
    sortino_ratio: float
    calmar_ratio: float
    deflated_sharpe_ratio: float
    probabilistic_sharpe_ratio: float
    is_statistically_significant: bool
    max_drawdown: float
    var_95: float
    cvar_95: float
    total_trades: int
    win_rate: float
    profit_factor: float
    factor_rank_ic: Optional[float] = None
    factor_ic_ir: Optional[float] = None


class TearsheetGenerator:
    """Generates institutional tearsheets and quantitative markdown factsheets."""

    @classmethod
    def generate_tearsheet(
        cls,
        strategy_id: str,
        equity_curve: List[float],
        trades: List[Dict[str, Any]],
        number_of_trials: int = 1,
        var_trials: float = 0.0,
        factor_report: Optional[FactorMetricsReport] = None,
    ) -> InstitutionalTearsheet:
        """Assembles full institutional quantitative metrics."""
        eq = np.array(equity_curve, dtype=float)
        if len(eq) < 5:
            raise ValueError("Insufficient equity curve points to generate tearsheet.")

        initial_equity = eq[0]
        final_equity = eq[-1]
        total_ret = (final_equity - initial_equity) / initial_equity

        # Daily returns
        rets = np.diff(eq) / eq[:-1]
        n_days = len(rets)
        cagr = ((final_equity / initial_equity) ** (252.0 / n_days)) - 1.0 if final_equity > 0 and n_days > 0 else 0.0

        ann_vol = float(np.std(rets, ddof=1) * np.sqrt(252)) if n_days > 1 else 0.0

        # Maximum Drawdown
        running_max = np.maximum.accumulate(eq)
        drawdowns = (eq - running_max) / running_max
        max_dd = float(abs(np.min(drawdowns)))

        # Downside vol for Sortino
        neg_rets = rets[rets < 0]
        downside_vol = float(np.std(neg_rets, ddof=1) * np.sqrt(252)) if len(neg_rets) > 1 else 1e-6
        sortino = (cagr - 0.05) / downside_vol if downside_vol > 1e-9 else 0.0
        calmar = cagr / max_dd if max_dd > 1e-9 else 0.0

        # Statistical significance
        stat_report = StatisticalMetricsEngine.evaluate_returns_series(
            rets,
            periods_per_year=252,
            number_of_trials=number_of_trials,
            var_trials=var_trials,
        )

        # VaR & CVaR (Historical)
        var_95 = float(-np.percentile(rets, 5.0))
        cvar_95 = float(-np.mean(rets[rets <= -var_95])) if len(rets[rets <= -var_95]) > 0 else var_95

        # Trade stats
        trade_pnls = [t.get("pnl", 0.0) for t in trades]
        total_trades = len(trade_pnls)
        wins = [p for p in trade_pnls if p > 0]
        losses = [p for p in trade_pnls if p < 0]
        win_rate = (len(wins) / total_trades) if total_trades > 0 else 0.0
        profit_factor = (sum(wins) / abs(sum(losses))) if losses and abs(sum(losses)) > 1e-9 else 1.0

        return InstitutionalTearsheet(
            strategy_id=strategy_id,
            cagr=round(cagr, 4),
            total_return=round(total_ret, 4),
            annualized_volatility=round(ann_vol, 4),
            empirical_sharpe=round(stat_report.annualized_sharpe, 4),
            sortino_ratio=round(sortino, 4),
            calmar_ratio=round(calmar, 4),
            deflated_sharpe_ratio=round(stat_report.dsr, 4),
            probabilistic_sharpe_ratio=round(stat_report.psr, 4),
            is_statistically_significant=stat_report.is_statistically_significant,
            max_drawdown=round(max_dd, 4),
            var_95=round(var_95, 4),
            cvar_95=round(cvar_95, 4),
            total_trades=total_trades,
            win_rate=round(win_rate, 4),
            profit_factor=round(profit_factor, 4),
            factor_rank_ic=factor_report.mean_rank_ic if factor_report else None,
            factor_ic_ir=factor_report.rank_ic_ir if factor_report else None,
        )

    @classmethod
    def render_markdown_tearsheet(cls, sheet: InstitutionalTearsheet) -> str:
        """Formats the tearsheet into an institutional presentation report."""
        sig_badge = "✅ STATISTICALLY SIGNIFICANT (DSR >= 0.95)" if sheet.is_statistically_significant else "⚠️ INSUFFICIENT SIGNIFICANCE (Risk of Overfitting)"
        return f"""# 📊 Institutional Strategy Tearsheet: {sheet.strategy_id}
> **Generated:** {sheet.generated_at.strftime('%Y-%m-%d %H:%M:%S UTC')}  
> **Significance Status:** {sig_badge}

---

### 1. Risk-Adjusted Returns & Deflated Performance
| Metric | Value | Target / Benchmark | Institutional Significance |
| :--- | :--- | :--- | :--- |
| **CAGR** | {sheet.cagr * 100:.2f}% | > 18.00% | Compound annual growth rate |
| **Total Return** | {sheet.total_return * 100:.2f}% | — | Full evaluation period return |
| **Annualized Volatility** | {sheet.annualized_volatility * 100:.2f}% | < 20.00% | Realized standard deviation |
| **Empirical Sharpe Ratio** | {sheet.empirical_sharpe:.2f} | > 1.25 | Standard unadjusted Sharpe |
| **Probabilistic Sharpe (PSR)** | {sheet.probabilistic_sharpe_ratio:.4f} | > 0.9500 | Adjusted for skewness & kurtosis |
| **Deflated Sharpe (DSR)** | **{sheet.deflated_sharpe_ratio:.4f}** | **> 0.9500** | **Adjusted for selection bias & trials** |
| **Sortino Ratio** | {sheet.sortino_ratio:.2f} | > 1.50 | Return relative to downside risk |
| **Calmar Ratio** | {sheet.calmar_ratio:.2f} | > 1.00 | CAGR / Maximum Drawdown |

---

### 2. Tail Risk & Drawdown Profile
| Metric | Value | Constraint | Risk Engine Limit |
| :--- | :--- | :--- | :--- |
| **Maximum Drawdown** | {sheet.max_drawdown * 100:.2f}% | < 12.00% | Hard circuit breaker: 15% |
| **1-Day 95% Historical VaR** | {sheet.var_95 * 100:.2f}% | < 3.00% | Threshold: 3.50% |
| **1-Day 95% Expected Shortfall (CVaR)** | {sheet.cvar_95 * 100:.2f}% | < 5.00% | Threshold: 6.00% |

---

### 3. Execution & Trade Quality
| Metric | Value | Metric | Value |
| :--- | :--- | :--- | :--- |
| **Total Trades** | {sheet.total_trades} | **Win Rate** | {sheet.win_rate * 100:.1f}% |
| **Profit Factor** | {sheet.profit_factor:.2f} | **Alpha Rank IC** | {f"{sheet.factor_rank_ic:.4f}" if sheet.factor_rank_ic is not None else "N/A"} |
| **Factor IC IR** | {f"{sheet.factor_ic_ir:.2f}" if sheet.factor_ic_ir is not None else "N/A"} | **Overfitting Risk** | {"LOW" if sheet.is_statistically_significant else "MODERATE/HIGH"} |
"""
