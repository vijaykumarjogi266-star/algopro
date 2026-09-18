"""
Algo Lab — Stage 13 Multi-Leg Option Strategy Construction & Payoff Engine
"""

import math
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from services.derivatives_engine.contracts import (
    ContractSpecError,
    DerivativesValidationError,
    ExerciseStyle,
    InstrumentType,
    OptionContract,
    OptionGreeks,
    OptionLeg,
    OptionStrategySpec,
    OptionType,
    StrategyType,
)


class MultiLegStrategyBuilder:
    """Engine for constructing, validating, and pricing multi-leg option strategies."""

    @staticmethod
    def validate_strategy_spec(
        spec: OptionStrategySpec,
        lot_size: int = 1,
    ) -> None:
        """Enforces leg uniqueness, non-finite bounds, and lot-size integrity."""
        if not spec.legs:
            raise DerivativesValidationError("Strategy must contain at least one leg")

        seen_legs = set()
        for leg in spec.legs:
            c = leg.contract
            # Check non-finite parameters
            for name, val in [
                ("strike_price", c.strike_price),
                ("entry_price", leg.entry_price),
                ("quantity", float(leg.quantity)),
                ("underlying_price", spec.underlying_price),
            ]:
                if math.isnan(val) or math.isinf(val):
                    raise DerivativesValidationError(f"Non-finite value in strategy spec for '{name}': {val}")

            # Check lot size modulo integrity (INV-84)
            if lot_size > 0 and abs(leg.quantity) % lot_size != 0:
                raise ContractSpecError(
                    f"Leg quantity {leg.quantity} is not an integer multiple of contract lot size {lot_size}"
                )

            # Duplicate leg key check (INV-94)
            leg_key = (c.symbol, c.option_type, c.strike_price, c.expiration_date, leg.quantity > 0)
            if leg_key in seen_legs:
                raise DerivativesValidationError(f"Duplicate or redundant strategy leg definition: {leg_key}")
            seen_legs.add(leg_key)

    @staticmethod
    def compute_aggregate_greeks(
        legs: List[OptionLeg],
        leg_greeks: List[OptionGreeks],
        multiplier: float = 1.0,
    ) -> OptionGreeks:
        """Computes aggregate net portfolio Greeks via linear superposition (INV-74)."""
        if len(legs) != len(leg_greeks):
            raise DerivativesValidationError("Mismatched legs and leg_greeks length")

        net_delta = 0.0
        net_gamma = 0.0
        net_vega = 0.0
        net_theta = 0.0
        net_rho = 0.0

        for leg, g in zip(legs, leg_greeks):
            qty = float(leg.quantity)
            net_delta += qty * g.delta * multiplier
            net_gamma += qty * g.gamma * multiplier
            net_vega += qty * g.vega * multiplier
            net_theta += qty * g.theta * multiplier
            net_rho += qty * g.rho * multiplier

        return OptionGreeks(
            delta=net_delta,
            gamma=net_gamma,
            vega=net_vega,
            theta=net_theta,
            rho=net_rho,
        )

    @staticmethod
    def calculate_strategy_payoff(
        legs: List[OptionLeg],
        spot_at_expiry: float,
        transaction_costs: float = 0.0,
        slippage: float = 0.0,
        multiplier: float = 1.0,
    ) -> Tuple[float, float, float]:
        """
        Computes net premium collected, terminal intrinsic payoff, and total PnL at expiry (INV-73, INV-93).
        PnL(T) = Premium_net - Costs_total + Sum(qty_k * Intrinsic_k(S_T) * multiplier)
        Returns: (net_premium_collected, terminal_intrinsic_payoff, total_pnl)
        """
        if math.isnan(spot_at_expiry) or math.isinf(spot_at_expiry) or spot_at_expiry < 0.0:
            raise DerivativesValidationError(f"Invalid spot_at_expiry: {spot_at_expiry}")

        net_premium_collected = 0.0
        terminal_intrinsic_payoff = 0.0

        for leg in legs:
            c = leg.contract
            qty = leg.quantity  # >0 for Long, <0 for Short
            entry = leg.entry_price

            # Premium cash flow: Short collects (+), Long pays (-)
            net_premium_collected -= qty * entry * multiplier

            # Terminal intrinsic payoff
            if c.option_type == OptionType.CALL:
                intrinsic = max(0.0, spot_at_expiry - c.strike_price)
            elif c.option_type == OptionType.PUT:
                intrinsic = max(0.0, c.strike_price - spot_at_expiry)
            else:
                intrinsic = 0.0

            terminal_intrinsic_payoff += qty * intrinsic * multiplier

        total_costs = transaction_costs + slippage
        total_pnl = net_premium_collected - total_costs + terminal_intrinsic_payoff

        return net_premium_collected, terminal_intrinsic_payoff, total_pnl


