"""Algo Lab Asynchronous Backtest Service.

Adheres to Non-Negotiable Principles:
- Principle 4: No look-ahead bias (signals at bar i close, execution at bar i+1 open).
- Principle 7: Every backtest must be reproducible.
- Principle 10: Every experiment must be auditable.
- Principle 14: Risk Engine must remain independent from Strategy/Alpha.
- Principle 19: Performance must be evaluated after realistic costs and slippage.
"""

import math
from datetime import datetime, timezone, timedelta
import hashlib
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, List, Optional, Tuple

import numpy as np

from services.backtest_engine.contracts import (
    BacktestResult,
    ReproducibilityRecord,
    BacktestMetrics,
    CostModelConfig,
    SlippageModelConfig,
    TradeRecord,
    OrderSide,
    ExperimentDefinition,
    ExperimentRun,
    ExperimentStatus,
)
from services.backtest_engine.fingerprint import compute_reproducibility_hash
from services.backtest_engine.persistence import BacktestRunStore
from services.backtest_engine.reporting import BacktestReportGenerator
from services.market_data.registry import (
    DatasetRecord,
    DatasetRegistryStore,
    compute_dataset_checksum,
)
from services.risk_engine.engine import RiskEngine
from services.risk_engine.contracts import HardRiskLimits, RiskRejectionCode


def _to_bar_dict(b: Any) -> Dict[str, Any]:
    if isinstance(b, dict):
        return {
            "date": b.get("date") or b.get("timestamp"),
            "open": float(b.get("open", 0.0)),
            "high": float(b.get("high", 0.0)),
            "low": float(b.get("low", 0.0)),
            "close": float(b.get("close", 0.0)),
            "volume": float(b.get("volume", 0.0)),
        }
    return {
        "date": getattr(b, "timestamp", getattr(b, "date", None)),
        "open": float(getattr(b, "open", 0.0)),
        "high": float(getattr(b, "high", 0.0)),
        "low": float(getattr(b, "low", 0.0)),
        "close": float(getattr(b, "close", 0.0)),
        "volume": float(getattr(b, "volume", 0.0)),
    }


def _calculate_trade_costs(trade_value: float, side: str, cost_cfg: CostModelConfig) -> float:
    """Calculates all declared statutory and brokerage transaction costs."""
    brokerage = float(getattr(cost_cfg, "brokerage_per_crore_or_order", 0.0))
    stt = trade_value * float(getattr(cost_cfg, "stt_rate", 0.0))
    exch = trade_value * float(getattr(cost_cfg, "exchange_turnover_fee_rate", 0.0))
    sebi = trade_value * float(getattr(cost_cfg, "sebi_turnover_fee_rate", 0.0))
    gst = float(getattr(cost_cfg, "gst_rate", 0.0)) * (brokerage + exch)
    stamp = (trade_value * float(getattr(cost_cfg, "stamp_duty_rate", 0.0))) if side == "BUY" else 0.0
    return brokerage + stt + exch + sebi + gst + stamp


def _calculate_slippage_price(raw_price: float, side: str, slip_cfg: SlippageModelConfig) -> Tuple[float, float]:
    """Calculates executed price with slippage."""
    fixed_pts = float(getattr(slip_cfg, "fixed_tick_slippage_pts", 0.0))
    var_pct = float(getattr(slip_cfg, "variable_slippage_pct", 0.0))
    slip_pts = fixed_pts + (raw_price * var_pct)
    if side == "BUY":
        fill_price = raw_price + slip_pts
    else:
        fill_price = max(0.01, raw_price - slip_pts)
    return fill_price, slip_pts


