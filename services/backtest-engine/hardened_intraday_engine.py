"""
Hardened Intraday Event-Driven Replay & Portfolio Backtesting Engine.
Phase C Hardening Guarantees:
1. Strict Point-in-Time causality: Bar t-1 closes -> Signal generated -> Filled at Bar t Open.
2. Conservative Intra-Candle Collision: If both SL and TP are touched in the same bar, SL is hit first.
3. Zero Lookahead: Indicators strictly calculated on historical bars up to t-1.
4. Portfolio-level Capital and Risk Management:
   - Initial Capital: ₹100,000
   - Fixed Fractional Risk: 1% risk per trade
   - Hard Max Trades per Day: Enforced (Vikram Prabhu 2 trades/day rule)
   - Slippage Model: 0.05% adverse slippage on every fill
   - Statutory Indian MIS Fees: IndianStatutoryCostModel (brokerage + STT + turnover + GST + stamp)
   - Mandatory MIS Square-Off: 15:15 IST
5. Safety:
   - Strictly Paper Trading Only. Live orders denied.
"""

from dataclasses import dataclass
from datetime import datetime, time, date
from decimal import Decimal
from typing import Dict, List, Optional, Set, Tuple, Any
import numpy as np
import pandas as pd

# Mandatory safety enforcement
ALLOW_LIVE_TRADING = False
ALLOW_REAL_BROKER_EXECUTION = False
REAL_MONEY_RISK_PAISE = 0
PAPER_BROKER_ONLY = True

from services.backtest_engine.statutory_cost_model import (
    IndianStatutoryCostModel,
    OrderLeg,
    ProductType,
)


@dataclass
class Position:
    symbol: str
    entry_time: datetime
    entry_price: float
    qty: int
    stop_loss: float
    target: float
    initial_risk: float
    entry_friction: float
    breakeven_activated: bool = False


@dataclass
class ClosedTrade:
    symbol: str
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    qty: int
    stop_loss: float
    target: float
    exit_reason: str
    gross_pnl: float
    friction: float
    net_pnl: float
    return_pct: float
    holding_minutes: float
    is_win: bool


@dataclass
class FilterConfig:
    name: str = "default"
    min_rvol: float = 1.5           # Minimum relative volume
    require_daily_trend: bool = False # Require Daily Close > 20 EMA
    min_risk_reward: float = 0.0    # Minimum R:R ratio feasibility (e.g. 2.0)
    allowed_entry_start: time = time(9, 45)
    allowed_entry_end: time = time(13, 30)
    max_trades_per_day: int = 999   # Daily trade quota (e.g. 2)
    use_trailing_breakeven: bool = False # Move SL to breakeven at +1R
    slippage_pct: float = 0.0005     # 5 bps adverse slippage


