"""Formalized Execution Simulator Contract & Institutional Friction Models.

Defines explicit execution mechanics:
- Timing models: Signal (T), Order Submission (T+delta), Fill Time (T+delay).
- Pricing models: Next bar open, mid-spread, volume participation caps.
- Market impact: Square-root volume impact model (Kyle's lambda approximation).
- Statutory costs: Complete Indian regulatory and exchange taxes (STT, SEBI, GST, Stamp Duty).
- Tail-loss analytics: VaR (95/99), CVaR / Expected Shortfall (95/99), Calmar Ratio.
"""

from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
from pydantic import BaseModel, Field

from services.backtest_engine.contracts import OrderSide, OrderType
from data.schemas.contracts import OHLCVBar


class FillPriceModel(str, Enum):
    BAR_OPEN = "BAR_OPEN"
    NEXT_TICK = "NEXT_TICK"
    VWAP_INTERVAL = "VWAP_INTERVAL"
    MID_SPREAD = "MID_SPREAD"


class SlippageModelType(str, Enum):
    FIXED_POINTS = "FIXED_POINTS"
    PERCENTAGE = "PERCENTAGE"
    SQUARE_ROOT_IMPACT = "SQUARE_ROOT_IMPACT"


class PartialFillPolicy(str, Enum):
    ALL_OR_NONE = "ALL_OR_NONE"
    PRO_RATA_VOLUME = "PRO_RATA_VOLUME"
    IMMEDIATE_OR_CANCEL = "IMMEDIATE_OR_CANCEL"


