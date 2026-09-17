"""
Algo Lab — Stage 9 Multi-Strategy Portfolio Rebalancer & Solvency Guard
"""

from datetime import date, datetime
from typing import Dict, List, Any, Tuple
import math

from services.portfolio_optimization.contracts import (
    RebalancePlan,
    AllocationError,
    SolvencyError,
)


class PortfolioRebalancer:
    """Translates target strategy weights into discrete asset orders while enforcing solvency & turnover limits."""

    @staticmethod
    def generate_rebalance_plan(
        rebalance_date: date,
        sim_time: datetime,
        current_portfolio_value: float,
        current_cash_balance: float,
        target_weights: Dict[str, float],
        target_cash_weight: float,
        current_positions: Dict[str, int],       # symbol -> share count
        asset_prices: Dict[str, float],          # symbol -> close price
        cost_per_trade_pct: float = 0.001,       # 0.10% friction estimate
        max_turnover_pct: float = 1.0,
    ) -> RebalancePlan:
        """Generates deterministic asset-level rebalance orders.

        Returns:
            RebalancePlan
        """
        # 1. Non-finite checks (INV-37)
        for name, val in [("portfolio_value", current_portfolio_value), ("cash_balance", current_cash_balance)]:
            if math.isnan(val) or math.isinf(val):
                raise AllocationError(f"Non-finite portfolio value or cash: {name}={val}")

        for s_id, w in target_weights.items():
            if math.isnan(w) or math.isinf(w):
                raise AllocationError(f"Non-finite weight for {s_id}: {w}")

        proposed_orders: List[Dict[str, Any]] = []
        total_buy_value = 0.0
        total_sell_value = 0.0
        residual_unallocated_cash = 0.0

        # Calculate target equity capital
        total_allocated_weight = sum(target_weights.values())
        total_equity_capital = current_portfolio_value * total_allocated_weight

        # Determine target allocation per symbol
        if target_weights and len(target_weights) > 0:
            weight_per_symbol = total_allocated_weight / len(asset_prices) if asset_prices else 0.0
        else:
            weight_per_symbol = 0.0

        # Sort symbols deterministically by string alphabetical order (INV-31)
        sorted_symbols = sorted(asset_prices.keys())

        for symbol in sorted_symbols:
            price = asset_prices[symbol]
            if price <= 0.0 or math.isnan(price) or math.isinf(price):
                raise AllocationError(f"Invalid asset price for {symbol}: {price}")

            curr_qty = current_positions.get(symbol, 0)
            target_symbol_capital = current_portfolio_value * weight_per_symbol
            
            # Discrete integer share calculation
            target_qty = int(target_symbol_capital // price)
            actual_symbol_capital = target_qty * price
            
            # Residual fractional share cash remainder (INV-38 / AT-166)
            residual = target_symbol_capital - actual_symbol_capital
            if residual > 0.0:
                residual_unallocated_cash += residual

            qty_delta = target_qty - curr_qty
            if qty_delta != 0:
                order_val = abs(qty_delta) * price
                side = "BUY" if qty_delta > 0 else "SELL"
                if side == "BUY":
                    total_buy_value += order_val
                else:
                    total_sell_value += order_val

                proposed_orders.append(
                    {
                        "symbol": symbol,
                        "side": side,
                        "quantity": abs(qty_delta),
                        "price": price,
                        "order_value": order_val,
                    }
                )

        # Turnover calculation & capping (AT-160)
        total_traded_value = total_buy_value + total_sell_value
        estimated_turnover_pct = total_traded_value / current_portfolio_value if current_portfolio_value > 0 else 0.0

        if estimated_turnover_pct > max_turnover_pct and total_traded_value > 0:
            scale = max_turnover_pct / estimated_turnover_pct
            total_buy_value = 0.0
            total_sell_value = 0.0
            for order in proposed_orders:
                order["quantity"] = int(order["quantity"] * scale)
                order["order_value"] = order["quantity"] * order["price"]
                if order["side"] == "BUY":
                    total_buy_value += order["order_value"]
                else:
                    total_sell_value += order["order_value"]
            estimated_turnover_pct = (total_buy_value + total_sell_value) / current_portfolio_value

        # Friction cost estimation
        estimated_friction = (total_buy_value + total_sell_value) * cost_per_trade_pct

        # Solvency verification (INV-32 / AT-140)
        required_cash = total_buy_value + estimated_friction
        available_cash = current_cash_balance + total_sell_value

        if required_cash > available_cash + 1e-6:
            raise SolvencyError(
                f"Required cash ₹{required_cash:.2f} exceeds available cash ₹{available_cash:.2f} (friction: ₹{estimated_friction:.2f})"
            )

        # Adjust final cash weight with unallocated share residual (INV-38)
        residual_weight_adj = residual_unallocated_cash / current_portfolio_value if current_portfolio_value > 0 else 0.0
        final_cash_weight = round(target_cash_weight + residual_weight_adj, 6)

        return RebalancePlan(
            rebalance_date=rebalance_date,
            simulation_time=sim_time,
            target_weights=target_weights,
            target_cash_weight=final_cash_weight,
            proposed_orders=proposed_orders,
            estimated_turnover_pct=round(estimated_turnover_pct, 6),
            estimated_friction_cost=round(estimated_friction, 2),
            residual_cash_unallocated=round(residual_unallocated_cash, 2),
        )