class HardenedIntradaySimulator:
    """High-performance chronological portfolio backtester."""

    def __init__(
        self,
        symbol_data: Dict[str, pd.DataFrame],
        daily_trends: Dict[str, Dict[date, bool]],
        initial_capital: float = 100000.0,
        risk_per_trade_pct: float = 0.010,
        filter_config: Optional[FilterConfig] = None,
    ):
        assert not ALLOW_LIVE_TRADING, "SAFETY VIOLATION"
        assert PAPER_BROKER_ONLY, "SAFETY VIOLATION"

        self.initial_capital = initial_capital
        self.risk_per_trade_pct = risk_per_trade_pct
        self.config = filter_config or FilterConfig()
        self.daily_trends = daily_trends
        self.hard_exit_time = time(15, 15)

        # Pre-process all symbols into fast dicts keyed by (timestamp, symbol)
        self.bar_lookup: Dict[Tuple[datetime, str], Dict[str, float]] = {}
        self.timestamp_symbols: Dict[datetime, List[str]] = {}
        all_ts = set()

        for sym, df in symbol_data.items():
            dt_series = df['Datetime'].tolist()
            opens = df['Open'].tolist()
            highs = df['High'].tolist()
            lows = df['Low'].tolist()
            closes = df['Close'].tolist()
            vols = df['Volume'].tolist()
            r1s = df['R1'].tolist()
            r2s = df['R2'].tolist()
            vol_smas = df['Vol_SMA_20'].tolist()

            for i in range(len(dt_series)):
                ts = dt_series[i]
                all_ts.add(ts)
                if ts not in self.timestamp_symbols:
                    self.timestamp_symbols[ts] = []
                self.timestamp_symbols[ts].append(sym)

                self.bar_lookup[(ts, sym)] = {
                    'open': float(opens[i]),
                    'high': float(highs[i]),
                    'low': float(lows[i]),
                    'close': float(closes[i]),
                    'volume': float(vols[i]),
                    'r1': float(r1s[i]) if not pd.isna(r1s[i]) else np.nan,
                    'r2': float(r2s[i]) if not pd.isna(r2s[i]) else np.nan,
                    'vol_sma': float(vol_smas[i]) if not pd.isna(vol_smas[i]) else np.nan,
                }

        self.sorted_timestamps = sorted(list(all_ts))

    def run(self, start_date: Optional[date] = None, end_date: Optional[date] = None) -> Tuple[List[ClosedTrade], Dict[str, any]]:
        closed_trades: List[ClosedTrade] = []
        open_positions: Dict[str, Position] = {}
        daily_trades_count: Dict[date, int] = {}
        pending_entries: Dict[str, dict] = {}

        for current_ts in self.sorted_timestamps:
            current_date = current_ts.date()
            if start_date and current_date < start_date:
                continue
            if end_date and current_date > end_date:
                continue

            current_time = current_ts.time()
            if current_date not in daily_trades_count:
                daily_trades_count[current_date] = 0

            # 1. EXECUTE PENDING ENTRIES AT BAR OPEN WITH SLIPPAGE
            for sym, order in list(pending_entries.items()):
                if sym in open_positions:
                    continue
                bar_key = (current_ts, sym)
                if bar_key not in self.bar_lookup:
                    continue

                bar = self.bar_lookup[bar_key]
                raw_open = bar['open']
                fill_price = raw_open * (1.0 + self.config.slippage_pct)

                sl_price = order['stop_loss']
                tp_price = order['target']
                stop_dist = fill_price - sl_price
                if stop_dist <= 0:
                    continue

                risk_amt = self.initial_capital * self.risk_per_trade_pct
                qty = int(risk_amt / stop_dist)
                max_qty = int(45000.0 / fill_price)
                qty = max(1, min(qty, max_qty))

                entry_fric = IndianStatutoryCostModel.calculate_order_friction(
                    leg=OrderLeg.BUY,
                    price=Decimal(str(round(fill_price, 2))),
                    quantity=qty,
                    product=ProductType.INTRADAY
                )

                open_positions[sym] = Position(
                    symbol=sym,
                    entry_time=current_ts,
                    entry_price=fill_price,
                    qty=qty,
                    stop_loss=sl_price,
                    target=tp_price,
                    initial_risk=stop_dist,
                    entry_friction=float(entry_fric.all_in_total_friction)
                )
                daily_trades_count[current_date] += 1

            pending_entries.clear()

            # 2. EVALUATE EXITS ON CURRENT BAR
            for sym, pos in list(open_positions.items()):
                bar_key = (current_ts, sym)
                if bar_key not in self.bar_lookup:
                    continue

                bar = self.bar_lookup[bar_key]
                high = bar['high']
                low = bar['low']
                close = bar['close']

                if self.config.use_trailing_breakeven and not pos.breakeven_activated:
                    if high >= pos.entry_price + pos.initial_risk:
                        pos.stop_loss = pos.entry_price
                        pos.breakeven_activated = True

                exit_reason = None
                exit_price = 0.0

                if current_time >= self.hard_exit_time:
                    exit_reason = "HARD_EXIT_15_15"
                    exit_price = close * (1.0 - self.config.slippage_pct)
                elif low <= pos.stop_loss and high >= pos.target:
                    # Conservative collision rule: hit SL first
                    exit_reason = "STOP_LOSS_COLLISION"
                    exit_price = pos.stop_loss * (1.0 - self.config.slippage_pct)
                elif low <= pos.stop_loss:
                    exit_reason = "STOP_LOSS"
                    exit_price = pos.stop_loss * (1.0 - self.config.slippage_pct)
                elif high >= pos.target:
                    exit_reason = "TAKE_PROFIT"
                    exit_price = pos.target * (1.0 - self.config.slippage_pct)

                if exit_reason:
                    exit_fric = IndianStatutoryCostModel.calculate_order_friction(
                        leg=OrderLeg.SELL,
                        price=Decimal(str(round(exit_price, 2))),
                        quantity=pos.qty,
                        product=ProductType.INTRADAY
                    )
                    total_fric = pos.entry_friction + float(exit_fric.all_in_total_friction)
                    gross_pnl = (exit_price - pos.entry_price) * pos.qty
                    net_pnl = gross_pnl - total_fric
                    holding_mins = (current_ts - pos.entry_time).total_seconds() / 60.0

                    closed_trades.append(ClosedTrade(
                        symbol=sym,
                        entry_time=pos.entry_time,
                        exit_time=current_ts,
                        entry_price=round(pos.entry_price, 2),
                        exit_price=round(exit_price, 2),
                        qty=pos.qty,
                        stop_loss=round(pos.stop_loss, 2),
                        target=round(pos.target, 2),
                        exit_reason=exit_reason,
                        gross_pnl=round(gross_pnl, 2),
                        friction=round(total_fric, 2),
                        net_pnl=round(net_pnl, 2),
                        return_pct=round((exit_price - pos.entry_price) / pos.entry_price * 100.0, 3),
                        holding_minutes=holding_mins,
                        is_win=net_pnl > 0
                    ))
                    del open_positions[sym]

            # 3. SCAN SIGNALS ON CLOSED BAR t FOR NEXT BAR OPEN
            if not (self.config.allowed_entry_start <= current_time <= self.config.allowed_entry_end):
                continue
            if daily_trades_count[current_date] >= self.config.max_trades_per_day:
                continue

            available_symbols = self.timestamp_symbols.get(current_ts, [])
            for sym in available_symbols:
                if sym in open_positions or sym in pending_entries:
                    continue
                bar = self.bar_lookup.get((current_ts, sym))
                if not bar:
                    continue

                close = bar['close']
                low = bar['low']
                vol = bar['volume']
                r1 = bar['r1']
                r2 = bar['r2']
                vol_sma = bar['vol_sma']

                if np.isnan(r1) or np.isnan(vol_sma) or vol_sma == 0:
                    continue
                if close <= r1:
                    continue

                # RVOL Filter
                rvol = vol / vol_sma
                if rvol < self.config.min_rvol:
                    continue

                # Daily Trend Confluence Filter
                if self.config.require_daily_trend:
                    sym_daily = self.daily_trends.get(sym, {})
                    if not sym_daily.get(current_date, False):
                        continue

                sl = low
                risk_dist = close - sl
                if risk_dist <= 0:
                    continue

                reward_dist = r2 - close
                implied_rr = reward_dist / risk_dist if risk_dist > 0 else 0

                if self.config.min_risk_reward > 0:
                    if implied_rr < self.config.min_risk_reward:
                        target = close + (self.config.min_risk_reward * risk_dist)
                    else:
                        target = r2
                else:
                    target = r2

                pending_entries[sym] = {
                    "stop_loss": sl,
                    "target": target,
                    "signal_time": current_ts,
                }
                
                # Check if daily limit reached during this bar's signals
                if daily_trades_count[current_date] + len(pending_entries) >= self.config.max_trades_per_day:
                    break

        summary = self._compute_summary(closed_trades)
        return closed_trades, summary

    def _compute_summary(self, trades: List[ClosedTrade]) -> Dict[str, any]:
        total_trades = len(trades)
        if total_trades == 0:
            return {
                "total_trades": 0, "win_rate_pct": 0.0, "net_pnl": 0.0,
                "gross_pnl": 0.0, "total_friction": 0.0, "profit_factor": 0.0,
                "max_drawdown": 0.0, "max_drawdown_pct": 0.0, "expectancy": 0.0
            }

        df = pd.DataFrame([t.__dict__ for t in trades])
        wins = df[df['net_pnl'] > 0]
        losses = df[df['net_pnl'] <= 0]

        gross_pnl = df['gross_pnl'].sum()
        total_fric = df['friction'].sum()
        net_pnl = df['net_pnl'].sum()
        win_rate = (len(wins) / total_trades) * 100.0

        gross_wins = wins['gross_pnl'].sum()
        gross_losses = abs(losses['gross_pnl'].sum())
        pf = round(gross_wins / gross_losses, 3) if gross_losses > 0 else 999.0

        df['cum_pnl'] = df['net_pnl'].cumsum()
        df['peak'] = df['cum_pnl'].cummax()
        df['dd'] = df['cum_pnl'] - df['peak']
        max_dd = abs(df['dd'].min())
        max_dd_pct = (max_dd / self.initial_capital) * 100.0

        return {
            "total_trades": total_trades,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate_pct": round(win_rate, 2),
            "gross_pnl": round(gross_pnl, 2),
            "total_friction": round(total_fric, 2),
            "net_pnl": round(net_pnl, 2),
            "profit_factor": pf,
            "expectancy": round(net_pnl / total_trades, 2),
            "max_drawdown": round(max_dd, 2),
            "max_drawdown_pct": round(max_dd_pct, 2),
            "avg_holding_minutes": round(df['holding_minutes'].mean(), 1) if not df.empty else 0.0,
        }
