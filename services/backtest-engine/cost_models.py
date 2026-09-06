"""Indian Market Cost & Slippage Execution Models.

Implements realistic taxation and friction for NSE/BSE:
- STT (Securities Transaction Tax)
- Brokerage
- Exchange turnover fees (NSE)
- SEBI regulatory fees
- GST (18%)
- Stamp Duty (State)
- Configurable slippage (Fixed tick, Percentage, Basis-point)
"""

from typing import Optional, Tuple
from services.backtest_engine.contracts import CostModelConfig, OrderSide, OrderType, SlippageModelConfig
from data.schemas.contracts import OHLCVBar


class IndianCostCalculator:
    """Calculates all statutory taxes, regulatory fees, and brokerage for Indian markets."""

    def __init__(self, config: Optional[CostModelConfig] = None):
        self.config = config or CostModelConfig()

    def calculate_transaction_costs(
        self,
        side: OrderSide,
        quantity: int,
        price: float,
        is_intraday: bool = True,
    ) -> float:
        """Calculates total round-trip or single-leg transaction costs in INR."""
        turnover = quantity * price
        if turnover <= 0:
            return 0.0

        # 1. Brokerage: min(20 INR, 0.03% of turnover)
        brokerage = min(self.config.brokerage_per_crore_or_order, turnover * 0.0003)

        # 2. STT (Securities Transaction Tax)
        if is_intraday:
            # Intraday: 0.025% on SELL side only
            stt = (turnover * 0.00025) if side == OrderSide.SELL else 0.0
        else:
            # Delivery: 0.1% on both BUY and SELL
            stt = turnover * self.config.stt_rate

        # 3. Exchange Turnover Charge (NSE: 0.00345%)
        exchange_fee = turnover * self.config.exchange_turnover_fee_rate

        # 4. SEBI Regulatory Fee (10 INR per crore = 0.0001%)
        sebi_fee = turnover * self.config.sebi_turnover_fee_rate

        # 5. GST (18% on Brokerage + Exchange Fee)
        gst = (brokerage + exchange_fee) * self.config.gst_rate

        # 6. Stamp Duty (0.015% on BUY side only)
        stamp_duty = (turnover * self.config.stamp_duty_rate) if side == OrderSide.BUY else 0.0

        total_costs = brokerage + stt + exchange_fee + sebi_fee + gst + stamp_duty
        return round(total_costs, 4)


class SlippageCalculator:
    """Calculates execution slippage friction against base order price."""

    def __init__(self, config: Optional[SlippageModelConfig] = None):
        self.config = config or SlippageModelConfig()

    def calculate_fill_price(
        self,
        side: OrderSide,
        base_price: float,
        current_bar: Optional[OHLCVBar] = None,
    ) -> Tuple[float, float]:
        """Calculates executed fill price and total slippage in INR points.
        
        Buy orders slip upwards (+), Sell orders slip downwards (-).
        """
        # Fixed tick slippage points
        tick_slippage = self.config.fixed_tick_slippage_pts
        # Percentage slippage
        pct_slippage = base_price * self.config.variable_slippage_pct

        total_slippage_pts = tick_slippage + pct_slippage

        if side == OrderSide.BUY:
            fill_price = base_price + total_slippage_pts
        else:
            fill_price = max(base_price - total_slippage_pts, 0.05)

        return round(fill_price, 4), round(total_slippage_pts, 4)