# Standard Factory Helpers
def create_option_leg(
    symbol: str,
    underlying: str,
    strike: float,
    expiry: datetime,
    option_type: OptionType,
    quantity: int,
    entry_price: float,
) -> OptionLeg:
    c = OptionContract(
        symbol=symbol,
        underlying_symbol=underlying,
        strike_price=strike,
        expiration_date=expiry,
        option_type=option_type,
    )
    return OptionLeg(contract=c, quantity=quantity, entry_price=entry_price)


def build_bull_call_spread(
    underlying: str,
    spot: float,
    K1: float,
    K2: float,
    expiry: datetime,
    p1: float,
    p2: float,
    lot_size: int = 1,
    mult: float = 1.0,
) -> OptionStrategySpec:
    if K1 >= K2:
        raise DerivativesValidationError(f"Bull Call Spread requires K1 < K2: K1={K1}, K2={K2}")
    leg1 = create_option_leg(f"{underlying}_C_{K1}", underlying, K1, expiry, OptionType.CALL, lot_size, p1)
    leg2 = create_option_leg(f"{underlying}_C_{K2}", underlying, K2, expiry, OptionType.CALL, -lot_size, p2)
    spec = OptionStrategySpec(
        name="Bull Call Spread",
        strategy_type=StrategyType.BULL_CALL_SPREAD,
        legs=[leg1, leg2],
        underlying_symbol=underlying,
        underlying_price=spot,
    )
    MultiLegStrategyBuilder.validate_strategy_spec(spec, lot_size)
    return spec


def build_bear_call_spread(
    underlying: str,
    spot: float,
    K1: float,
    K2: float,
    expiry: datetime,
    p1: float,
    p2: float,
    lot_size: int = 1,
    mult: float = 1.0,
) -> OptionStrategySpec:
    if K1 >= K2:
        raise DerivativesValidationError(f"Bear Call Spread requires K1 < K2: K1={K1}, K2={K2}")
    leg1 = create_option_leg(f"{underlying}_C_{K1}", underlying, K1, expiry, OptionType.CALL, -lot_size, p1)
    leg2 = create_option_leg(f"{underlying}_C_{K2}", underlying, K2, expiry, OptionType.CALL, lot_size, p2)
    spec = OptionStrategySpec(
        name="Bear Call Spread",
        strategy_type=StrategyType.BEAR_CALL_SPREAD,
        legs=[leg1, leg2],
        underlying_symbol=underlying,
        underlying_price=spot,
    )
    MultiLegStrategyBuilder.validate_strategy_spec(spec, lot_size)
    return spec


def build_bull_put_spread(
    underlying: str,
    spot: float,
    K1: float,
    K2: float,
    expiry: datetime,
    p1: float,
    p2: float,
    lot_size: int = 1,
    mult: float = 1.0,
) -> OptionStrategySpec:
    if K1 >= K2:
        raise DerivativesValidationError(f"Bull Put Spread requires K1 < K2: K1={K1}, K2={K2}")
    leg1 = create_option_leg(f"{underlying}_P_{K1}", underlying, K1, expiry, OptionType.PUT, lot_size, p1)
    leg2 = create_option_leg(f"{underlying}_P_{K2}", underlying, K2, expiry, OptionType.PUT, -lot_size, p2)
    spec = OptionStrategySpec(
        name="Bull Put Spread",
        strategy_type=StrategyType.BULL_PUT_SPREAD,
        legs=[leg1, leg2],
        underlying_symbol=underlying,
        underlying_price=spot,
    )
    MultiLegStrategyBuilder.validate_strategy_spec(spec, lot_size)
    return spec


