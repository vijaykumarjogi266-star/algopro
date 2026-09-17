"""
Algo Lab — Stage 7 Deterministic Evaluation Engine
Implements zero-lookahead backtesting engine integrating Stage 6 cost and slippage
models with fail-closed execution environment controls.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from services.evaluation_engine.manifest import (
    ExperimentManifest,
    EvaluationEnvironment,
    FrictionConfig,
)
from services.backtest_engine.cost_models import (
    IndianCostCalculator,
    SlippageCalculator,
)
from services.backtest_engine.contracts import (
    CostModelConfig,
    SlippageModelConfig,
    OrderSide,
)
from services.evaluation_engine.walk_forward import LookAheadBiasError


@dataclass
class EvaluationTrade:
    trade_id: str
    symbol: str
    side: str
    quantity: int
    base_price: float
    fill_price: float
    slippage_pts: float
    transaction_cost: float
    timestamp: datetime
    pnl: float = 0.0


@dataclass
class EvaluationResult:
    experiment_id: str
    strategy_id: str
    dataset_id: str
    initial_capital: float
    final_equity: float
    total_net_return: float
    total_gross_return: float
    total_friction_cost: float
    total_trades_count: int
    winning_trades_count: int
    losing_trades_count: int
    equity_curve: List[Tuple[datetime, float]] = field(default_factory=list)
    trades: List[EvaluationTrade] = field(default_factory=list)
    execution_environment: EvaluationEnvironment = EvaluationEnvironment.OFFLINE_SIMULATION


class DeterministicEvaluationEngine:
    """Deterministic evaluation engine using certified Stage 6 cost/slippage calculators."""

    def __init__(self, manifest: ExperimentManifest):
        self.manifest = manifest
        
        # AT-79: Live execution fail-closed lockout
        if self.manifest.environment == EvaluationEnvironment.LIVE:
            raise PermissionError(
                "ExecutionEnvironment.LIVE is strictly forbidden in Stage 7 evaluation engine."
            )

        self._cost_calculator = self._build_cost_calculator(self.manifest.friction_config)
        self._slippage_calculator = self._build_slippage_calculator(self.manifest.friction_config)

    def _build_cost_calculator(self, friction: FrictionConfig) -> IndianCostCalculator:
        cost_config = CostModelConfig(
            brokerage_per_crore_or_order=friction.brokerage_per_order,
            stt_rate=friction.stt_rate,
            exchange_turnover_fee_rate=friction.exchange_turnover_fee_rate,
            gst_rate=friction.gst_rate,
            stamp_duty_rate=friction.stamp_duty_rate,
        )
        return IndianCostCalculator(config=cost_config)

    def _build_slippage_calculator(self, friction: FrictionConfig) -> SlippageCalculator:
        slippage_config = SlippageModelConfig(
            fixed_tick_slippage_pts=friction.fixed_tick_slippage_pts,
            variable_slippage_pct=friction.variable_slippage_pct,
        )
        return SlippageCalculator(config=slippage_config)

    def evaluate_bar_series(
        self,
        bars: List[Dict[str, Any]],
        signals: Optional[List[Dict[str, Any]]] = None,
    ) -> EvaluationResult:
        """Executes evaluation loop over ordered OHLCV bar series.
        
        `bars` should be sorted chronologically by timestamp.
        `signals` list contains order triggers: dict with `bar_index` or `timestamp`, `side`, `quantity`.
        """
        if not bars:
            raise ValueError("Evaluation bar series cannot be empty.")

        cash = self.manifest.initial_capital
        equity = cash
        position_qty = 0
        position_avg_cost = 0.0

        equity_curve: List[Tuple[datetime, float]] = []
        trades: List[EvaluationTrade] = []

        total_gross_pnl = 0.0
        total_friction_cost = 0.0

        signal_map = {}
        if signals:
            for s in signals:
                idx = s.get("bar_index")
                if idx is not None:
                    signal_map[idx] = s

        current_sim_time: Optional[datetime] = None

        for idx, bar in enumerate(bars):
            bar_ts = bar["timestamp"]
            if isinstance(bar_ts, str):
                bar_ts = datetime.fromisoformat(bar_ts.replace("Z", "+00:00"))

            # Strict chronological order check & look-ahead guard
            if current_sim_time is not None and bar_ts < current_sim_time:
                raise LookAheadBiasError(
                    f"Bar timestamp ({bar_ts}) is earlier than current simulation time ({current_sim_time})."
                )
            current_sim_time = bar_ts

            close_price = float(bar["close"])

            # Check if signal exists for current bar
            if idx in signal_map:
                sig = signal_map[idx]
                side_str = sig["side"].upper()
                order_side = OrderSide.BUY if side_str == "BUY" else OrderSide.SELL
                qty = int(sig.get("quantity", 1))

                # Calculate slippage & fill price
                fill_price, slip_pts = self._slippage_calculator.calculate_fill_price(
                    side=order_side,
                    base_price=close_price,
                )

                # Calculate statutory costs
                trans_cost = self._cost_calculator.calculate_transaction_costs(
                    side=order_side,
                    quantity=qty,
                    price=fill_price,
                    is_intraday=True,
                )

                total_friction_cost += trans_cost + (slip_pts * qty)

                pnl = 0.0
                if order_side == OrderSide.BUY:
                    cash -= (fill_price * qty + trans_cost)
                    position_qty += qty
                    position_avg_cost = fill_price
                else:
                    gross_proceeds = fill_price * qty
                    cost_basis = position_avg_cost * qty if position_qty >= qty else fill_price * qty
                    pnl = (gross_proceeds - cost_basis) - trans_cost
                    total_gross_pnl += (gross_proceeds - cost_basis)
                    cash += (gross_proceeds - trans_cost)
                    position_qty = max(0, position_qty - qty)

                trade = EvaluationTrade(
                    trade_id=f"trd_{idx}_{len(trades)+1}",
                    symbol=bar.get("symbol", "UNKNOWN"),
                    side=side_str,
                    quantity=qty,
                    base_price=close_price,
                    fill_price=fill_price,
                    slippage_pts=slip_pts,
                    transaction_cost=trans_cost,
                    timestamp=bar_ts,
                    pnl=pnl,
                )
                trades.append(trade)

            # Update equity
            equity = cash + (position_qty * close_price)
            equity_curve.append((bar_ts, round(equity, 4)))

        final_equity = equity_curve[-1][1] if equity_curve else cash
        total_net_return = (final_equity - self.manifest.initial_capital) / self.manifest.initial_capital
        total_gross_return = total_gross_pnl / self.manifest.initial_capital

        winning_count = sum(1 for t in trades if t.pnl > 0.0)
        losing_count = sum(1 for t in trades if t.pnl < 0.0)

        return EvaluationResult(
            experiment_id=self.manifest.experiment_id,
            strategy_id=self.manifest.strategy_id,
            dataset_id=self.manifest.dataset_id,
            initial_capital=self.manifest.initial_capital,
            final_equity=round(final_equity, 4),
            total_net_return=round(total_net_return, 6),
            total_gross_return=round(total_gross_return, 6),
            total_friction_cost=round(total_friction_cost, 4),
            total_trades_count=len(trades),
            winning_trades_count=winning_count,
            losing_trades_count=losing_count,
            equity_curve=equity_curve,
            trades=trades,
            execution_environment=self.manifest.environment,
        )
