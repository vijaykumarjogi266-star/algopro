"""
Algo Lab — Stage 10 Multi-Strategy Execution Router & Volume Participation Engine
"""

from datetime import datetime
from typing import Dict, List, Any, Tuple
import math
import uuid

from services.portfolio_optimization.contracts import RebalancePlan, SolvencyError
from services.portfolio_execution.contracts import (
    MarketImpactConfig,
    ExecutionFill,
    ExecutionError,
)
from services.portfolio_execution.impact_model import MarketImpactModel
from services.market_data.registry import DatasetIntegrityError


class ExecutionRouter:
    """Serializes multi-strategy orders and matches fills against bar volume limits."""

    @staticmethod
    def match_bar_orders(
        rebalance_plan: RebalancePlan,
        bar_data: Dict[str, Dict[str, Any]],     # symbol -> {open, high, low, close, volume}
        current_cash_balance: float,
        config: MarketImpactConfig = None,
        cost_per_trade_pct: float = 0.001,
    ) -> Tuple[List[ExecutionFill], float]:
        """Matches rebalance plan proposed orders against current bar price/volume.

        Returns:
            Tuple[List[ExecutionFill], remaining_cash_balance]
        """
        if config is None:
            config = MarketImpactConfig()

        # 1. Non-finite checks (INV-37 / AT-174)
        if math.isnan(current_cash_balance) or math.isinf(current_cash_balance):
            raise ExecutionError(f"Non-finite cash balance in execution router: {current_cash_balance}")

        proposed_orders = rebalance_plan.proposed_orders
        if not proposed_orders:
            return [], current_cash_balance

        # 2. Sort orders deterministically by strategy_id & symbol (INV-43 / AT-183)
        sorted_orders = sorted(
            proposed_orders,
            key=lambda o: (o.get("strategy_id", "DEFAULT_STRATEGY"), o.get("symbol", ""))
        )

        fills: List[ExecutionFill] = []
        cash_balance = current_cash_balance

        for order in sorted_orders:
            symbol = order["symbol"]
            req_qty = order["quantity"]
            side = order["side"]
            s_id = order.get("strategy_id", "DEFAULT_STRATEGY")

            if symbol not in bar_data:
                continue

            bar = bar_data[symbol]

            # 3. Check for dataset volume missing/corrupted (AT-177 / AT-178)
            if "volume" not in bar:
                raise DatasetIntegrityError(f"Missing bar volume column for symbol '{symbol}'")

            bar_vol = bar["volume"]
            if math.isnan(bar_vol) or math.isinf(bar_vol):
                raise ExecutionError(f"Non-finite bar volume for {symbol}: {bar_vol}")
            if bar_vol < 0:
                raise DatasetIntegrityError(f"Corrupted negative bar volume for {symbol}: {bar_vol}")

            price = bar.get("close", order.get("price", 0.0))
            if math.isnan(price) or math.isinf(price) or price <= 0.0:
                raise ExecutionError(f"Invalid bar close price for {symbol}: {price}")

            # 4. Zero Bar Volume Illiquidity Lockout (AT-173)
            if bar_vol == 0:
                fill_qty = 0
            else:
                # 5. Volume Participation Rate Cap (INV-40 / AT-168)
                max_fillable = int(bar_vol * config.max_volume_participation_pct)
                fill_qty = min(req_qty, max_fillable)

            is_partial = fill_qty < req_qty
            remaining = req_qty - fill_qty

            if fill_qty == 0:
                # Fill quantity zero -> Deferred fill record
                fill = ExecutionFill(
                    fill_id=str(uuid.uuid4())[:8],
                    order_id=order.get("order_id", "ORD_001"),
                    strategy_id=s_id,
                    symbol=symbol,
                    fill_timestamp=rebalance_plan.simulation_time,
                    fill_quantity=0,
                    fill_price=price,
                    market_impact_cost=0.0,
                    slippage_cost=0.0,
                    transaction_fee=0.0,
                    is_partial_fill=True,
                    remaining_quantity=req_qty,
                )
                fills.append(fill)
                continue

            # 6. Dynamic Market Impact Cost (INV-41 / AT-169)
            adv = bar.get("adv", bar_vol * 10.0)
            volatility = bar.get("volatility", 0.02)
            impact_delta = MarketImpactModel.calculate_market_impact(
                order_quantity=fill_qty,
                bar_volume=bar_vol,
                price=price,
                volatility_pct=volatility,
                adv=adv,
                config=config,
            )

            fill_price = price + impact_delta if side == "BUY" else max(0.01, price - impact_delta)
            order_val = fill_qty * fill_price
            fee = order_val * cost_per_trade_pct

            # 7. Pre-Trade Cash Solvency Verification (INV-32 / AT-187)
            if side == "BUY":
                req_cash = order_val + fee
                if req_cash > cash_balance + 1e-6:
                    raise SolvencyError(
                        f"Order fill cost ₹{req_cash:.2f} exceeds available cash ₹{cash_balance:.2f}"
                    )
                cash_balance -= req_cash
            else:
                cash_balance += (order_val - fee)

            fill = ExecutionFill(
                fill_id=str(uuid.uuid4())[:8],
                order_id=order.get("order_id", "ORD_001"),
                strategy_id=s_id,
                symbol=symbol,
                fill_timestamp=rebalance_plan.simulation_time,
                fill_quantity=fill_qty,
                fill_price=round(fill_price, 4),
                market_impact_cost=round(impact_delta * fill_qty, 2),
                slippage_cost=round(impact_delta, 4),
                transaction_fee=round(fee, 2),
                is_partial_fill=is_partial,
                remaining_quantity=remaining,
            )
            fills.append(fill)

        return fills, cash_balance
