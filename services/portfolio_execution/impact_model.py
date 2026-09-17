"""
Algo Lab — Stage 10 Dynamic Market Impact Model
"""

import math
from typing import Dict, Any
from services.portfolio_execution.contracts import MarketImpactConfig, ExecutionError


class MarketImpactModel:
    """Calculates non-linear square-root market impact cost based on order size, ADV, and volatility."""

    @staticmethod
    def calculate_market_impact(
        order_quantity: int,
        bar_volume: int,
        price: float,
        volatility_pct: float = 0.02,
        adv: float = 10000.0,
        config: MarketImpactConfig = None,
    ) -> float:
        """Calculates square-root market impact cost in price units per share.

        Returns:
            impact_price_delta (float >= 0.0)
        """
        if config is None:
            config = MarketImpactConfig()

        # Non-finite check (INV-37 / AT-174)
        for name, val in [("order_quantity", order_quantity), ("bar_volume", bar_volume),
                          ("price", price), ("volatility_pct", volatility_pct), ("adv", adv)]:
            if isinstance(val, (int, float)):
                if math.isnan(val) or math.isinf(val):
                    raise ExecutionError(f"Non-finite input in market impact model for {name}: {val}")

        if order_quantity <= 0 or bar_volume <= 0 or price <= 0.0 or adv <= 0.0:
            return 0.0

        # Dynamic Square-Root Market Impact Model (INV-41 / AT-169)
        # Impact = gamma * price * volatility * sqrt(order_quantity / adv)
        ratio = order_quantity / adv
        impact = config.gamma_impact_coefficient * price * volatility_pct * math.sqrt(ratio)
        return round(max(0.0, impact), 6)