def build_bear_put_spread(
    underlying: str,
    spot: float,
    K1: float,
    K2: float,
    expiry: datetime,
    p1: float,
    p2: float,
    lot_size: int = 1,
    mult: float = 1.0,
) -> OptionStrategySpec:
    if K1 >= K2:
        raise DerivativesValidationError(f"Bear Put Spread requires K1 < K2: K1={K1}, K2={K2}")
    leg1 = create_option_leg(f"{underlying}_P_{K1}", underlying, K1, expiry, OptionType.PUT, -lot_size, p1)
    leg2 = create_option_leg(f"{underlying}_P_{K2}", underlying, K2, expiry, OptionType.PUT, lot_size, p2)
    spec = OptionStrategySpec(
        name="Bear Put Spread",
        strategy_type=StrategyType.BEAR_PUT_SPREAD,
        legs=[leg1, leg2],
        underlying_symbol=underlying,
        underlying_price=spot,
    )
    MultiLegStrategyBuilder.validate_strategy_spec(spec, lot_size)
    return spec


def build_straddle(
    underlying: str,
    spot: float,
    K: float,
    expiry: datetime,
    p_call: float,
    p_put: float,
    is_long: bool = True,
    lot_size: int = 1,
    mult: float = 1.0,
) -> OptionStrategySpec:
    q = lot_size if is_long else -lot_size
    leg1 = create_option_leg(f"{underlying}_C_{K}", underlying, K, expiry, OptionType.CALL, q, p_call)
    leg2 = create_option_leg(f"{underlying}_P_{K}", underlying, K, expiry, OptionType.PUT, q, p_put)
    spec = OptionStrategySpec(
        name="Straddle",
        strategy_type=StrategyType.STRADDLE,
        legs=[leg1, leg2],
        underlying_symbol=underlying,
        underlying_price=spot,
    )
    MultiLegStrategyBuilder.validate_strategy_spec(spec, lot_size)
    return spec


def build_strangle(
    underlying: str,
    spot: float,
    K1_put: float,
    K2_call: float,
    expiry: datetime,
    p_put: float,
    p_call: float,
    is_long: bool = True,
    lot_size: int = 1,
    mult: float = 1.0,
) -> OptionStrategySpec:
    if K1_put >= K2_call:
        raise DerivativesValidationError(f"Strangle requires K1_put < K2_call: K1={K1_put}, K2={K2_call}")
    q = lot_size if is_long else -lot_size
    leg1 = create_option_leg(f"{underlying}_P_{K1_put}", underlying, K1_put, expiry, OptionType.PUT, q, p_put)
    leg2 = create_option_leg(f"{underlying}_C_{K2_call}", underlying, K2_call, expiry, OptionType.CALL, q, p_call)
    spec = OptionStrategySpec(
        name="Strangle",
        strategy_type=StrategyType.STRANGLE,
        legs=[leg1, leg2],
        underlying_symbol=underlying,
        underlying_price=spot,
    )
    MultiLegStrategyBuilder.validate_strategy_spec(spec, lot_size)
    return spec


