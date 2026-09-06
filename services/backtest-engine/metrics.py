"""Algo Lab Performance Metrics & Benchmark Engine.

Computes comprehensive statistical, risk-adjusted, and benchmark metrics:
- Returns: Total Return, CAGR
- Trades: Win Rate, Avg Win/Loss, Profit Factor, Expectancy, Max Consecutive Losses
- Risk: Max Drawdown, Max DD Duration, Sharpe, Sortino
- Friction: Total Fees, Slippage Impact
- Benchmarks: Buy & Hold Benchmark comparison, No-Trade baseline
- Regimes: Performance attribution by market regime
"""

import math
from datetime import datetime, timezone
from typing import Dict, List, Optional
import numpy as np
from pydantic import BaseModel, Field

from services.backtest_engine.contracts import BacktestMetrics, TradeRecord


class RegimePerformance(BaseModel):
    regime: str
    trades_count: int
    win_rate: float
    total_pnl: float
    profit_factor: float


class ComprehensiveBacktestMetrics(BaseModel):
    """Institutional-grade backtest performance metrics suite."""

    starting_capital: float
    ending_capital: float
    net_profit: float
    total_return_pct: float
    cagr_pct: Optional[float] = None

    # Trade Statistics
    number_of_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    average_win: float
    average_loss: float
    largest_win: float
    largest_loss: float
    profit_factor: float
    expectancy: float
    maximum_consecutive_losses: int

    # Risk Metrics
    maximum_drawdown_pct: float
    max_drawdown_duration_bars: int
    annualized_volatility_pct: float
    sharpe_ratio: float
    sortino_ratio: float

    # Trading Behavior & Friction
    average_holding_time_seconds: float
    exposure_pct: float
    portfolio_turnover: float
    total_transaction_costs: float
    total_slippage_impact: float
    worst_trade_pnl: float
    worst_day_pnl: float

    # Benchmarks
    buy_and_hold_return_pct: float
    buy_and_hold_sharpe: float
    alpha_over_buy_and_hold: float

    # Regime Segmentation
    regime_breakdown: List[RegimePerformance] = Field(default_factory=list)


