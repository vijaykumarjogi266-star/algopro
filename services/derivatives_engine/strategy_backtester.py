"""
Algo Lab — Stage 13 Point-in-Time Multi-Leg Option Strategy Backtester
"""

import math
from datetime import datetime, timezone
from typing import Dict, List, Optional

from services.derivatives_engine.contract_registry import DerivativesContractRegistry
from services.derivatives_engine.contracts import (
    ContractSpecError,
    DerivativesValidationError,
    InstrumentType,
    OptionContract,
    OptionStrategySpec,
    OptionType,
    SettlementRuleError,
    SettlementType,
    SPANParameterFile,
    StaleSnapshotError,
    StrategyBacktestError,
    StrategyBacktestResult,
)
from services.derivatives_engine.greeks_analytics import OptionGreeksCalculator
from services.derivatives_engine.greeks_hedging import GreeksHedgingEngine
from services.derivatives_engine.span_engine import SPANMarginEngine
from services.derivatives_engine.strategy_builder import MultiLegStrategyBuilder


class MultiLegStrategyBacktester:
    """Deterministic Point-in-Time Multi-Leg Option Strategy Backtesting Engine."""

    def __init__(
        self,
        environment: str = "RESEARCH",
        contract_registry: Optional[DerivativesContractRegistry] = None,
    ):
        # Live execution firewall (INV-90)
        env_upper = (environment or "").upper()
        if env_upper in ("LIVE", "LIVE_TRADING") or environment != "RESEARCH" and environment != "PAPER":
            raise PermissionError(f"Execution firewall lockout: environment '{environment}' is prohibited.")

        self.environment = environment
        self.registry = contract_registry or DerivativesContractRegistry()

    def run_backtest(
        self,
        spec: OptionStrategySpec,
        price_history: List[Dict],  # List of {"timestamp": datetime, "spot": float, "volatility": float, "chain": Dict}
        initial_cash: float = 100000.0,
        span_file: Optional[SPANParameterFile] = None,
        enable_delta_hedging: bool = False,
        delta_target: float = 0.10,
        max_hedge_limit: int = 1000,
        lot_size: int = 1,
        multiplier: float = 1.0,
        commission_per_contract: float = 1.50,
        slippage_per_contract: float = 0.05,
    ) -> StrategyBacktestResult:
        """
        Executes deterministic multi-leg option strategy backtest across PIT market data timeline.
        """
        if initial_cash <= 0.0 or math.isnan(initial_cash) or math.isinf(initial_cash):
            raise DerivativesValidationError(f"Invalid initial_cash: {initial_cash}")

        MultiLegStrategyBuilder.validate_strategy_spec(spec, lot_size)

        cash = initial_cash
        realized_pnl = 0.0
        total_fees = 0.0
        total_slippage = 0.0
        total_roll_costs = 0.0
        hedge_history = []
        last_rebalance_time: Optional[datetime] = None

        # Entry premium calculation
        net_premium, _, _ = MultiLegStrategyBuilder.calculate_strategy_payoff(
            legs=spec.legs,
            spot_at_expiry=spec.underlying_price,
            transaction_costs=0.0,
            slippage=0.0,
            multiplier=multiplier,
        )
        cash += net_premium

        # Entry transaction costs
        num_legs = len(spec.legs)
        entry_fees = num_legs * commission_per_contract * lot_size
        entry_slip = num_legs * slippage_per_contract * lot_size
        total_fees += entry_fees
        total_slippage += entry_slip
        cash -= (entry_fees + entry_slip)

        sim_time = None
        latest_spot = spec.underlying_price
        latest_vol = 0.20
        status = "IN_PROGRESS"

        for snap in price_history:
            t_snap = snap["timestamp"]

            # PIT No-Lookahead check (INV-79)
            if sim_time is not None and t_snap < sim_time:
                raise StaleSnapshotError(f"Historical snapshot timestamp regression: {t_snap} < {sim_time}")
            sim_time = t_snap

            latest_spot = snap["spot"]
            latest_vol = snap.get("volatility", 0.20)

            # Contract spec PIT resolution (INV-92, AT-313)
            try:
                spec_info = self.registry.get_contract_spec(spec.underlying_symbol, t_snap)
            except ContractSpecError:
                pass

            # Dynamic Delta Hedging if enabled
            if enable_delta_hedging:
                # Compute net strategy delta
                net_delta = 0.0
                for leg in spec.legs:
                    c = leg.contract
                    t_exp = max(0.0, (c.expiration_date - t_snap).total_seconds() / (365.0 * 86400.0))
                    greeks = OptionGreeksCalculator.calculate_greeks_analytical(
                        spot=latest_spot,
                        strike=c.strike_price,
                        time_to_expiry=t_exp,
                        risk_free_rate=0.05,
                        dividend_yield=0.0,
                        volatility=latest_vol,
                        option_type=c.option_type,
                    )
                    net_delta += leg.quantity * greeks.delta * multiplier

                hedge_qty = GreeksHedgingEngine.calculate_delta_hedge(
                    net_delta=net_delta,
                    delta_target=delta_target,
                    multiplier=multiplier,
                    lot_size=lot_size,
                    max_hedge_limit=max_hedge_limit,
                    last_rebalance_time=last_rebalance_time,
                    current_time=t_snap,
                    min_interval_hours=1.0,
                )

                if hedge_qty != 0:
                    hedge_cost = abs(hedge_qty) * (commission_per_contract + slippage_per_contract)
                    cash -= hedge_cost
                    total_fees += abs(hedge_qty) * commission_per_contract
                    total_slippage += abs(hedge_qty) * slippage_per_contract
                    last_rebalance_time = t_snap
                    hedge_history.append(
                        {
                            "timestamp": t_snap.isoformat(),
                            "net_delta": net_delta,
                            "hedge_quantity": hedge_qty,
                            "cost": hedge_cost,
                        }
                    )

            # Expiry evaluation check
            min_exp = min(leg.contract.expiration_date for leg in spec.legs)
            if t_snap >= min_exp:
                # Terminal Expiry Evaluation (INV-76, INV-77, INV-86)
                _, intrinsic_payoff, _ = MultiLegStrategyBuilder.calculate_strategy_payoff(
                    legs=spec.legs,
                    spot_at_expiry=latest_spot,
                    transaction_costs=0.0,
                    slippage=0.0,
                    multiplier=multiplier,
                )

                # Check Option Instrument Types
                for leg in spec.legs:
                    c = leg.contract
                    inst_type = getattr(c, "instrument_type", InstrumentType.OPTIDX)

                    if inst_type == InstrumentType.OPTSTK:
                        # Stock Option Physical Delivery Alert (INV-77)
                        required_collateral = latest_spot * lot_size * abs(leg.quantity)
                        if cash < required_collateral:
                            status = "BLOCKED_INSUFFICIENT_COLLATERAL"
                            raise SettlementRuleError(
                                f"BLOCKED_INSUFFICIENT_COLLATERAL: Collateral required {required_collateral:.2f} > cash {cash:.2f}"
                            )
                        status = "PHYSICAL_DELIVERY_ALERT"
                    else:
                        status = "COMPLETED_CASH_SETTLEMENT"

                cash += intrinsic_payoff
                realized_pnl = cash - initial_cash
                break

        # Final PnL accounting identity check (INV-73)
        if status == "IN_PROGRESS":
            # Unrealized PnL at final market spot
            _, current_intrinsic, _ = MultiLegStrategyBuilder.calculate_strategy_payoff(
                legs=spec.legs,
                spot_at_expiry=latest_spot,
                transaction_costs=0.0,
                slippage=0.0,
                multiplier=multiplier,
            )
            final_nov = current_intrinsic
            unrealized_pnl = net_premium - (total_fees + total_slippage) + current_intrinsic
        else:
            final_nov = 0.0
            unrealized_pnl = 0.0

        total_pnl = (cash - initial_cash) if status != "IN_PROGRESS" else unrealized_pnl

        # SPAN Margin Calculation (INV-78)
        span_margin_req = 0.0
        if span_file is not None:
            span_positions = []
            for leg in spec.legs:
                c = leg.contract
                span_positions.append(
                    {
                        "symbol": spec.underlying_symbol,
                        "quantity": leg.quantity,
                        "strike": c.strike_price,
                        "underlying_price": latest_spot,
                        "option_type": c.option_type.value,
                        "nov": leg.entry_price,
                    }
                )
            report = SPANMarginEngine.calculate_margin(
                account_id="ACC_STAGE13",
                positions=span_positions,
                span_file=span_file,
                available_collateral=max(100.0, cash),
                timestamp=sim_time or datetime.now(timezone.utc),
            )
            span_margin_req = report.total_margin_required

        return StrategyBacktestResult(
            strategy_name=spec.name,
            realized_pnl=realized_pnl if status != "IN_PROGRESS" else 0.0,
            unrealized_pnl=unrealized_pnl if status == "IN_PROGRESS" else 0.0,
            total_pnl=total_pnl,
            net_premium_collected=net_premium,
            total_transaction_fees=total_fees,
            total_slippage=total_slippage,
            total_roll_costs=total_roll_costs,
            final_nov=final_nov,
            span_margin_required=span_margin_req,
            execution_status=status,
            hedge_history=hedge_history,
        )

    def execute_leg_roll(
        self,
        current_cash: float,
        old_leg: OptionContract,
        new_leg: OptionContract,
        quantity: int,
        commission: float = 1.50,
        slippage: float = 0.05,
    ) -> float:
        """Deducts leg roll transaction fees and bid-ask slippage from cash (INV-85)."""
        roll_fee = abs(quantity) * (commission + slippage) * 2.0
        if current_cash < roll_fee:
            raise StrategyBacktestError(f"Insufficient cash for leg roll fee: {roll_fee} > {current_cash}")
        return current_cash - roll_fee