def build_iron_condor(
    underlying: str,
    spot: float,
    K1_p: float,
    K2_p: float,
    K3_c: float,
    K4_c: float,
    expiry: datetime,
    prices: List[float],  # [p1, p2, p3, p4]
    lot_size: int = 1,
    mult: float = 1.0,
) -> OptionStrategySpec:
    if not (K1_p < K2_p < K3_c < K4_c):
        raise DerivativesValidationError("Iron Condor requires K1_p < K2_p < K3_c < K4_c")
    if len(prices) != 4:
        raise DerivativesValidationError("Iron Condor requires 4 prices")

    l1 = create_option_leg(f"{underlying}_P_{K1_p}", underlying, K1_p, expiry, OptionType.PUT, lot_size, prices[0])
    l2 = create_option_leg(f"{underlying}_P_{K2_p}", underlying, K2_p, expiry, OptionType.PUT, -lot_size, prices[1])
    l3 = create_option_leg(f"{underlying}_C_{K3_c}", underlying, K3_c, expiry, OptionType.CALL, -lot_size, prices[2])
    l4 = create_option_leg(f"{underlying}_C_{K4_c}", underlying, K4_c, expiry, OptionType.CALL, lot_size, prices[3])

    spec = OptionStrategySpec(
        name="Iron Condor",
        strategy_type=StrategyType.IRON_CONDOR,
        legs=[l1, l2, l3, l4],
        underlying_symbol=underlying,
        underlying_price=spot,
    )
    MultiLegStrategyBuilder.validate_strategy_spec(spec, lot_size)
    return spec


def build_butterfly(
    underlying: str,
    spot: float,
    K1: float,
    K2: float,
    K3: float,
    expiry: datetime,
    prices: List[float],  # [p1, p2, p3]
    lot_size: int = 1,
    mult: float = 1.0,
) -> OptionStrategySpec:
    if not (K1 < K2 < K3):
        raise DerivativesValidationError("Butterfly requires K1 < K2 < K3")
    if len(prices) != 3:
        raise DerivativesValidationError("Butterfly requires 3 prices")

    l1 = create_option_leg(f"{underlying}_C_{K1}", underlying, K1, expiry, OptionType.CALL, lot_size, prices[0])
    l2 = create_option_leg(f"{underlying}_C_{K2}", underlying, K2, expiry, OptionType.CALL, -2 * lot_size, prices[1])
    l3 = create_option_leg(f"{underlying}_C_{K3}", underlying, K3, expiry, OptionType.CALL, lot_size, prices[2])

    spec = OptionStrategySpec(
        name="Butterfly Spread",
        strategy_type=StrategyType.BUTTERFLY,
        legs=[l1, l2, l3],
        underlying_symbol=underlying,
        underlying_price=spot,
    )
    MultiLegStrategyBuilder.validate_strategy_spec(spec, lot_size)
    return spec


def build_collar(
    underlying: str,
    spot: float,
    K_put: float,
    K_call: float,
    expiry: datetime,
    p_put: float,
    p_call: float,
    lot_size: int = 1,
    mult: float = 1.0,
) -> OptionStrategySpec:
    if K_put >= K_call:
        raise DerivativesValidationError("Collar requires K_put < K_call")

    l1 = create_option_leg(f"{underlying}_P_{K_put}", underlying, K_put, expiry, OptionType.PUT, lot_size, p_put)
    l2 = create_option_leg(f"{underlying}_C_{K_call}", underlying, K_call, expiry, OptionType.CALL, -lot_size, p_call)

    spec = OptionStrategySpec(
        name="Collar Protection",
        strategy_type=StrategyType.COLLAR,
        legs=[l1, l2],
        underlying_symbol=underlying,
        underlying_price=spot,
    )
    MultiLegStrategyBuilder.validate_strategy_spec(spec, lot_size)
    return spec


def build_synthetic_long(
    underlying: str,
    spot: float,
    K: float,
    expiry: datetime,
    p_call: float,
    p_put: float,
    lot_size: int = 1,
    mult: float = 1.0,
) -> OptionStrategySpec:
    l1 = create_option_leg(f"{underlying}_C_{K}", underlying, K, expiry, OptionType.CALL, lot_size, p_call)
    l2 = create_option_leg(f"{underlying}_P_{K}", underlying, K, expiry, OptionType.PUT, -lot_size, p_put)

    spec = OptionStrategySpec(
        name="Synthetic Long",
        strategy_type=StrategyType.SYNTHETIC_LONG,
        legs=[l1, l2],
        underlying_symbol=underlying,
        underlying_price=spot,
    )
    MultiLegStrategyBuilder.validate_strategy_spec(spec, lot_size)
    return spec
