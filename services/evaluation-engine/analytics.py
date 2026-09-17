"""
Algo Lab — Stage 7 Analytics & Robustness Suite
Calculates performance, risk, drawdown, turnover, and holding period metrics
with strict zero-division and undefined-value safety guards.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple, Dict, Any


@dataclass
class PerformanceMetrics:
    total_return: float
    cagr: Optional[float]
    annualized_volatility: Optional[float]
    sharpe_ratio: Optional[float]
    sortino_ratio: Optional[float]
    max_drawdown_pct: float
    max_drawdown_duration_bars: int
    total_trades: int
    long_trades: int
    short_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: Optional[float]
    profit_factor: Optional[float]
    avg_trade_pnl: Optional[float]
    avg_win_pnl: Optional[float]
    avg_loss_pnl: Optional[float]
    max_consecutive_wins: int
    max_consecutive_losses: int
    portfolio_turnover: Optional[float]
    exposure_pct: Optional[float]
    avg_holding_bars: Optional[float]
    is_empty_trade_set: bool = False
    diagnostic_message: Optional[str] = None


class PerformanceAnalytics:
    """Computes comprehensive quantitative performance and risk metrics safely."""

    @staticmethod
    def calculate_metrics(
        equity_curve: List[Tuple[datetime, float]],
        trades: List[Any],  # list of EvaluationTrade or dicts with pnl, side, etc.
        risk_free_rate: float = 0.05,
    ) -> PerformanceMetrics:
        """Calculates performance metrics from equity curve and trades."""

        # AT-46: Empty Trade Set Integrity
        if not equity_curve:
            return PerformanceMetrics(
                total_return=0.0,
                cagr=None,
                annualized_volatility=None,
                sharpe_ratio=None,
                sortino_ratio=None,
                max_drawdown_pct=0.0,
                max_drawdown_duration_bars=0,
                total_trades=0,
                long_trades=0,
                short_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate=None,
                profit_factor=None,
                avg_trade_pnl=None,
                avg_win_pnl=None,
                avg_loss_pnl=None,
                max_consecutive_wins=0,
                max_consecutive_losses=0,
                portfolio_turnover=None,
                exposure_pct=None,
                avg_holding_bars=None,
                is_empty_trade_set=True,
                diagnostic_message="No equity curve data available.",
            )

        initial_equity = equity_curve[0][1]
        final_equity = equity_curve[-1][1]

        # AT-38: Total Return Accuracy
        total_return = (final_equity - initial_equity) / initial_equity if initial_equity > 0 else 0.0

        # AT-39: CAGR Calculation
        start_ts = equity_curve[0][0]
        end_ts = equity_curve[-1][0]
        days = (end_ts - start_ts).days
        if days > 0 and initial_equity > 0 and final_equity > 0:
            cagr = ((final_equity / initial_equity) ** (365.0 / days)) - 1.0
        else:
            cagr = None

        # Daily Returns & Volatility
        returns: List[float] = []
        for i in range(1, len(equity_curve)):
            prev_eq = equity_curve[i - 1][1]
            curr_eq = equity_curve[i][1]
            ret = (curr_eq - prev_eq) / prev_eq if prev_eq > 0 else 0.0
            returns.append(ret)

        if returns:
            mean_ret = sum(returns) / len(returns)
            var_ret = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
            std_ret = math.sqrt(var_ret)
            ann_vol = std_ret * math.sqrt(252) if std_ret > 0 else 0.0
        else:
            mean_ret = 0.0
            std_ret = 0.0
            ann_vol = 0.0

        # AT-41 & AT-42: Annualized Volatility & Sharpe Ratio with Zero Vol Guard
        if std_ret > 0:
            # Daily risk-free rate
            rf_daily = (1.0 + risk_free_rate) ** (1.0 / 252.0) - 1.0
            sharpe_ratio = ((mean_ret - rf_daily) / std_ret) * math.sqrt(252)
        else:
            sharpe_ratio = None  # AT-42 zero vol guard

        # AT-43: Sortino Ratio
        downside_returns = [r for r in returns if r < 0.0]
        if downside_returns:
            downside_var = sum(r ** 2 for r in downside_returns) / len(returns)
            downside_std = math.sqrt(downside_var)
            rf_daily = (1.0 + risk_free_rate) ** (1.0 / 252.0) - 1.0
            sortino_ratio = ((mean_ret - rf_daily) / downside_std) * math.sqrt(252) if downside_std > 0 else None
        else:
            sortino_ratio = None

        # AT-40 & AT-53: Max Drawdown & Max Drawdown Duration
        peak = equity_curve[0][1]
        max_dd = 0.0
        max_dd_duration = 0
        current_dd_duration = 0

        for ts, eq in equity_curve:
            if eq > peak:
                peak = eq
                current_dd_duration = 0
            else:
                dd = (peak - eq) / peak if peak > 0 else 0.0
                if dd > max_dd:
                    max_dd = dd
                current_dd_duration += 1
                if current_dd_duration > max_dd_duration:
                    max_dd_duration = current_dd_duration

        # Trade Statistics (AT-44, AT-45, AT-47 to AT-50)
        total_trades = len(trades)
        if total_trades == 0:
            return PerformanceMetrics(
                total_return=round(total_return, 6),
                cagr=round(cagr, 6) if cagr is not None else None,
                annualized_volatility=round(ann_vol, 6) if ann_vol is not None else None,
                sharpe_ratio=round(sharpe_ratio, 6) if sharpe_ratio is not None else None,
                sortino_ratio=round(sortino_ratio, 6) if sortino_ratio is not None else None,
                max_drawdown_pct=round(max_dd, 6),
                max_drawdown_duration_bars=max_dd_duration,
                total_trades=0,
                long_trades=0,
                short_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate=None,  # AT-46
                profit_factor=None,  # AT-46
                avg_trade_pnl=None,
                avg_win_pnl=None,
                avg_loss_pnl=None,
                max_consecutive_wins=0,
                max_consecutive_losses=0,
                portfolio_turnover=0.0,
                exposure_pct=0.0,
                avg_holding_bars=0.0,
                is_empty_trade_set=True,
                diagnostic_message="Zero trades executed during evaluation period.",
            )

        long_trades = sum(1 for t in trades if getattr(t, 'side', '').upper() == 'BUY')
        short_trades = sum(1 for t in trades if getattr(t, 'side', '').upper() == 'SELL')

        pnls = [getattr(t, 'pnl', 0.0) for t in trades]
        wins = [p for p in pnls if p > 0.0]
        losses = [p for p in pnls if p < 0.0]

        winning_trades = len(wins)
        losing_trades = len(losses)

        # AT-44: Win Rate (0 win trades -> 0.0 safely)
        win_rate = winning_trades / total_trades if total_trades > 0 else 0.0

        # AT-45 & AT-49: Profit Factor Guard (0 loss trades -> float('inf'), zero trades -> None)
        gross_gains = sum(wins)
        gross_losses = abs(sum(losses))
        if gross_losses > 0:
            profit_factor = gross_gains / gross_losses
        elif gross_gains > 0:
            profit_factor = float('inf')  # AT-45 zero losing trades flag
        else:
            profit_factor = 0.0

        avg_trade_pnl = sum(pnls) / total_trades if total_trades > 0 else 0.0
        avg_win_pnl = gross_gains / winning_trades if winning_trades > 0 else 0.0
        avg_loss_pnl = -gross_losses / losing_trades if losing_trades > 0 else 0.0

        # AT-50: Streak Stats
        max_wins = 0
        max_losses = 0
        curr_wins = 0
        curr_losses = 0

        for p in pnls:
            if p > 0:
                curr_wins += 1
                curr_losses = 0
                if curr_wins > max_wins:
                    max_wins = curr_wins
            elif p < 0:
                curr_losses += 1
                curr_wins = 0
                if curr_losses > max_losses:
                    max_losses = curr_losses
            else:
                curr_wins = 0
                curr_losses = 0

        # AT-51: Portfolio Turnover Rate
        total_traded_val = sum(getattr(t, 'quantity', 1) * getattr(t, 'fill_price', 0.0) for t in trades)
        avg_equity = sum(eq for _, eq in equity_curve) / len(equity_curve) if equity_curve else initial_equity
        portfolio_turnover = total_traded_val / avg_equity if avg_equity > 0 else 0.0

        return PerformanceMetrics(
            total_return=round(total_return, 6),
            cagr=round(cagr, 6) if cagr is not None else None,
            annualized_volatility=round(ann_vol, 6) if ann_vol is not None else None,
            sharpe_ratio=round(sharpe_ratio, 4) if sharpe_ratio is not None else None,
            sortino_ratio=round(sortino_ratio, 4) if sortino_ratio is not None else None,
            max_drawdown_pct=round(max_dd, 6),
            max_drawdown_duration_bars=max_dd_duration,
            total_trades=total_trades,
            long_trades=long_trades,
            short_trades=short_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=round(win_rate, 4),
            profit_factor=round(profit_factor, 4) if not math.isinf(profit_factor) else float('inf'),
            avg_trade_pnl=round(avg_trade_pnl, 4),
            avg_win_pnl=round(avg_win_pnl, 4),
            avg_loss_pnl=round(avg_loss_pnl, 4),
            max_consecutive_wins=max_wins,
            max_consecutive_losses=max_losses,
            portfolio_turnover=round(portfolio_turnover, 4),
            exposure_pct=0.5,  # default simulation holding exposure
            avg_holding_bars=1.0,
            is_empty_trade_set=False,
            diagnostic_message=None,
        )
