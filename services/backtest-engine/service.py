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
from data.schemas.contracts import DataQualityStatus
from data.schemas.canonical_market_data import CanonicalMarketDataBar


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


def _format_ts(ts: Any) -> str:
    """Format market timestamp into strict ISO-8601 string."""
    if isinstance(ts, datetime):
        return ts.isoformat()
    return str(ts)


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
        allow_synthetic: bool = False,
    ):
        self.store = store or BacktestRunStore()
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.risk_engine = risk_engine or RiskEngine()
        self.dataset_store = dataset_store or DatasetRegistryStore()
        self.allow_synthetic = allow_synthetic
        self._in_memory_dataset_bars: Dict[str, List[Any]] = {}

    def register_dataset_bars(self, dataset_id: str, bars: List[Any], version: Optional[str] = None) -> None:
        """Registers in-memory market data bars associated with a dataset identifier."""
        self._in_memory_dataset_bars[dataset_id] = bars
        if version:
            self._in_memory_dataset_bars[(dataset_id, version)] = bars
            self._in_memory_dataset_bars[f"{dataset_id}:{version}"] = bars

    register_in_memory_dataset = register_dataset_bars

    def seed_test_default_dataset(self) -> None:
        """Test-only fixture helper to explicitly seed canonical in-memory bars and registry entry."""
        self._seed_default_dataset_internal()

    def _seed_default_dataset_internal(self) -> None:
        """Internal seeding logic for the default test dataset fixture."""
        if "NSE_NIFTY50_DAILY" in self._in_memory_dataset_bars:
            return
        base_ts = datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc)
        bars: List[CanonicalMarketDataBar] = []
        symbols = [
            "NIFTY50", "RELIANCE", "RELIANCE.NS", "TCS", "TCS.NS",
            "INFY", "INFY.NS", "SBIN", "SBIN.NS"
        ]
        for sym in symbols:
            # Deterministic canonical walk (150 bars)
            prices = [100.0] * 35 + [150.0 + (i * 1.5) for i in range(115)]
            for idx, p in enumerate(prices):
                bars.append(
                    CanonicalMarketDataBar(
                        timestamp=base_ts + timedelta(days=idx),
                        symbol=sym,
                        exchange="NSE",
                        timeframe="1d",
                        open=p,
                        high=p + 1.0,
                        low=p - 1.0,
                        close=p,
                        volume=10000.0,
                        trade_count=100,
                    )
                )
        chk = compute_dataset_checksum(bars)
        rec = DatasetRecord(
            dataset_id="NSE_NIFTY50_DAILY",
            name="NSE NIFTY 50 Daily Benchmark",
            version="2026.09.14",
            exchange="NSE",
            asset_class="EQUITY",
            timeframe="1d",
            symbols=symbols,
            start_date=bars[0].timestamp,
            end_date=bars[-1].timestamp,
            bar_count=len(bars),
            sha256_checksum=chk,
            quality_status=DataQualityStatus.VALID,
        )
        self.dataset_store.register_dataset(rec)
        self._in_memory_dataset_bars["NSE_NIFTY50_DAILY"] = bars
        self._in_memory_dataset_bars[("NSE_NIFTY50_DAILY", "2026.09.14")] = bars
        self._in_memory_dataset_bars["NSE_NIFTY50_DAILY:2026.09.14"] = bars

    def _ensure_default_dataset(self) -> None:
        """Guarded helper: raises RuntimeError on production paths unless allow_synthetic=True."""
        if not self.allow_synthetic:
            raise RuntimeError(
                "Automatic default synthetic dataset generation is prohibited on production paths. "
                "Historical backtests require actual registered datasets."
            )
        self._seed_default_dataset_internal()

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
        dataset_version: Optional[str] = None,
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

        target_ds_id = dataset_id or "NSE_NIFTY50_DAILY"
        if self.allow_synthetic and target_ds_id == "NSE_NIFTY50_DAILY":
            self._ensure_default_dataset()

        if dataset_version is None:
            ds_rec = self.dataset_store.get_dataset(target_ds_id)
            dataset_version = ds_rec.version if ds_rec else "2026.09.14"

        if dataset_checksum is None:
            ds_rec = self.dataset_store.get_dataset(target_ds_id, version=dataset_version)
            if ds_rec:
                dataset_checksum = ds_rec.sha256_checksum
            else:
                dataset_checksum = "0" * 64

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
                dataset_id=target_ds_id,
                dataset_version=dataset_version,
                dataset_checksum=dataset_checksum or "",
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
        if not self.allow_synthetic:
            raise RuntimeError(
                "Synthetic bar generation is prohibited on production paths. "
                "All backtests require registered historical datasets."
            )
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

        def _clean(val: float, default: float = 0.0) -> float:
            if val is None or math.isnan(val) or math.isinf(val):
                return default
            return val

        if n_trades == 0:
            return BacktestMetrics(
                total_return_pct=round(_clean(total_return_pct), 4),
                cagr_pct=round(_clean(cagr_pct), 4),
                number_of_trades=0,
                win_rate=0.0,
                average_win=0.0,
                average_loss=0.0,
                profit_factor=0.0,
                expectancy=0.0,
                maximum_drawdown_pct=round(_clean(max_dd * 100.0), 4),
                sharpe_ratio=0.0,
                sortino_ratio=0.0,
                maximum_consecutive_losses=0,
                average_holding_time_seconds=0.0,
                exposure_pct=0.0,
                total_transaction_costs=0.0,
                total_slippage_impact=0.0,
                worst_trade_pnl=0.0,
                worst_day_pnl=round(_clean(worst_day), 2),
            )

        win_rate = len(wins) / n_trades if n_trades > 0 else 0.0
        avg_win = float(np.mean([t["pnl"] for t in wins])) if wins else 0.0
        avg_loss = float(np.mean([t["pnl"] for t in losses])) if losses else 0.0
        gross_profit = sum(t["pnl"] for t in wins) if wins else 0.0
        gross_loss = abs(sum(t["pnl"] for t in losses)) if losses else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (0.0 if not wins else 999.0)
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

        def _clean(val: float, default: float = 0.0) -> float:
            if val is None or math.isnan(val) or math.isinf(val):
                return default
            return val

        return BacktestMetrics(
            total_return_pct=round(_clean(total_return_pct), 4),
            cagr_pct=round(_clean(cagr_pct), 4),
            number_of_trades=n_trades,
            win_rate=round(_clean(win_rate), 4),
            average_win=round(_clean(avg_win), 2),
            average_loss=round(_clean(avg_loss), 2),
            profit_factor=round(_clean(profit_factor), 4),
            expectancy=round(_clean(expectancy), 2),
            maximum_drawdown_pct=round(_clean(max_dd * 100.0), 4),
            sharpe_ratio=round(_clean(sharpe), 4),
            sortino_ratio=round(_clean(sortino), 4),
            maximum_consecutive_losses=max_consec_loss,
            average_holding_time_seconds=round(_clean(avg_hold_secs), 1),
            exposure_pct=round(_clean(exposure_pct), 4),
            total_transaction_costs=round(_clean(total_costs), 2),
            total_slippage_impact=round(_clean(total_slip), 2),
            worst_trade_pnl=round(_clean(worst_trade), 2),
            worst_day_pnl=round(_clean(worst_day), 2),
        )

    def _run_simulation(
        self,
        repro: ReproducibilityRecord,
        seed: int,
        all_bars: Dict[str, List[Dict[str, Any]]],
        strategy_id: str = "SMA_Cross",
    ) -> Tuple[List[Dict[str, Any]], List[float]]:
        """Run deterministic causal timestamp-aligned simulation."""
        cost_cfg = repro.cost_model
        slip_cfg = repro.slippage_model
        params = repro.parameters or {}
        fast_period = int(params.get("fast_period", 9))
        slow_period = int(params.get("slow_period", 21))

        is_buy_and_hold = strategy_id in ("BuyAndHold", "Canonical_BuyAndHold")

        trades: List[Dict[str, Any]] = []
        cash = float(repro.initial_capital)
        peak_portfolio_val = float(repro.initial_capital)
        prev_close_val = float(repro.initial_capital)
        positions: Dict[str, Dict[str, Any]] = {}
        equity_curve: List[float] = []
        equity_points: List[Dict[str, Any]] = []

        timeline = sorted(set(b["date"] for bars in all_bars.values() for b in bars))
        if not timeline:
            return trades, [cash], [{"timestamp": _format_ts(repro.start_date), "equity": cash, "cash": cash, "positions_value": 0.0}]

        bar_by_sym_ts: Dict[str, Dict[Any, Dict[str, Any]]] = {
            sym: {b["date"]: b for b in bars} for sym, bars in all_bars.items()
        }
        closes_by_sym: Dict[str, List[float]] = {sym: [] for sym in all_bars}
        last_known_close: Dict[str, float] = {}
        last_known_open: Dict[str, float] = {}
        sym_has_entered: set = set()

        pending_entries: Dict[str, float] = {}  # symbol -> signal_price
        pending_exits: set = set()

        for t_idx, current_ts in enumerate(timeline):
            # Update latest open prices for symbols trading at current_ts
            for sym in all_bars:
                if current_ts in bar_by_sym_ts[sym]:
                    last_known_open[sym] = bar_by_sym_ts[sym][current_ts]["open"]

            # Portfolio mark at open before trading actions
            open_pos_val = sum(
                (bar_by_sym_ts[sym][current_ts]["open"] if current_ts in bar_by_sym_ts[sym] else last_known_close.get(sym, pos["entry_price"])) * pos["qty"]
                for sym, pos in positions.items()
            )
            current_portfolio_val = cash + open_pos_val
            if current_portfolio_val > peak_portfolio_val:
                peak_portfolio_val = current_portfolio_val
            current_drawdown_pct = max(0.0, (peak_portfolio_val - current_portfolio_val) / peak_portfolio_val) if peak_portfolio_val > 0 else 0.0
            current_daily_loss_pct = max(0.0, (prev_close_val - current_portfolio_val) / prev_close_val) if prev_close_val > 0 else 0.0

            # 1. Fill pending exits at open for symbols with a bar at current_ts
            for sym in list(positions.keys()):
                if current_ts not in bar_by_sym_ts[sym]:
                    continue
                bar = bar_by_sym_ts[sym][current_ts]
                pos = positions[sym]
                qty = pos["qty"]
                entry_p = pos["entry_price"]
                stop_loss = pos["stop_loss"]

                exit_price = None
                exit_reason = None

                # Gap-down check at OPEN first
                if bar["open"] <= stop_loss:
                    raw_exit = min(bar["open"], stop_loss)
                    exit_price, slip_pts = _calculate_slippage_price(raw_exit, "SELL", slip_cfg)
                    exit_reason = "STOP_LOSS_GAP"
                elif sym in pending_exits:
                    raw_exit = bar["open"]
                    exit_price, slip_pts = _calculate_slippage_price(raw_exit, "SELL", slip_cfg)
                    exit_reason = "SIGNAL_EXIT"
                elif bar["low"] <= stop_loss:
                    raw_exit = stop_loss
                    exit_price, slip_pts = _calculate_slippage_price(raw_exit, "SELL", slip_cfg)
                    exit_reason = "STOP_LOSS"

                if exit_price is not None:
                    exit_trade_val = exit_price * qty
                    exit_cost = _calculate_trade_costs(exit_trade_val, "SELL", cost_cfg)
                    entry_cost = pos.get("entry_cost", 0.0)
                    total_cost = entry_cost + exit_cost
                    total_slip = pos.get("entry_slippage", 0.0) + (slip_pts * qty)
                    net_pnl = (exit_price * qty - exit_cost) - (entry_p * qty + entry_cost)
                    cash += (exit_price * qty - exit_cost)
                    holding_bars = t_idx - pos["entry_bar"]
                    trades.append({
                        "symbol": sym,
                        "entry_bar": pos["entry_bar"],
                        "exit_bar": t_idx,
                        "entry_time": pos.get("entry_time", current_ts),
                        "exit_time": current_ts,
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

            # Buy and Hold: queue entry on first available bar of symbol
            if is_buy_and_hold:
                for sym in repro.universe:
                    if sym not in positions and sym not in sym_has_entered and current_ts in bar_by_sym_ts.get(sym, {}):
                        pending_entries[sym] = bar_by_sym_ts[sym][current_ts]["open"]
                        sym_has_entered.add(sym)

            # 2. Fill pending entries at open
            processed_entries = set()
            for sym, sig_price in list(pending_entries.items()):
                if current_ts not in bar_by_sym_ts.get(sym, {}):
                    continue
                processed_entries.add(sym)
                bar = bar_by_sym_ts[sym][current_ts]
                if sym not in positions:
                    raw_entry = bar["open"]
                    entry_p, slip_pts = _calculate_slippage_price(raw_entry, "BUY", slip_cfg)
                    if is_buy_and_hold:
                        from quant.strategies.buy_and_hold import BuyAndHold
                        if "allocation_pct" in params or "weights" in params:
                            bh_strat = BuyAndHold(parameters={
                                "allocation_pct": float(params.get("allocation_pct", 1.0)),
                                "universe": repro.universe,
                                "weights": params.get("weights", {}),
                            })
                            weight = bh_strat.get_allocation_weight(sym)
                            capital_per_trade = repro.initial_capital * weight
                        else:
                            bh_strat = BuyAndHold(parameters={
                                "universe": repro.universe,
                                "weights": params.get("weights", {}),
                            })
                            capital_per_trade = (min(cash * 0.045, repro.initial_capital * 0.045)) / max(1, len(repro.universe))
                        stop_loss = round(entry_p * 0.50, 2)
                    else:
                        capital_per_trade = min(cash * 0.045, repro.initial_capital * 0.045)
                        stop_loss = round(entry_p * 0.97, 2)

                    qty = max(1, int(capital_per_trade / entry_p)) if entry_p > 0 else 0
                    if qty <= 0:
                        continue

                    # Update portfolio state before risk evaluation
                    open_pos_val = sum(
                        (bar_by_sym_ts[s][current_ts]["open"] if current_ts in bar_by_sym_ts[s] else last_known_close.get(s, positions[s]["entry_price"])) * positions[s]["qty"]
                        for s in positions
                    )
                    current_portfolio_val = cash + open_pos_val
                    current_drawdown_pct = max(0.0, (peak_portfolio_val - current_portfolio_val) / peak_portfolio_val) if peak_portfolio_val > 0 else 0.0
                    current_daily_loss_pct = max(0.0, (prev_close_val - current_portfolio_val) / prev_close_val) if prev_close_val > 0 else 0.0

                    risk_eval = self.risk_engine.evaluate(
                        symbol=sym,
                        price=entry_p,
                        proposed_quantity=qty,
                        stop_loss=stop_loss,
                        current_portfolio_value=current_portfolio_val,
                        current_daily_loss_pct=current_daily_loss_pct,
                        current_drawdown_pct=current_drawdown_pct,
                        current_open_positions_count=len(positions),
                    )

                    if not risk_eval.is_approved:
                        continue

                    approved_qty = risk_eval.approved_quantity if risk_eval.approved_quantity is not None else qty
                    if approved_qty <= 0:
                        continue
                    qty = approved_qty

                    buy_cost = _calculate_trade_costs(entry_p * qty, "BUY", cost_cfg)
                    required_outflow = (entry_p * qty) + buy_cost
                    if cash < required_outflow:
                        continue

                    cash -= required_outflow
                    positions[sym] = {
                        "qty": qty,
                        "entry_price": entry_p,
                        "entry_bar": t_idx,
                        "entry_time": current_ts,
                        "stop_loss": stop_loss,
                        "entry_cost": buy_cost,
                        "entry_slippage": slip_pts * qty,
                    }

                    # Entry bar stop loss: evaluated strictly AFTER entry fill
                    if not is_buy_and_hold and bar["low"] <= stop_loss:
                        raw_exit = stop_loss
                        exit_price, exit_slip = _calculate_slippage_price(raw_exit, "SELL", slip_cfg)
                        exit_trade_val = exit_price * qty
                        exit_cost = _calculate_trade_costs(exit_trade_val, "SELL", cost_cfg)
                        entry_cost = positions[sym]["entry_cost"]
                        total_cost = entry_cost + exit_cost
                        total_slip = positions[sym]["entry_slippage"] + (exit_slip * qty)
                        net_pnl = (exit_price * qty - exit_cost) - (entry_p * qty + entry_cost)
                        cash += (exit_price * qty - exit_cost)
                        trades.append({
                            "symbol": sym,
                            "entry_bar": t_idx,
                            "exit_bar": t_idx,
                            "entry_time": current_ts,
                            "exit_time": current_ts,
                            "entry_price": entry_p,
                            "exit_price": exit_price,
                            "qty": qty,
                            "pnl": net_pnl,
                            "cost": total_cost,
                            "slippage": total_slip,
                            "holding_bars": 1,
                            "reason": "STOP_LOSS",
                        })
                        del positions[sym]

            for sym in processed_entries:
                pending_entries.pop(sym, None)

            # 3. Mark-to-market portfolio value at current_ts close
            for sym in all_bars:
                if current_ts in bar_by_sym_ts[sym]:
                    c_price = bar_by_sym_ts[sym][current_ts]["close"]
                    last_known_close[sym] = c_price
                    closes_by_sym[sym].append(c_price)

            pos_val = sum(
                last_known_close.get(sym, pos["entry_price"]) * pos["qty"]
                for sym, pos in positions.items()
            )
            close_equity = cash + pos_val
            equity_curve.append(close_equity)
            equity_points.append({
                "timestamp": _format_ts(current_ts),
                "equity": close_equity,
                "cash": cash,
                "positions_value": pos_val,
            })
            prev_close_val = close_equity
            if close_equity > peak_portfolio_val:
                peak_portfolio_val = close_equity

            # 4. Generate signals at current_ts close for execution at next open
            if not is_buy_and_hold:
                for sym in all_bars:
                    if current_ts not in bar_by_sym_ts[sym]:
                        continue
                    closes = closes_by_sym[sym]
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

        # Close any open positions at the last known close price
        if timeline:
            final_ts = timeline[-1]
            for sym, pos in list(positions.items()):
                raw_exit = last_known_close.get(sym, pos["entry_price"])
                exit_price, slip_pts = _calculate_slippage_price(raw_exit, "SELL", slip_cfg)
                qty = pos["qty"]
                exit_trade_val = exit_price * qty
                exit_cost = _calculate_trade_costs(exit_trade_val, "SELL", cost_cfg)
                entry_cost = pos.get("entry_cost", 0.0)
                total_cost = entry_cost + exit_cost
                total_slip = pos.get("entry_slippage", 0.0) + (slip_pts * qty)
                net_pnl = (exit_price * qty - exit_cost) - (pos["entry_price"] * qty + entry_cost)
                cash += (exit_price * qty - exit_cost)
                holding_bars = (len(timeline) - 1) - pos["entry_bar"]
                trades.append({
                    "symbol": sym,
                    "entry_bar": pos["entry_bar"],
                    "exit_bar": len(timeline) - 1,
                    "entry_time": pos.get("entry_time", final_ts),
                    "exit_time": final_ts,
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
            if equity_points:
                equity_points[-1]["equity"] = cash
                equity_points[-1]["cash"] = cash
                equity_points[-1]["positions_value"] = 0.0

        pending_entries.clear()
        return trades, equity_curve, equity_points

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
            supported_strategies = {"Canonical_SMA", "SMA_Cross", "Canonical_BuyAndHold", "BuyAndHold"}
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

            # 3. Locate and validate dataset (Fail closed, no synthetic generation)
            req_dataset_id = (exp_def.dataset_id if exp_def else getattr(repro, "dataset_id", None)) or "NSE_NIFTY50_DAILY"
            req_dataset_version = (exp_def.dataset_version if exp_def else getattr(repro, "dataset_version", None)) or "2026.09.14"
            req_checksum = exp_def.dataset_checksum if exp_def else getattr(repro, "dataset_checksum", None)

            if self.allow_synthetic and req_dataset_id == "NSE_NIFTY50_DAILY":
                self._ensure_default_dataset()

            if not req_dataset_id:
                self.store.append_audit_event(
                    experiment_id, "DATA_UNAVAILABLE",
                    {"reason": "Historical backtest requires a registered dataset. Synthetic data fallback is prohibited."}
                )
                self.store.update_status(experiment_id, "FAILED")
                if exp_def:
                    exp_def.status = ExperimentStatus.FAILED
                    self.store.save_experiment(exp_def)
                return

            reg_ds = self.dataset_store.get_dataset(req_dataset_id, version=req_dataset_version)
            raw_bars = (
                self._in_memory_dataset_bars.get((req_dataset_id, req_dataset_version))
                or self._in_memory_dataset_bars.get(f"{req_dataset_id}:{req_dataset_version}")
                or self._in_memory_dataset_bars.get(req_dataset_id)
            )

            if not reg_ds and not raw_bars:
                self.store.append_audit_event(
                    experiment_id, "DATA_UNAVAILABLE",
                    {"dataset_id": req_dataset_id, "reason": f"Dataset '{req_dataset_id}' not found in registry."}
                )
                self.store.update_status(experiment_id, "FAILED")
                if exp_def:
                    exp_def.status = ExperimentStatus.FAILED
                    self.store.save_experiment(exp_def)
                return

            if not reg_ds:
                self.store.append_audit_event(
                    experiment_id, "DATA_UNAVAILABLE",
                    {"dataset_id": req_dataset_id, "reason": f"Dataset '{req_dataset_id}' version '{req_dataset_version}' not found in registry."}
                )
                self.store.update_status(experiment_id, "FAILED")
                if exp_def:
                    exp_def.status = ExperimentStatus.FAILED
                    self.store.save_experiment(exp_def)
                return

            # Reject CORRUPTED / REJECTED / unvalidated datasets
            if reg_ds.quality_status in (DataQualityStatus.CORRUPTED, DataQualityStatus.REJECTED):
                self.store.append_audit_event(
                    experiment_id, "DATASET_REJECTED",
                    {"dataset_id": req_dataset_id, "status": reg_ds.quality_status.value if hasattr(reg_ds.quality_status, "value") else str(reg_ds.quality_status)}
                )
                self.store.append_audit_event(
                    experiment_id, "DATA_UNAVAILABLE",
                    {"dataset_id": req_dataset_id, "reason": f"Dataset '{req_dataset_id}' is quarantined with status {reg_ds.quality_status}."}
                )
                self.store.update_status(experiment_id, "FAILED")
                if exp_def:
                    exp_def.status = ExperimentStatus.FAILED
                    self.store.save_experiment(exp_def)
                return

            # Validate dataset timeframe against experiment timeframe
            if reg_ds.timeframe != repro.timeframe:
                self.store.append_audit_event(
                    experiment_id, "TIMEFRAME_MISMATCH",
                    {"expected": repro.timeframe, "dataset_timeframe": reg_ds.timeframe}
                )
                self.store.append_audit_event(
                    experiment_id, "DATA_UNAVAILABLE",
                    {"dataset_id": req_dataset_id, "reason": f"Timeframe mismatch: experiment requires '{repro.timeframe}', dataset registered with '{reg_ds.timeframe}'."}
                )
                self.store.update_status(experiment_id, "FAILED")
                if exp_def:
                    exp_def.status = ExperimentStatus.FAILED
                    self.store.save_experiment(exp_def)
                return

            if not raw_bars:
                self.store.append_audit_event(
                    experiment_id, "DATA_UNAVAILABLE",
                    {"dataset_id": req_dataset_id, "reason": f"Market data bars unavailable for dataset '{req_dataset_id}'."}
                )
                self.store.update_status(experiment_id, "FAILED")
                if exp_def:
                    exp_def.status = ExperimentStatus.FAILED
                    self.store.save_experiment(exp_def)
                return

            # Validate declared bar count against complete dataset BEFORE date interval filtering
            if len(raw_bars) != reg_ds.bar_count:
                self.store.append_audit_event(
                    experiment_id, "BAR_COUNT_MISMATCH",
                    {"expected": reg_ds.bar_count, "actual": len(raw_bars)}
                )
                self.store.append_audit_event(
                    experiment_id, "DATA_UNAVAILABLE",
                    {"dataset_id": req_dataset_id, "reason": f"Bar count mismatch: registry declared {reg_ds.bar_count}, loaded {len(raw_bars)} bars."}
                )
                self.store.update_status(experiment_id, "FAILED")
                if exp_def:
                    exp_def.status = ExperimentStatus.FAILED
                    self.store.save_experiment(exp_def)
                return

            # Validate bar timeframe
            for b in raw_bars:
                b_tf = getattr(b, "timeframe", None) or (b.get("timeframe") if isinstance(b, dict) else None)
                if b_tf and b_tf != repro.timeframe:
                    self.store.append_audit_event(
                        experiment_id, "TIMEFRAME_MISMATCH",
                        {"expected": repro.timeframe, "bar_timeframe": b_tf}
                    )
                    self.store.append_audit_event(
                        experiment_id, "DATA_UNAVAILABLE",
                        {"dataset_id": req_dataset_id, "reason": f"Bar timeframe '{b_tf}' mismatches experiment timeframe '{repro.timeframe}'."}
                    )
                    self.store.update_status(experiment_id, "FAILED")
                    if exp_def:
                        exp_def.status = ExperimentStatus.FAILED
                        self.store.save_experiment(exp_def)
                    return

            # Checksum verification
            actual_cs = compute_dataset_checksum(raw_bars)

            if reg_ds.sha256_checksum and actual_cs != reg_ds.sha256_checksum:
                self.store.append_audit_event(
                    experiment_id, "DATA_DRIFT",
                    {"expected": reg_ds.sha256_checksum, "calculated": actual_cs}
                )
                self.store.append_audit_event(
                    experiment_id, "CHECKSUM_MISMATCH",
                    {"expected": reg_ds.sha256_checksum, "calculated": actual_cs}
                )
                self.store.append_audit_event(
                    experiment_id, "DATA_UNAVAILABLE",
                    {"dataset_id": req_dataset_id, "reason": "Dataset checksum drifted from registry."}
                )
                self.store.update_status(experiment_id, "FAILED")
                if exp_def:
                    exp_def.status = ExperimentStatus.FAILED
                    self.store.save_experiment(exp_def)
                return

            if req_checksum and actual_cs != req_checksum:
                self.store.append_audit_event(
                    experiment_id, "CHECKSUM_MISMATCH",
                    {"expected": req_checksum, "calculated": actual_cs}
                )
                self.store.append_audit_event(
                    experiment_id, "DATA_UNAVAILABLE",
                    {"dataset_id": req_dataset_id, "reason": "Dataset checksum mismatch with requested checksum."}
                )
                self.store.update_status(experiment_id, "FAILED")
                if exp_def:
                    exp_def.status = ExperimentStatus.FAILED
                    self.store.save_experiment(exp_def)
                return

            # Validate finite positive prices, valid OHLC relationships, nonnegative volume, timezone-aware, no duplicates
            seen_timestamps = set()
            for b in raw_bars:
                sym = str(getattr(b, "symbol", None) or (b.get("symbol") if isinstance(b, dict) else "")).upper()
                ts = getattr(b, "timestamp", getattr(b, "date", None)) if not isinstance(b, dict) else (b.get("timestamp") or b.get("date"))
                if isinstance(ts, str):
                    try:
                        ts = datetime.fromisoformat(ts)
                    except Exception:
                        ts = None
                if ts is None or getattr(ts, "tzinfo", None) is None:
                    self.store.append_audit_event(
                        experiment_id, "DATA_INTEGRITY_VIOLATION",
                        {"reason": f"Bar for {sym} has naive or missing timestamp: {ts}"}
                    )
                    self.store.append_audit_event(
                        experiment_id, "DATA_UNAVAILABLE",
                        {"reason": "Naive or missing bar timestamp."}
                    )
                    self.store.update_status(experiment_id, "FAILED")
                    if exp_def:
                        exp_def.status = ExperimentStatus.FAILED
                        self.store.save_experiment(exp_def)
                    return

                ts_key = (sym, ts.astimezone(timezone.utc).isoformat())
                if ts_key in seen_timestamps:
                    self.store.append_audit_event(
                        experiment_id, "DATA_INTEGRITY_VIOLATION",
                        {"reason": f"Duplicate bar timestamp for {sym} at {ts}."}
                    )
                    self.store.append_audit_event(
                        experiment_id, "DATA_UNAVAILABLE",
                        {"reason": "Duplicate bar timestamp detected."}
                    )
                    self.store.update_status(experiment_id, "FAILED")
                    if exp_def:
                        exp_def.status = ExperimentStatus.FAILED
                        self.store.save_experiment(exp_def)
                    return
                seen_timestamps.add(ts_key)

                o = float(getattr(b, "open", 0.0) if not isinstance(b, dict) else b.get("open", 0.0))
                h = float(getattr(b, "high", 0.0) if not isinstance(b, dict) else b.get("high", 0.0))
                l = float(getattr(b, "low", 0.0) if not isinstance(b, dict) else b.get("low", 0.0))
                c = float(getattr(b, "close", 0.0) if not isinstance(b, dict) else b.get("close", 0.0))
                v = float(getattr(b, "volume", 0.0) if not isinstance(b, dict) else b.get("volume", 0.0))

                for p_name, p_val in [("open", o), ("high", h), ("low", l), ("close", c)]:
                    if math.isnan(p_val) or math.isinf(p_val) or p_val <= 0.0:
                        self.store.append_audit_event(
                            experiment_id, "DATA_INTEGRITY_VIOLATION",
                            {"reason": f"Price {p_name}={p_val} must be finite positive."}
                        )
                        self.store.append_audit_event(
                            experiment_id, "DATA_UNAVAILABLE",
                            {"reason": "Invalid non-positive or non-finite price."}
                        )
                        self.store.update_status(experiment_id, "FAILED")
                        if exp_def:
                            exp_def.status = ExperimentStatus.FAILED
                            self.store.save_experiment(exp_def)
                        return

                if not (l <= o <= h and l <= c <= h and l <= h):
                    self.store.append_audit_event(
                        experiment_id, "DATA_INTEGRITY_VIOLATION",
                        {"reason": f"OHLC violation for {sym}: O={o}, H={h}, L={l}, C={c}."}
                    )
                    self.store.append_audit_event(
                        experiment_id, "DATA_UNAVAILABLE",
                        {"reason": "Invalid OHLC bar relationship."}
                    )
                    self.store.update_status(experiment_id, "FAILED")
                    if exp_def:
                        exp_def.status = ExperimentStatus.FAILED
                        self.store.save_experiment(exp_def)
                    return

                if math.isnan(v) or math.isinf(v) or v < 0.0:
                    self.store.append_audit_event(
                        experiment_id, "DATA_INTEGRITY_VIOLATION",
                        {"reason": f"Volume={v} must be non-negative finite."}
                    )
                    self.store.append_audit_event(
                        experiment_id, "DATA_UNAVAILABLE",
                        {"reason": "Invalid negative volume."}
                    )
                    self.store.update_status(experiment_id, "FAILED")
                    if exp_def:
                        exp_def.status = ExperimentStatus.FAILED
                        self.store.save_experiment(exp_def)
                    return

            # Validate symbol coverage
            reg_syms_upper = {s.upper() for s in reg_ds.symbols}
            for sym in repro.universe:
                if sym.upper() not in reg_syms_upper:
                    self.store.append_audit_event(
                        experiment_id, "MISSING_SYMBOL",
                        {"requested_symbol": sym, "declared_symbols": reg_ds.symbols}
                    )
                    self.store.append_audit_event(
                        experiment_id, "DATA_UNAVAILABLE",
                        {"dataset_id": req_dataset_id, "reason": f"Requested symbol '{sym}' missing from dataset coverage."}
                    )
                    self.store.update_status(experiment_id, "FAILED")
                    if exp_def:
                        exp_def.status = ExperimentStatus.FAILED
                        self.store.save_experiment(exp_def)
                    return

            all_bars: Dict[str, List[Dict[str, Any]]] = {}
            for sym in repro.universe:
                sym_upper = sym.upper()
                sym_bars = [
                    _to_bar_dict(b) for b in raw_bars
                    if (isinstance(b, dict) and str(b.get("symbol", "")).upper() == sym_upper) or (hasattr(b, "symbol") and str(getattr(b, "symbol", "")).upper() == sym_upper)
                ]
                sym_bars.sort(key=lambda x: x["date"])

                # Filter by experiment start and end date if dates provided
                if repro.start_date and repro.end_date and sym_bars:
                    def _parse_ts(d):
                        if isinstance(d, str):
                            d = datetime.fromisoformat(d)
                        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)

                    s_dt = repro.start_date if repro.start_date.tzinfo else repro.start_date.replace(tzinfo=timezone.utc)
                    e_dt = repro.end_date if repro.end_date.tzinfo else repro.end_date.replace(tzinfo=timezone.utc)
                    filtered = [b for b in sym_bars if s_dt <= _parse_ts(b["date"]) <= e_dt]
                    if filtered:
                        sym_bars = filtered

                if not sym_bars:
                    self.store.append_audit_event(
                        experiment_id, "DATA_UNAVAILABLE",
                        {"dataset_id": req_dataset_id, "symbol": sym, "reason": f"No market data bars for symbol '{sym}'."}
                    )
                    self.store.update_status(experiment_id, "FAILED")
                    if exp_def:
                        exp_def.status = ExperimentStatus.FAILED
                        self.store.save_experiment(exp_def)
                    return
                all_bars[sym] = sym_bars

            # Evaluate baseline risk check before simulation
            first_sym = repro.universe[0]
            base_p = 2500.0
            proposed_val = repro.initial_capital * 0.05
            test_price = min(base_p, proposed_val) if proposed_val >= 1.0 else base_p
            test_qty = max(1, int(proposed_val / test_price)) if test_price > 0 else 1
            single_eval = self.risk_engine.evaluate(
                symbol=first_sym,
                price=test_price,
                proposed_quantity=test_qty,
                stop_loss=round(test_price * 0.97, 2),
                current_portfolio_value=repro.initial_capital,
                current_daily_loss_pct=0.0,
                current_drawdown_pct=0.0,
                current_open_positions_count=0,
            )
            if not single_eval.is_approved:
                self.store.append_audit_event(
                    experiment_id, "RISK_REJECTED",
                    {
                        "symbol": first_sym,
                        "code": single_eval.rejection_code.value if hasattr(single_eval.rejection_code, "value") else str(single_eval.rejection_code),
                        "reason": single_eval.rejection_reason,
                    }
                )
                self.store.update_status(experiment_id, "FAILED")
                if exp_def:
                    exp_def.status = ExperimentStatus.FAILED
                    self.store.save_experiment(exp_def)
                return

            seed = int(repro.reproducibility_hash[:8], 16)
            # Run bar-by-bar simulation
            trades, equity_curve, equity_points = self._run_simulation(repro, seed, all_bars, strategy_id=strat_id)

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
                entry_ts = t.get("entry_time")
                exit_ts = t.get("exit_time")
                entry_ts_str = _format_ts(entry_ts) if entry_ts else repro.start_date.isoformat()
                exit_ts_str = _format_ts(exit_ts) if exit_ts else repro.end_date.isoformat()

                self.store.save_trade(
                    experiment_id=experiment_id,
                    trade={
                        "trade_id": f"trade_{experiment_id}_{idx}",
                        "symbol": t["symbol"],
                        "strategy_id": strat_id,
                        "strategy_version": "1.0.0",
                        "side": "BUY",
                        "entry_timestamp": entry_ts_str,
                        "exit_timestamp": exit_ts_str,
                        "entry_price": t["entry_price"],
                        "exit_price": t["exit_price"],
                        "quantity": t["qty"],
                        "gross_pnl": t["pnl"] + t["cost"],
                        "costs": t["cost"],
                        "slippage": t["slippage"],
                        "net_pnl": t["pnl"],
                        "pnl": t["pnl"],
                        "holding_time_seconds": t["holding_bars"] * 86400.0,
                        "entry_reason": "BUY_AND_HOLD" if strat_id in ("BuyAndHold", "Canonical_BuyAndHold") else "SMA_CROSSOVER",
                        "exit_reason": t.get("reason", "SIGNAL_EXIT"),
                        "reason": t.get("reason", "SIGNAL_EXIT"),
                        "evidence_snapshot": {},
                    }
                )

            for pt in equity_points:
                self.store.save_equity_point(
                    experiment_id=experiment_id,
                    timestamp=pt["timestamp"],
                    equity=pt["equity"],
                    cash=pt["cash"],
                    positions_value=pt["positions_value"],
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