class MetricsCalculator:
    """Computes all quantitative analytics on equity curves and trade records."""

    @staticmethod
    def compute_metrics(
        initial_capital: float,
        equity_curve: List[Dict],
        trades: List[TradeRecord],
        benchmark_prices: Optional[List[float]] = None,
        risk_free_rate: float = 0.065,  # 6.5% standard Indian RBI repo rate
    ) -> ComprehensiveBacktestMetrics:
        """Evaluates equity curve, trades, and benchmark series."""
        if not equity_curve:
            raise ValueError("Cannot compute metrics on empty equity curve.")

        ending_capital = float(equity_curve[-1]["equity"])
        net_profit = ending_capital - initial_capital
        total_return_pct = (net_profit / initial_capital) * 100.0

        # Calculate CAGR if multi-day period
        start_ts = datetime.fromisoformat(equity_curve[0]["timestamp"])
        end_ts = datetime.fromisoformat(equity_curve[-1]["timestamp"])
        days = max((end_ts - start_ts).total_seconds() / 86400.0, 1.0)
        years = days / 365.25

        if years >= 0.5 and ending_capital > 0:
            cagr_pct = ((ending_capital / initial_capital) ** (1.0 / years) - 1.0) * 100.0
        else:
            cagr_pct = None

        # Trade Statistics
        n_trades = len(trades)
        wins = [t for t in trades if t.net_pnl > 0]
        losses = [t for t in trades if t.net_pnl <= 0]

        n_wins = len(wins)
        n_losses = len(losses)
        win_rate = (n_wins / n_trades * 100.0) if n_trades > 0 else 0.0

        avg_win = float(np.mean([t.net_pnl for t in wins])) if n_wins > 0 else 0.0
        avg_loss = float(np.mean([t.net_pnl for t in losses])) if n_losses > 0 else 0.0
        largest_win = float(max([t.net_pnl for t in wins])) if n_wins > 0 else 0.0
        largest_loss = float(min([t.net_pnl for t in losses])) if n_losses > 0 else 0.0

        total_gross_wins = sum(t.net_pnl for t in wins)
        total_gross_losses = abs(sum(t.net_pnl for t in losses))

        if total_gross_losses > 0:
            profit_factor = total_gross_wins / total_gross_losses
        else:
            profit_factor = 99.0 if total_gross_wins > 0 else 1.0

        # Expectancy: (Win Rate * Avg Win) - (Loss Rate * |Avg Loss|)
        if n_trades > 0:
            p_win = n_wins / n_trades
            p_loss = n_losses / n_trades
            expectancy = (p_win * avg_win) - (p_loss * abs(avg_loss))
        else:
            expectancy = 0.0

        # Max consecutive losses
        max_consec_losses = 0
        curr_consec = 0
        for t in trades:
            if t.net_pnl <= 0:
                curr_consec += 1
                if curr_consec > max_consec_losses:
                    max_consec_losses = curr_consec
            else:
                curr_consec = 0

        # Equity Curve Analytics (Daily Returns & Drawdown)
        equities = np.array([pt["equity"] for pt in equity_curve])
        drawdowns = np.array([pt["drawdown_pct"] for pt in equity_curve])
        max_dd_pct = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0

        # Max Drawdown Duration (in bars)
        max_dd_dur = 0
        curr_dd_dur = 0
        for dd in drawdowns:
            if dd > 0.001:
                curr_dd_dur += 1
                if curr_dd_dur > max_dd_dur:
                    max_dd_dur = curr_dd_dur
            else:
                curr_dd_dur = 0

        # Returns series
        returns = np.diff(equities) / equities[:-1] if len(equities) > 1 else np.array([0.0])
        # Annualize Sharpe & Sortino (assuming ~252 trading days)
        # Factor for intraday / daily
        annual_factor = math.sqrt(252)
        mean_ret = float(np.mean(returns)) if len(returns) > 0 else 0.0
        std_ret = float(np.std(returns)) if len(returns) > 0 else 0.0
        daily_rf = (1.0 + risk_free_rate) ** (1.0 / 252.0) - 1.0

        if std_ret > 0:
            sharpe_ratio = ((mean_ret - daily_rf) / std_ret) * annual_factor
        else:
            sharpe_ratio = 0.0

        downside_returns = returns[returns < daily_rf] - daily_rf
        downside_dev = float(np.std(downside_returns)) if len(downside_returns) > 0 else 0.0
        if downside_dev > 0:
            sortino_ratio = ((mean_ret - daily_rf) / downside_dev) * annual_factor
        else:
            sortino_ratio = 0.0

        annualized_vol = std_ret * annual_factor * 100.0

        # Friction
        total_costs = float(sum(t.costs for t in trades))
        total_slippage = float(sum(t.slippage for t in trades))
        worst_trade = largest_loss

        # Daily PnL worst day
        worst_day = float(min(returns * initial_capital)) if len(returns) > 0 else 0.0

        # Average holding time and exposure
        holding_times = [t.holding_time_seconds for t in trades]
        avg_holding_time = float(np.mean(holding_times)) if holding_times else 0.0

        in_market_bars = sum(1 for pt in equity_curve if pt["open_positions"] > 0)
        exposure_pct = (in_market_bars / len(equity_curve) * 100.0) if equity_curve else 0.0

        turnover = float(sum(t.quantity * t.entry_price for t in trades))

        # Benchmark: Buy-and-Hold
        if benchmark_prices and len(benchmark_prices) > 1:
            p0 = benchmark_prices[0]
            pN = benchmark_prices[-1]
            bh_return = ((pN - p0) / p0) * 100.0
            bh_returns = np.diff(benchmark_prices) / benchmark_prices[:-1]
            bh_std = float(np.std(bh_returns)) if len(bh_returns) > 0 else 0.0
            bh_sharpe = (((float(np.mean(bh_returns)) - daily_rf) / bh_std) * annual_factor) if bh_std > 0 else 0.0
        else:
            bh_return = 0.0
            bh_sharpe = 0.0

        alpha = total_return_pct - bh_return

        # Regime Performance Attribution
        regimes_map: Dict[str, List[TradeRecord]] = {}
        for t in trades:
            reg = t.evidence_snapshot.get("market_regime", "NORMAL")
            regimes_map.setdefault(reg, []).append(t)

        regime_breakdown = []
        for reg_name, reg_trades in regimes_map.items():
            r_wins = sum(1 for t in reg_trades if t.net_pnl > 0)
            r_wr = (r_wins / len(reg_trades) * 100.0) if reg_trades else 0.0
            r_pnl = sum(t.net_pnl for t in reg_trades)
            r_g_win = sum(t.net_pnl for t in reg_trades if t.net_pnl > 0)
            r_g_loss = abs(sum(t.net_pnl for t in reg_trades if t.net_pnl <= 0))
            r_pf = (r_g_win / r_g_loss) if r_g_loss > 0 else (99.0 if r_g_win > 0 else 1.0)
            regime_breakdown.append(
                RegimePerformance(
                    regime=reg_name,
                    trades_count=len(reg_trades),
                    win_rate=round(r_wr, 2),
                    total_pnl=round(r_pnl, 2),
                    profit_factor=round(r_pf, 2),
                )
            )

        return ComprehensiveBacktestMetrics(
            starting_capital=round(initial_capital, 2),
            ending_capital=round(ending_capital, 2),
            net_profit=round(net_profit, 2),
            total_return_pct=round(total_return_pct, 4),
            cagr_pct=round(cagr_pct, 4) if cagr_pct is not None else None,
            number_of_trades=n_trades,
            winning_trades=n_wins,
            losing_trades=n_losses,
            win_rate=round(win_rate, 2),
            average_win=round(avg_win, 2),
            average_loss=round(avg_loss, 2),
            largest_win=round(largest_win, 2),
            largest_loss=round(largest_loss, 2),
            profit_factor=round(profit_factor, 2),
            expectancy=round(expectancy, 2),
            maximum_consecutive_losses=max_consec_losses,
            maximum_drawdown_pct=round(max_dd_pct, 4),
            max_drawdown_duration_bars=max_dd_dur,
            annualized_volatility_pct=round(annualized_vol, 2),
            sharpe_ratio=round(sharpe_ratio, 2),
            sortino_ratio=round(sortino_ratio, 2),
            average_holding_time_seconds=round(avg_holding_time, 1),
            exposure_pct=round(exposure_pct, 2),
            portfolio_turnover=round(turnover, 2),
            total_transaction_costs=round(total_costs, 2),
            total_slippage_impact=round(total_slippage, 2),
            worst_trade_pnl=round(worst_trade, 2),
            worst_day_pnl=round(worst_day, 2),
            buy_and_hold_return_pct=round(bh_return, 4),
            buy_and_hold_sharpe=round(bh_sharpe, 2),
            alpha_over_buy_and_hold=round(alpha, 4),
            regime_breakdown=regime_breakdown,
        )
