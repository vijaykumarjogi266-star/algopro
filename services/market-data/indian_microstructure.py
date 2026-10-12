"""
Algo Lab — Indian Market Microstructure & Exchange Friction Engine.

Implements exchange mechanics for NSE / BSE:
1. Pre-Open Auction (09:00 - 09:15 IST) execution blackout & 1-second stabilization buffer.
2. Dynamic Circuit Limit Band Verification (2%, 5%, 10%, 20% Upper/Lower circuit lock guards).
3. Statutory Friction Breakdown discriminating CNC (Delivery) vs MIS (Intraday):
   - STT: 0.1% CNC buy & sell vs 0.025% MIS sell.
   - Exchange Turnover Charges: 0.00297% NSE / 0.00375% BSE.
   - SEBI Turnover Charges: 0.0001% (Rs 10/crore).
   - Stamp Duty: 0.015% CNC buy vs 0.003% MIS buy.
   - GST: 18% on (Brokerage + Exchange Charges + SEBI Charges).
"""

from __future__ import annotations

from datetime import datetime, time, timezone
from enum import Enum
from typing import Dict, Optional, Tuple
from pydantic import BaseModel, Field


class IndianProductType(str, Enum):
    CNC = "CNC"  # Cash & Carry (Delivery)
    MIS = "MIS"  # Margin Intraday Square-off (Intraday)


class IndianExchange(str, Enum):
    NSE = "NSE"
    BSE = "BSE"


class CircuitBandStatus(BaseModel):
    symbol: str
    reference_close: float
    circuit_band_pct: float
    lower_circuit: float
    upper_circuit: float
    is_at_upper_circuit: bool
    is_at_lower_circuit: bool
    can_buy: bool
    can_sell: bool
    rejection_reason: Optional[str] = None


class StatutoryCostBreakdown(BaseModel):
    product: IndianProductType
    turnover: float
    brokerage: float
    stt: float
    exchange_charges: float
    sebi_charges: float
    stamp_duty: float
    gst: float
    total_cost: float
    cost_bps: float


class IndianMicrostructureEngine:
    """Microstructure validator and tax modeling engine for Indian Cash Equities."""

    # IST Trading Timetable
    PRE_OPEN_START = time(9, 0)
    PRE_OPEN_END = time(9, 15)
    MARKET_CLOSE = time(15, 30)

    @classmethod
    def validate_execution_time(
        cls,
        dt_ist: datetime,
        enforce_post_open_buffer: bool = True,
    ) -> Tuple[bool, Optional[str]]:
        """
        Validates if order can be executed based on NSE/BSE session time.
        Rejects pre-open auction orders and enforces 1-second stabilization buffer (09:15:01+).
        """
        t = dt_ist.time()

        if cls.PRE_OPEN_START <= t < cls.PRE_OPEN_END:
            return False, "Order rejected: Pre-open call auction session active (09:00-09:15 IST). Continuous book is inactive."

        if enforce_post_open_buffer and t.hour == 9 and t.minute == 15 and t.second == 0:
            return False, "Order rejected: Pre-open uncrossing 1-second stabilization buffer active (wait until 09:15:01 IST)."

        if t > cls.MARKET_CLOSE:
            return False, "Order rejected: Regular trading session closed at 15:30 IST."

        return True, None

    @classmethod
    def evaluate_circuit_limits(
        cls,
        symbol: str,
        current_price: float,
        previous_close: float,
        circuit_band_pct: float = 0.20,  # e.g., 20% for Nifty 50 or 5%/10% for midcaps
        side: str = "BUY",
    ) -> CircuitBandStatus:
        """
        Validates whether current price is pinned against circuit bands.
        Rejects BUY at Upper Circuit (no sellers in book) and SELL at Lower Circuit (no buyers in book).
        """
        lower = round(previous_close * (1.0 - circuit_band_pct), 2)
        upper = round(previous_close * (1.0 + circuit_band_pct), 2)

        is_upper = current_price >= (upper - 0.05)
        is_lower = current_price <= (lower + 0.05)

        can_buy = not is_upper
        can_sell = not is_lower
        rejection_reason = None

        side_up = side.upper()
        if side_up == "BUY" and is_upper:
            rejection_reason = f"Execution rejected: {symbol} pinned at Upper Circuit (Rs {upper:.2f}). No liquidity / sellers."
        elif side_up == "SELL" and is_lower:
            rejection_reason = f"Execution rejected: {symbol} pinned at Lower Circuit (Rs {lower:.2f}). No liquidity / buyers."

        return CircuitBandStatus(
            symbol=symbol,
            reference_close=previous_close,
            circuit_band_pct=circuit_band_pct,
            lower_circuit=lower,
            upper_circuit=upper,
            is_at_upper_circuit=is_upper,
            is_at_lower_circuit=is_lower,
            can_buy=can_buy,
            can_sell=can_sell,
            rejection_reason=rejection_reason,
        )

    @classmethod
    def calculate_statutory_costs(
        cls,
        side: str,  # "BUY" or "SELL"
        price: float,
        quantity: int,
        product: IndianProductType = IndianProductType.CNC,
        exchange: IndianExchange = IndianExchange.NSE,
        brokerage_per_order: float = 0.0,  # E.g. 0 for Zerodha Delivery, Rs 20 for Intraday
    ) -> StatutoryCostBreakdown:
        """Computes comprehensive Indian equity transaction taxes, turnover fees, and GST."""
        turnover = price * quantity
        side_up = side.upper()

        # 1. Brokerage
        if product == IndianProductType.MIS:
            brokerage = min(20.0, turnover * 0.0003) if brokerage_per_order == 0.0 else brokerage_per_order
        else:
            brokerage = brokerage_per_order  # Discount brokers charge Rs 0 on delivery

        # 2. STT (Securities Transaction Tax)
        if product == IndianProductType.CNC:
            stt = turnover * 0.001  # 0.1% on buy and sell
        else:  # MIS
            stt = turnover * 0.00025 if side_up == "SELL" else 0.0  # 0.025% on sell only

        # 3. Exchange Turnover Charges
        turnover_rate = 0.0000297 if exchange == IndianExchange.NSE else 0.0000375
        exchange_charges = turnover * turnover_rate

        # 4. SEBI Turnover Charges
        sebi_charges = turnover * 0.000001  # Rs 10 per crore

        # 5. Stamp Duty (on BUY only)
        if side_up == "BUY":
            stamp_rate = 0.00015 if product == IndianProductType.CNC else 0.00003
            stamp_duty = turnover * stamp_rate
        else:
            stamp_duty = 0.0

        # 6. GST (18% on Brokerage + Exchange Charges + SEBI Charges)
        gst = (brokerage + exchange_charges + sebi_charges) * 0.18

        total_cost = brokerage + stt + exchange_charges + sebi_charges + stamp_duty + gst
        cost_bps = (total_cost / turnover) * 10_000 if turnover > 0 else 0.0

        return StatutoryCostBreakdown(
            product=product,
            turnover=round(turnover, 2),
            brokerage=round(brokerage, 2),
            stt=round(stt, 2),
            exchange_charges=round(exchange_charges, 2),
            sebi_charges=round(sebi_charges, 2),
            stamp_duty=round(stamp_duty, 2),
            gst=round(gst, 2),
            total_cost=round(total_cost, 2),
            cost_bps=round(cost_bps, 2),
        )