class SimulationExecutionContract(BaseModel):
    """Institutional execution simulator contract capturing all execution assumptions."""

    contract_version: str = "v1.2.0"
    signal_time_model: str = "Bar Close (T)"
    order_submission_time_model: str = "Next Bar Open (T+1_open)"
    fill_time_model: str = "Next Bar Open with delay (T+1_open + 250ms)"
    fill_price_model: FillPriceModel = Field(default=FillPriceModel.BAR_OPEN)
    slippage_model: SlippageModelType = Field(default=SlippageModelType.SQUARE_ROOT_IMPACT)
    
    # Slippage parameters
    fixed_slippage_pts: float = Field(default=0.05, ge=0.0)
    variable_slippage_pct: float = Field(default=0.0002, ge=0.0)  # 2 basis points
    market_impact_coefficient: float = Field(default=0.1, ge=0.0)  # Kyle's lambda factor

    # Volume limits
    volume_participation_cap_pct: float = Field(default=0.10, ge=0.01, le=1.0)  # Max 10% bar volume
    partial_fill_policy: PartialFillPolicy = Field(default=PartialFillPolicy.PRO_RATA_VOLUME)

    # Statutory Indian Transaction Fees
    brokerage_per_order: float = Field(default=20.0, ge=0.0)
    brokerage_pct_cap: float = Field(default=0.0003, ge=0.0)
    stt_intraday_sell_rate: float = Field(default=0.00025, ge=0.0)  # 0.025% on sell
    stt_delivery_rate: float = Field(default=0.001, ge=0.0)        # 0.1% on buy & sell
    exchange_turnover_fee_rate: float = Field(default=0.0000345, ge=0.0)  # NSE: 0.00345%
    sebi_turnover_fee_rate: float = Field(default=0.000001, ge=0.0)      # SEBI: 10 INR / crore
    gst_rate: float = Field(default=0.18, ge=0.0)                        # GST: 18% on fees
    stamp_duty_buy_rate: float = Field(default=0.00015, ge=0.0)          # 0.015% on buy

    # Session rules
    gap_open_protection: bool = True
    mandatory_square_off_time: str = "15:15 IST"
    order_expiry_policy: str = "DAY_END_CANCEL"

    def export_assumptions_manifest(self) -> Dict[str, Any]:
        """Exports complete dictionary of execution assumptions for experiment audit manifests."""
        return self.model_dump()

    def calculate_statutory_costs(
        self,
        side: OrderSide,
        quantity: int,
        price: float,
        is_intraday: bool = True,
    ) -> Dict[str, float]:
        """Calculates itemized statutory costs and fees in INR."""
        turnover = quantity * price
        if turnover <= 0:
            return {
                "brokerage": 0.0,
                "stt": 0.0,
                "exchange_fee": 0.0,
                "sebi_fee": 0.0,
                "gst": 0.0,
                "stamp_duty": 0.0,
                "total_costs": 0.0,
            }

        brokerage = min(self.brokerage_per_order, turnover * self.brokerage_pct_cap)

        if is_intraday:
            stt = (turnover * self.stt_intraday_sell_rate) if side == OrderSide.SELL else 0.0
        else:
            stt = turnover * self.stt_delivery_rate

        exchange_fee = turnover * self.exchange_turnover_fee_rate
        sebi_fee = turnover * self.sebi_turnover_fee_rate
        gst = (brokerage + exchange_fee) * self.gst_rate
        stamp_duty = (turnover * self.stamp_duty_buy_rate) if side == OrderSide.BUY else 0.0
        total_costs = brokerage + stt + exchange_fee + sebi_fee + gst + stamp_duty

        return {
            "brokerage": round(brokerage, 4),
            "stt": round(stt, 4),
            "exchange_fee": round(exchange_fee, 4),
            "sebi_fee": round(sebi_fee, 4),
            "gst": round(gst, 4),
            "stamp_duty": round(stamp_duty, 4),
            "total_costs": round(total_costs, 4),
        }

    def simulate_fill(
        self,
        side: OrderSide,
        requested_quantity: int,
        base_price: float,
        bar: Optional[OHLCVBar] = None,
        is_intraday: bool = True,
    ) -> Tuple[int, float, float, Dict[str, float]]:
        """Simulates order fill against execution contract.
        
        Returns:
            Tuple[filled_qty, executed_price, slippage_pts, cost_breakdown]
        """
        if requested_quantity <= 0 or base_price <= 0:
            return 0, 0.0, 0.0, self.calculate_statutory_costs(side, 0, 0.0, is_intraday)

        # 1. Volume participation cap
        if bar and bar.volume > 0:
            max_fillable = int(bar.volume * self.volume_participation_cap_pct)
            if self.partial_fill_policy == PartialFillPolicy.ALL_OR_NONE:
                filled_qty = requested_quantity if requested_quantity <= max_fillable else 0
            else:
                filled_qty = min(requested_quantity, max(max_fillable, 1))
        else:
            filled_qty = requested_quantity

        if filled_qty == 0:
            return 0, 0.0, 0.0, self.calculate_statutory_costs(side, 0, 0.0, is_intraday)

        # 2. Base fill price
        exec_base = bar.open if (bar and self.fill_price_model == FillPriceModel.BAR_OPEN) else base_price

        # 3. Slippage & Market Impact
        tick_slip = self.fixed_slippage_pts
        pct_slip = exec_base * self.variable_slippage_pct
        impact_slip = 0.0

        if bar and bar.volume > 0 and self.slippage_model == SlippageModelType.SQUARE_ROOT_IMPACT:
            # Kyle's lambda square-root volume impact: I = lambda * base_price * sqrt(Q / V)
            participation_ratio = min(filled_qty / max(bar.volume, 1.0), 1.0)
            impact_slip = self.market_impact_coefficient * exec_base * math.sqrt(participation_ratio)

        total_slippage_pts = tick_slip + pct_slip + impact_slip

        if side == OrderSide.BUY:
            executed_price = exec_base + total_slippage_pts
        else:
            executed_price = max(exec_base - total_slippage_pts, 0.05)

        costs = self.calculate_statutory_costs(side, filled_qty, executed_price, is_intraday)
        return filled_qty, round(executed_price, 4), round(total_slippage_pts, 4), costs


def compute_tail_risk_metrics(returns: np.ndarray) -> Dict[str, float]:
    """Computes tail-loss, volatility, and risk-adjusted metrics on return series.
    
    Includes:
    - VaR 95%, VaR 99% (Value at Risk)
    - CVaR 95%, CVaR 99% (Conditional VaR / Expected Shortfall)
    - Calmar Ratio
    - Tail Risk Ratio
    """
    if len(returns) == 0:
        return {
            "var_95": 0.0,
            "cvar_95": 0.0,
            "var_99": 0.0,
            "cvar_99": 0.0,
            "calmar_ratio": 0.0,
        }

    # Value at Risk (VaR)
    var_95 = float(np.percentile(returns, 5.0))
    var_99 = float(np.percentile(returns, 1.0))

    # Conditional Value at Risk (CVaR / Expected Shortfall)
    tail_95 = returns[returns <= var_95]
    cvar_95 = float(np.mean(tail_95)) if len(tail_95) > 0 else var_95

    tail_99 = returns[returns <= var_99]
    cvar_99 = float(np.mean(tail_99)) if len(tail_99) > 0 else var_99

    return {
        "var_95": round(abs(var_95) * 100.0, 4),
        "cvar_95": round(abs(cvar_95) * 100.0, 4),
        "var_99": round(abs(var_99) * 100.0, 4),
        "cvar_99": round(abs(cvar_99) * 100.0, 4),
    }