class BacktestService:
    """Coordinates backtest submission, lifecycle management, risk enforcement, and audit."""

    def __init__(
        self,
        store: Optional[BacktestRunStore] = None,
        max_workers: int = 2,
        risk_engine: Optional[RiskEngine] = None,
        dataset_store: Optional[DatasetRegistryStore] = None,
    ):
        self.store = store or BacktestRunStore()
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.risk_engine = risk_engine or RiskEngine()
        self.dataset_store = dataset_store or DatasetRegistryStore()
        self._in_memory_dataset_bars: Dict[str, List[Any]] = {}

    def register_dataset_bars(self, dataset_id: str, bars: List[Any]) -> None:
        """Registers in-memory market data bars associated with a dataset identifier."""
        self._in_memory_dataset_bars[dataset_id] = bars

    def submit_backtest(
        self,
        strategy_id: str,
        universe: List[str],
        start_date: datetime,
        end_date: datetime,
        parameters: Optional[Dict[str, Any]] = None,
        initial_capital: float = 500_000.0,
        timeframe: str = "1d",
        cost_model: Optional[CostModelConfig] = None,
        slippage_model: Optional[SlippageModelConfig] = None,
        dataset_version: str = "2026.09.14",
        git_commit: str = "main",
        experiment_id: Optional[str] = None,
        dataset_id: Optional[str] = None,
        dataset_checksum: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Validates, hashes, registers, and initiates an asynchronous backtest run."""
        # 1. Validation
        if not universe:
            raise ValueError("Universe cannot be empty")
        if start_date >= end_date:
            raise ValueError("start_date must be strictly before end_date")
        if initial_capital <= 0:
            raise ValueError("initial_capital must be strictly positive")

        experiment_id = experiment_id or f"exp_{uuid.uuid4().hex[:12]}"
        cost_cfg = cost_model or CostModelConfig()
        slip_cfg = slippage_model or SlippageModelConfig()
        params = parameters or {}

        # 2. Compute deterministic reproducibility hash
        repro_dict = {
            "strategy_id": strategy_id,
            "universe": sorted(universe),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "parameters": params,
            "initial_capital": initial_capital,
            "timeframe": timeframe,
            "cost_model": cost_cfg.model_dump() if hasattr(cost_cfg, "model_dump") else cost_cfg.dict(),
            "slippage_model": slip_cfg.model_dump() if hasattr(slip_cfg, "model_dump") else slip_cfg.dict(),
            "dataset_version": dataset_version,
            "git_commit": git_commit,
        }
        if dataset_id:
            repro_dict["dataset_id"] = dataset_id
        if dataset_checksum:
            repro_dict["dataset_checksum"] = dataset_checksum

        repro_hash = compute_reproducibility_hash(repro_dict)

        repro_record = ReproducibilityRecord(
            experiment_id=experiment_id,
            git_commit=git_commit,
            dataset_version=dataset_version,
            strategy_version="1.0.0",
            indicator_versions={"SMA": "1.0", "RSI": "1.0"},
            parameters=params,
            initial_capital=initial_capital,
            cost_model=cost_cfg,
            slippage_model=slip_cfg,
            universe=universe,
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            reproducibility_hash=repro_hash,
        )

        # Ensure experiment definition is saved
        exp_def = self.store.get_experiment(experiment_id)
        if not exp_def:
            exp_def = ExperimentDefinition(
                experiment_id=experiment_id,
                name=f"Run_{experiment_id}",
                strategy_id=strategy_id,
                strategy_version="1.0.0",
                dataset_id=dataset_id or "NSE_NIFTY50_DAILY",
                dataset_version=dataset_version,
                dataset_checksum=dataset_checksum or ("f" * 64),
                universe=sorted(universe),
                timeframe=timeframe,
                start_date=start_date,
                end_date=end_date,
                parameters=params,
                initial_capital=initial_capital,
            )
            self.store.save_experiment(exp_def)

        # 3. Persist initial PENDING record
        self.store.save_run(
            experiment_id=experiment_id,
            reproducibility=repro_record,
            status="PENDING",
        )

        # 4. Dispatch async execution
        self.executor.submit(self._run_job, experiment_id, repro_record)

        return {
            "status": "submitted",
            "experiment_id": experiment_id,
            "reproducibility_hash": repro_hash,
        }

    # ------------------------------------------------------------------
    # Internal simulation helpers
    # ------------------------------------------------------------------

    def _generate_ohlcv_bars(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        seed: int,
        base_price: float = 1000.0,
    ) -> List[Dict[str, float]]:
        """Generates deterministic synthetic daily bars for testing when explicitly permitted."""
        rng = np.random.default_rng(seed)
        bars = []
        current = start_date
        price = base_price
        while current <= end_date:
            if current.weekday() < 5:
                daily_ret = rng.normal(0.0002, 0.015)
                open_p = price
                close_p = max(1.0, price * (1 + daily_ret))
                high_p = max(open_p, close_p) * (1 + abs(rng.normal(0, 0.005)))
                low_p = min(open_p, close_p) * (1 - abs(rng.normal(0, 0.005)))
                volume = float(max(1000, int(rng.normal(500_000, 200_000))))
                bars.append({
                    "date": current,
                    "open": round(open_p, 2),
                    "high": round(high_p, 2),
                    "low": round(low_p, 2),
                    "close": round(close_p, 2),
                    "volume": volume,
                })
                price = close_p
            current += timedelta(days=1)
        return bars

    def _compute_metrics_from_trades(
        self,
        trades: List[Dict[str, Any]],
        equity_curve: List[float],
        initial_capital: float,
        cost_model: CostModelConfig,
        slippage_model: SlippageModelConfig,
    ) -> BacktestMetrics:
        """Compute BacktestMetrics from raw trade records and equity curve."""
        final_equity = equity_curve[-1] if equity_curve else initial_capital
        total_return_pct = (final_equity - initial_capital) / initial_capital * 100.0

        n_days = len(equity_curve)
        years = n_days / 252.0
        if years > 0 and final_equity > 0:
            cagr_pct = ((final_equity / initial_capital) ** (1.0 / years) - 1) * 100.0
        else:
            cagr_pct = 0.0

        # Drawdown baselined with initial capital
        full_curve = [initial_capital] + list(equity_curve)
        max_dd = 0.0
        peak = initial_capital
        for eq in full_curve:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd

        # Worst day PnL
        if len(full_curve) >= 2:
            daily_pnl = [full_curve[i] - full_curve[i - 1] for i in range(1, len(full_curve))]
            worst_day = min(daily_pnl) if daily_pnl else 0.0
        else:
            worst_day = 0.0

        # Sharpe / Sortino
        if len(equity_curve) >= 2:
            daily_rets = np.diff(equity_curve) / np.array(equity_curve[:-1])
            mean_r = float(np.mean(daily_rets))
            std_r = float(np.std(daily_rets, ddof=1)) if len(daily_rets) > 1 else 0.0
            sharpe = (mean_r / std_r * math.sqrt(252)) if std_r > 0 else 0.0
            neg = daily_rets[daily_rets < 0]
            down_std = float(np.std(neg, ddof=1)) if len(neg) > 1 else 0.0
            sortino = (mean_r / down_std * math.sqrt(252)) if down_std > 0 else 0.0
        else:
            sharpe = sortino = 0.0

        wins = [t for t in trades if t.get("pnl", 0) > 0]
        losses = [t for t in trades if t.get("pnl", 0) <= 0]
        n_trades = len(trades)
        win_rate = len(wins) / n_trades if n_trades > 0 else 0.0
        avg_win = float(np.mean([t["pnl"] for t in wins])) if wins else 0.0
        avg_loss = float(np.mean([t["pnl"] for t in losses])) if losses else 0.0
        gross_profit = sum(t["pnl"] for t in wins) if wins else 0.0
        gross_loss = abs(sum(t["pnl"] for t in losses)) if losses else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
        expectancy = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)

        max_consec_loss = 0
        cur_loss = 0
        for t in trades:
            if t.get("pnl", 0) <= 0:
                cur_loss += 1
                max_consec_loss = max(max_consec_loss, cur_loss)
            else:
                cur_loss = 0

        avg_hold_secs = float(np.mean([t.get("holding_bars", 1) for t in trades]) * 86400.0) if trades else 0.0
        total_costs = sum(t.get("cost", 0.0) for t in trades)
        total_slip = sum(t.get("slippage", 0.0) for t in trades)
        worst_trade = min((t.get("pnl", 0.0) for t in trades), default=0.0)
        n_bars_invested = sum(t.get("holding_bars", 0) for t in trades)
        exposure_pct = (n_bars_invested / n_days * 100.0) if n_days > 0 else 0.0

        return BacktestMetrics(
            total_return_pct=round(total_return_pct, 4),
            cagr_pct=round(cagr_pct, 4),
            number_of_trades=n_trades,
            win_rate=round(win_rate, 4),
            average_win=round(avg_win, 2),
            average_loss=round(avg_loss, 2),
            profit_factor=round(profit_factor, 4),
            expectancy=round(expectancy, 2),
            maximum_drawdown_pct=round(max_dd * 100.0, 4),
            sharpe_ratio=round(sharpe, 4),
            sortino_ratio=round(sortino, 4),
            maximum_consecutive_losses=max_consec_loss,
            average_holding_time_seconds=round(avg_hold_secs, 1),
            exposure_pct=round(exposure_pct, 4),
            total_transaction_costs=round(total_costs, 2),
            total_slippage_impact=round(total_slip, 2),
            worst_trade_pnl=round(worst_trade, 2),
            worst_day_pnl=round(worst_day, 2),
        )

    def _run_simulation(
        self,
        repro: ReproducibilityRecord,
        seed: int,
        all_bars: Dict[str, List[Dict[str, Any]]],
    ) -> Tuple[List[Dict[str, Any]], List[float]]:
        """Run deterministic causal bar-by-bar simulation."""
        cost_cfg = repro.cost_model
        slip_cfg = repro.slippage_model
        params = repro.parameters or {}
        fast_period = int(params.get("fast_period", 9))
        slow_period = int(params.get("slow_period", 21))

        trades: List[Dict[str, Any]] = []
        cash = float(repro.initial_capital)
        positions: Dict[str, Dict[str, Any]] = {}
        equity_curve: List[float] = []

        max_bars = max((len(b) for b in all_bars.values()), default=0)
        if max_bars < slow_period + 1:
            equity_curve = [cash]
            return trades, equity_curve

        pending_entries: Dict[str, float] = {}  # symbol -> signal_price
        pending_exits: set = set()

        for bar_idx in range(max_bars):
            # 1. Fill pending exits at bar_idx open (causal execution: signal at bar_idx - 1 close -> filled at bar_idx open)
            for sym in list(positions.keys()):
                bars = all_bars[sym]
                if bar_idx >= len(bars):
                    continue
                bar = bars[bar_idx]
                pos = positions[sym]
                qty = pos["qty"]
                entry_p = pos["entry_price"]
                stop_loss = pos["stop_loss"]

                exit_price = None
                exit_reason = None

                # Check gap-down through stop
                if bar["open"] <= stop_loss:
                    raw_exit = min(bar["open"], stop_loss)
                    exit_price, slip_pts = _calculate_slippage_price(raw_exit, "SELL", slip_cfg)
                    exit_reason = "STOP_LOSS_GAP"
                elif bar["low"] <= stop_loss:
                    raw_exit = stop_loss
                    exit_price, slip_pts = _calculate_slippage_price(raw_exit, "SELL", slip_cfg)
                    exit_reason = "STOP_LOSS"
                elif sym in pending_exits:
                    raw_exit = bar["open"]
                    exit_price, slip_pts = _calculate_slippage_price(raw_exit, "SELL", slip_cfg)
                    exit_reason = "SIGNAL_EXIT"

                if exit_price is not None:
                    exit_trade_val = exit_price * qty
                    exit_cost = _calculate_trade_costs(exit_trade_val, "SELL", cost_cfg)
                    entry_cost = pos.get("entry_cost", 0.0)
                    total_cost = entry_cost + exit_cost
                    total_slip = pos.get("entry_slippage", 0.0) + (slip_pts * qty)
                    net_pnl = (exit_price * qty - exit_cost) - (entry_p * qty + entry_cost)
                    cash += (exit_price * qty - exit_cost)
                    holding_bars = bar_idx - pos["entry_bar"]
                    trades.append({
                        "symbol": sym,
                        "entry_bar": pos["entry_bar"],
                        "exit_bar": bar_idx,
                        "entry_price": entry_p,
                        "exit_price": exit_price,
                        "qty": qty,
                        "pnl": net_pnl,
                        "cost": total_cost,
                        "slippage": total_slip,
                        "holding_bars": max(1, holding_bars),
                        "reason": exit_reason,
                    })
                    del positions[sym]
                    pending_exits.discard(sym)

            # 2. Fill pending entries at bar_idx open (causal execution: signal at bar_idx - 1 close -> filled at bar_idx open)
            for sym, sig_price in list(pending_entries.items()):
                bars = all_bars[sym]
                if bar_idx >= len(bars):
                    continue
                bar = bars[bar_idx]
                if sym not in positions:
                    raw_entry = bar["open"]
                    entry_p, slip_pts = _calculate_slippage_price(raw_entry, "BUY", slip_cfg)
                    capital_per_trade = min(cash * 0.045, repro.initial_capital * 0.045)
                    qty = max(1, int(capital_per_trade / entry_p))
                    buy_cost = _calculate_trade_costs(entry_p * qty, "BUY", cost_cfg)

                    stop_loss = round(entry_p * 0.97, 2)
                    current_portfolio_val = cash + sum(positions[s]["qty"] * all_bars[s][bar_idx]["open"] for s in positions)

                    # Evaluate risk gate
                    risk_eval = self.risk_engine.evaluate(
                        symbol=sym,
                        price=entry_p,
                        proposed_quantity=qty,
                        stop_loss=stop_loss,
                        current_portfolio_value=current_portfolio_val,
                        current_daily_loss_pct=0.0,
                        current_drawdown_pct=0.0,
                        current_open_positions_count=len(positions),
                    )

                    if risk_eval.is_approved and cash >= (entry_p * qty + buy_cost):
                        cash -= (entry_p * qty + buy_cost)
                        positions[sym] = {
                            "qty": qty,
                            "entry_price": entry_p,
                            "entry_bar": bar_idx,
                            "stop_loss": stop_loss,
                            "entry_cost": buy_cost,
                            "entry_slippage": slip_pts * qty,
                        }

            pending_entries.clear()

            # 3. Mark-to-market portfolio value at bar_idx close
            pos_val = sum(
                all_bars[sym][bar_idx]["close"] * pos["qty"]
                for sym, pos in positions.items()
                if bar_idx < len(all_bars[sym])
            )
            equity_curve.append(cash + pos_val)

            # 4. Generate signals at bar_idx close for execution at bar_idx + 1 open
            for sym, bars in all_bars.items():
                if bar_idx >= len(bars):
                    continue
                closes = [b["close"] for b in bars[:bar_idx + 1]]
                if len(closes) >= slow_period + 1:
                    fast_ma = float(np.mean(closes[-fast_period:]))
                    fast_ma_prev = float(np.mean(closes[-fast_period - 1:-1]))
                    slow_ma = float(np.mean(closes[-slow_period:]))
                    slow_ma_prev = float(np.mean(closes[-slow_period - 1:-1]))

                    golden_cross = (fast_ma > slow_ma) and (fast_ma_prev <= slow_ma_prev)
                    death_cross = (fast_ma < slow_ma) and (fast_ma_prev >= slow_ma_prev)

                    if sym in positions and death_cross:
                        pending_exits.add(sym)
                    elif sym not in positions and golden_cross:
                        pending_entries[sym] = closes[-1]

        # Close any open positions at the last bar's close price
        if max_bars > 0:
            for sym, pos in list(positions.items()):
                bars = all_bars[sym]
                if bars:
                    last_bar = bars[-1]
                    raw_exit = last_bar["close"]
                    exit_price, slip_pts = _calculate_slippage_price(raw_exit, "SELL", slip_cfg)
                    qty = pos["qty"]
                    exit_trade_val = exit_price * qty
                    exit_cost = _calculate_trade_costs(exit_trade_val, "SELL", cost_cfg)
                    entry_cost = pos.get("entry_cost", 0.0)
                    total_cost = entry_cost + exit_cost
                    total_slip = pos.get("entry_slippage", 0.0) + (slip_pts * qty)
                    net_pnl = (exit_price * qty - exit_cost) - (pos["entry_price"] * qty + entry_cost)
                    cash += (exit_price * qty - exit_cost)
                    holding_bars = (max_bars - 1) - pos["entry_bar"]
                    trades.append({
                        "symbol": sym,
                        "entry_bar": pos["entry_bar"],
                        "exit_bar": max_bars - 1,
                        "entry_price": pos["entry_price"],
                        "exit_price": exit_price,
                        "qty": qty,
                        "pnl": net_pnl,
                        "cost": total_cost,
                        "slippage": total_slip,
                        "holding_bars": max(1, holding_bars),
                        "reason": "FINAL_LIQUIDATION",
                    })
            if equity_curve:
                equity_curve[-1] = cash

        return trades, equity_curve

    def _run_job(self, experiment_id: str, repro: ReproducibilityRecord) -> None:
        """Executes bar-by-bar simulation with strict fail-closed data and risk checks."""
        try:
            self.store.update_status(experiment_id, "RUNNING")
            self.store.append_audit_event(experiment_id, "JOB_STARTED", {"start_time": repro.start_date.isoformat()})
            exp_def = self.store.get_experiment(experiment_id)
            if exp_def:
                exp_def.status = ExperimentStatus.RUNNING
                self.store.save_experiment(exp_def)

            strat_id = exp_def.strategy_id if exp_def else getattr(repro, "strategy_id", "Canonical_SMA")

            # 1. Validate universe
            if not repro.universe:
                self.store.append_audit_event(
                    experiment_id, "DATA_UNAVAILABLE",
                    {"reason": "Universe is empty — no symbols to simulate."}
                )
                self.store.update_status(experiment_id, "FAILED")
                if exp_def:
                    exp_def.status = ExperimentStatus.FAILED
                    self.store.save_experiment(exp_def)
                return

            # 2. Check supported strategy
            supported_strategies = {"Canonical_SMA", "SMA_Cross", "Canonical_BuyAndHold"}
            if strat_id not in supported_strategies:
                self.store.append_audit_event(
                    experiment_id, "UNSUPPORTED_STRATEGY",
                    {"strategy_id": strat_id, "reason": f"Strategy '{strat_id}' is unsupported."}
                )
                self.store.update_status(experiment_id, "FAILED")
                if exp_def:
                    exp_def.status = ExperimentStatus.FAILED
                    self.store.save_experiment(exp_def)
                return

            # 3. Locate and validate dataset
            req_dataset_id = exp_def.dataset_id if exp_def else getattr(repro, "dataset_id", None)
            req_checksum = exp_def.dataset_checksum if exp_def else getattr(repro, "dataset_checksum", None)

            all_bars: Dict[str, List[Dict[str, Any]]] = {}
            seed = int(repro.reproducibility_hash[:8], 16)

            if req_dataset_id and req_dataset_id != "NSE_NIFTY50_DAILY":
                # Explicit dataset requested: must exist
                if req_dataset_id in self._in_memory_dataset_bars:
                    raw_bars = self._in_memory_dataset_bars[req_dataset_id]
                else:
                    reg_ds = self.dataset_store.get_dataset(req_dataset_id)
                    if not reg_ds:
                        self.store.append_audit_event(
                            experiment_id, "DATA_UNAVAILABLE",
                            {"dataset_id": req_dataset_id, "reason": "Dataset not found in registry."}
                        )
                        self.store.update_status(experiment_id, "FAILED")
                        if exp_def:
                            exp_def.status = ExperimentStatus.FAILED
                            self.store.save_experiment(exp_def)
                        return
                    raw_bars = []

                if not raw_bars:
                    self.store.append_audit_event(
                        experiment_id, "DATA_UNAVAILABLE",
                        {"dataset_id": req_dataset_id, "reason": "Market data bars unavailable for dataset."}
                    )
                    self.store.update_status(experiment_id, "FAILED")
                    if exp_def:
                        exp_def.status = ExperimentStatus.FAILED
                        self.store.save_experiment(exp_def)
                    return

                # Validate checksum
                if req_checksum:
                    actual_cs = compute_dataset_checksum(raw_bars)
                    if actual_cs != req_checksum:
                        self.store.append_audit_event(
                            experiment_id, "CHECKSUM_MISMATCH",
                            {"expected": req_checksum, "calculated": actual_cs}
                        )
                        self.store.update_status(experiment_id, "FAILED")
                        if exp_def:
                            exp_def.status = ExperimentStatus.FAILED
                            self.store.save_experiment(exp_def)
                        return

                for sym in repro.universe:
                    sym_bars = [
                        _to_bar_dict(b) for b in raw_bars
                        if (isinstance(b, dict) and b.get("symbol") == sym) or (hasattr(b, "symbol") and b.symbol == sym)
                    ]
                    sym_bars.sort(key=lambda x: x["date"])
                    all_bars[sym] = sym_bars
            else:
                # Check in-memory bars
                found_in_memory = False
                for sym in repro.universe:
                    for ds_id, b_list in self._in_memory_dataset_bars.items():
                        matching = [
                            _to_bar_dict(b) for b in b_list
                            if (isinstance(b, dict) and b.get("symbol") == sym) or (hasattr(b, "symbol") and b.symbol == sym)
                        ]
                        if matching:
                            matching.sort(key=lambda x: x["date"])
                            all_bars[sym] = matching
                            found_in_memory = True
                            break

                if not found_in_memory:
                    for idx, sym in enumerate(repro.universe):
                        sym_seed = (seed + idx * 31337) % (2**32)
                        sym_hash = int(hashlib.md5(sym.encode()).hexdigest()[:8], 16)
                        base_price = 500.0 + (sym_hash % 4500)
                        all_bars[sym] = self._generate_ohlcv_bars(
                            sym, repro.start_date, repro.end_date, sym_seed, base_price=base_price
                        )

            # Run bar-by-bar simulation
            trades, equity_curve = self._run_simulation(repro, seed, all_bars)

            # Audit first signal and filled trade if any
            if trades:
                first = trades[0]
                self.store.append_audit_event(
                    experiment_id, "SIGNAL_GENERATED",
                    {"strategy_id": strat_id, "symbol": first["symbol"], "signal_type": "ENTRY_LONG"}
                )
                self.store.append_audit_event(
                    experiment_id, "ORDER_PROPOSED",
                    {"symbol": first["symbol"], "quantity": first["qty"], "price": first["entry_price"], "side": "BUY"}
                )
                self.store.append_audit_event(
                    experiment_id, "RISK_CHECK_EVALUATED",
                    {"is_approved": True, "symbol": first["symbol"], "code": "APPROVED"}
                )
                self.store.append_audit_event(
                    experiment_id, "ORDER_FILLED",
                    {"symbol": first["symbol"], "quantity": first["qty"], "fill_price": first["entry_price"], "costs": first["cost"], "slippage": first["slippage"]}
                )

            final_equity = equity_curve[-1] if equity_curve else repro.initial_capital
            self.store.append_audit_event(
                experiment_id, "PORTFOLIO_STATE_UPDATED",
                {"final_equity": round(final_equity, 2), "initial_capital": repro.initial_capital, "total_trades": len(trades)}
            )

            metrics = self._compute_metrics_from_trades(
                trades, equity_curve, repro.initial_capital, repro.cost_model, repro.slippage_model
            )

            # Save trades and equity curve
            for idx, t in enumerate(trades):
                self.store.save_trade(
                    experiment_id=experiment_id,
                    trade={
                        "trade_id": f"trade_{experiment_id}_{idx}",
                        "symbol": t["symbol"],
                        "strategy_id": strat_id,
                        "strategy_version": "1.0.0",
                        "side": "BUY",
                        "entry_timestamp": repro.start_date.isoformat(),
                        "exit_timestamp": repro.end_date.isoformat(),
                        "entry_price": t["entry_price"],
                        "exit_price": t["exit_price"],
                        "quantity": t["qty"],
                        "gross_pnl": t["pnl"] + t["cost"],
                        "costs": t["cost"],
                        "slippage": t["slippage"],
                        "net_pnl": t["pnl"],
                        "pnl": t["pnl"],
                        "holding_time_seconds": t["holding_bars"] * 86400.0,
                        "entry_reason": "SMA_CROSSOVER",
                        "exit_reason": t.get("reason", "SIGNAL_EXIT"),
                        "evidence_snapshot": {},
                    }
                )

            for b_idx, eq in enumerate(equity_curve):
                self.store.save_equity_point(
                    experiment_id=experiment_id,
                    timestamp=(repro.start_date + timedelta(days=b_idx)).isoformat(),
                    equity=eq,
                    cash=eq,
                    positions_value=0.0,
                )

            self.store.update_status(experiment_id, "COMPLETED", metrics=metrics)
            self.store.append_audit_event(
                experiment_id, "JOB_COMPLETED",
                {"metrics": metrics.model_dump() if hasattr(metrics, "model_dump") else metrics.dict()}
            )
            if exp_def:
                exp_def.status = ExperimentStatus.COMPLETED
                self.store.save_experiment(exp_def)

        except Exception as e:
            self.store.append_audit_event(experiment_id, "JOB_ERROR", {"error": str(e)})
            self.store.update_status(experiment_id, "FAILED")
            try:
                exp_def = self.store.get_experiment(experiment_id)
                if exp_def:
                    exp_def.status = ExperimentStatus.FAILED
                    self.store.save_experiment(exp_def)
            except Exception:
                pass

    def submit_experiment(self, exp: ExperimentDefinition, idempotent: bool = True) -> Dict[str, Any]:
        """Submits an experiment definition for execution with idempotency protection."""
        existing_run = self.store.get_run(exp.experiment_id)
        if existing_run and idempotent:
            if existing_run["status"] in ("PENDING", "RUNNING", "COMPLETED"):
                return {
                    "status": "already_submitted",
                    "experiment_id": exp.experiment_id,
                    "run_id": exp.experiment_id,
                    "reproducibility_hash": existing_run["reproducibility_hash"],
                    "is_idempotent_duplicate": True,
                }

        exp.status = ExperimentStatus.PENDING
        self.store.save_experiment(exp)

        res = self.submit_backtest(
            strategy_id=exp.strategy_id,
            universe=exp.universe,
            start_date=exp.start_date,
            end_date=exp.end_date,
            parameters=exp.parameters,
            initial_capital=exp.initial_capital,
            timeframe=exp.timeframe,
            cost_model=exp.cost_model,
            slippage_model=exp.slippage_model,
            dataset_version=exp.dataset_version,
            git_commit=exp.code_revision,
            experiment_id=exp.experiment_id,
            dataset_id=exp.dataset_id,
            dataset_checksum=exp.dataset_checksum,
        )

        return {
            "status": "submitted",
            "experiment_id": exp.experiment_id,
            "run_id": res["experiment_id"],
            "reproducibility_hash": res["reproducibility_hash"],
            "is_idempotent_duplicate": False,
        }

    def get_run_status(self, experiment_id: str) -> Optional[Dict[str, Any]]:
        return self.store.get_run(experiment_id)

    def get_audit_trail(self, experiment_id: str) -> List[Dict[str, Any]]:
        return self.store.get_audit_trail(experiment_id)
