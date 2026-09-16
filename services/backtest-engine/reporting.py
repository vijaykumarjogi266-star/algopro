"""Algo Lab Research Report Generator.

Adheres to Non-Negotiable Principles:
- Principle 18: All trading decisions must be explainable through evidence.
- Principle 19: Performance must be evaluated after realistic costs and slippage.
- Principle 20: Optimize for robustness, not maximum historical return.
"""

from typing import Dict, Any, List
from services.backtest_engine.contracts import BacktestResult, BacktestMetrics


class BacktestReportGenerator:
    """Generates research reports and executive markdown summaries."""

    @staticmethod
    def generate_markdown_report(result: BacktestResult, audit_trail: List[Dict[str, Any]]) -> str:
        rep = result.reproducibility
        met = result.metrics

        md = [
            f"# Algo Lab Research Report: `{rep.experiment_id}`",
            f"**Commit:** `{rep.git_commit[:7]}` | **Strategy Version:** `{rep.strategy_version}` | **Hash:** `{rep.reproducibility_hash[:12]}...`",
            "",
            "## 1. Performance Summary",
            f"- **Total Return:** `{met.total_return_pct:.2f}%` (CAGR: `{met.cagr_pct:.2f}%`)" if met.cagr_pct else f"- **Total Return:** `{met.total_return_pct:.2f}%`",
            f"- **Sharpe Ratio:** `{met.sharpe_ratio:.2f}` | **Sortino Ratio:** `{met.sortino_ratio:.2f}`",
            f"- **Maximum Drawdown:** `{met.maximum_drawdown_pct:.2f}%`",
            f"- **Trades Executed:** {met.number_of_trades} (Win Rate: `{met.win_rate*100:.1f}%`)",
            f"- **Profit Factor:** `{met.profit_factor:.2f}` | **Expectancy:** INR {met.expectancy:,.2f}",
            "",
            "## 2. Realistic Friction Breakdown",
            f"- **Total Transaction Costs:** INR {met.total_transaction_costs:,.2f}",
            f"- **Total Slippage Impact:** INR {met.total_slippage_impact:,.2f}",
            f"- **Rejected Orders:** {result.rejected_trades_count}",
            f"- **WAIT Decisions:** {result.wait_decisions_count}",
            "",
            "## 3. Governance & Audit Verification",
            f"- **Audit Trail Event Count:** {len(audit_trail)} event(s) captured.",
            f"- **Dataset Version:** `{rep.dataset_version}`",
            f"- **Random Seed:** `{rep.random_seed}`",
        ]

        # Rejection breakdown
        rejections = [e for e in audit_trail if e["event_type"] == "RISK_REJECT"]
        if rejections:
            md.append("\n### Risk Rejection Details:")
            for r in rejections[:5]:
                md.append(f"- `[{r['timestamp']}]` {r['payload'].get('reason', 'Policy violation')}")

        return "\n".join(md)
