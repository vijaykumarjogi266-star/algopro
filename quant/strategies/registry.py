"""Algo Lab Strategy Registry and Dispatcher.

Central registry and dispatcher for all quantitative trading strategies.
Adheres to Non-Negotiable Principles:
- Principle 1: Never force a trade.
- Principle 2: WAIT is a valid decision.
- Principle 8: Every strategy must be versioned.
- One explicit strategy registry/dispatcher.
- Unknown strategy yields WAIT; no generic scanner fallback.
- Validates parameter types and bounded ranges fail-closed before dispatch.
"""

import math
from typing import Any, Dict, List, Optional, Tuple, Type, Union

from quant.strategies.base import BaseStrategy, SignalType, StrategyDecision
from quant.strategies.sma_cross import SMACross
from quant.strategies.vwap_reversion import VWAPReversion
from quant.strategies.orb import OpeningRangeBreakout
from quant.strategies.buy_and_hold import BuyAndHold
from quant.strategies.donchian_breakout import DonchianBreakout
from quant.strategies.bollinger_reversion import BollingerReversion


class StrategyRegistry:
    """Authoritative Registry and Dispatcher for Quantitative Strategies."""

    _registry: Dict[str, Type[BaseStrategy]] = {}

    @classmethod
    def register(cls, strategy_cls: Type[BaseStrategy], aliases: Optional[List[str]] = None) -> None:
        """Register a strategy class under its primary ID and optional aliases."""
        keys = [strategy_cls.__name__]
        if hasattr(strategy_cls, "strategy_id"):
            keys.append(getattr(strategy_cls, "strategy_id"))
        if aliases:
            keys.extend(aliases)

        for key in keys:
            normalized = cls._normalize_key(key)
            cls._registry[normalized] = strategy_cls

    @classmethod
    def _normalize_key(cls, name: Optional[str]) -> str:
        if not name or not isinstance(name, str):
            return ""
        return name.strip().upper().replace(" ", "_").replace("-", "_")

    @classmethod
    def is_registered(cls, name: Optional[str]) -> bool:
        """Check if a strategy identifier is known to the registry."""
        if not name or not isinstance(name, str):
            return False
        normalized = cls._normalize_key(name)
        if normalized in ("", "WAIT", "NONE", "UNKNOWN"):
            return False
        return normalized in cls._registry

    @classmethod
    def get_strategy(
        cls,
        name: Optional[str],
        parameters: Optional[Dict[str, Any]] = None,
    ) -> Optional[BaseStrategy]:
        """Instantiate and return a strategy instance by name/alias, or None if unknown."""
        if not cls.is_registered(name):
            return None
        normalized = cls._normalize_key(name)
        strategy_cls = cls._registry[normalized]
        params = parameters or {}
        try:
            return strategy_cls(parameters=params)
        except TypeError:
            # Fallback if __init__ takes keyword args
            try:
                return strategy_cls(**params)
            except Exception:
                return strategy_cls()

    @classmethod
    def validate_parameters(cls, strategy_name: str, parameters: Any) -> Tuple[bool, Optional[str]]:
        """Validate parameter types and ranges fail-closed before dispatch (C06)."""
        if not isinstance(parameters, dict):
            return False, f"Parameters must be a dictionary, got {type(parameters).__name__}"

        # stop_loss_atr: finite float in (0.0, 20.0]
        if "stop_loss_atr" in parameters:
            val = parameters["stop_loss_atr"]
            if not isinstance(val, (int, float)) or isinstance(val, bool) or math.isnan(val) or math.isinf(val):
                return False, f"stop_loss_atr must be finite numeric, got {val}"
            if val <= 0.0 or val > 20.0:
                return False, f"stop_loss_atr {val} outside valid range (0.0, 20.0]"

        # target_atr: finite float in (0.0, 50.0]
        if "target_atr" in parameters:
            val = parameters["target_atr"]
            if not isinstance(val, (int, float)) or isinstance(val, bool) or math.isnan(val) or math.isinf(val):
                return False, f"target_atr must be finite numeric, got {val}"
            if val <= 0.0 or val > 50.0:
                return False, f"target_atr {val} outside valid range (0.0, 50.0]"

        # risk_multiplier: finite float in (0.0, 5.0]
        if "risk_multiplier" in parameters:
            val = parameters["risk_multiplier"]
            if not isinstance(val, (int, float)) or isinstance(val, bool) or math.isnan(val) or math.isinf(val):
                return False, f"risk_multiplier must be finite numeric, got {val}"
            if val <= 0.0 or val > 5.0:
                return False, f"risk_multiplier {val} outside valid range (0.0, 5.0]"

        # fast_period & slow_period
        if "fast_period" in parameters:
            fp = parameters["fast_period"]
            if not isinstance(fp, int) or isinstance(fp, bool) or fp <= 0:
                return False, f"fast_period must be positive integer, got {fp}"
        if "slow_period" in parameters:
            sp = parameters["slow_period"]
            if not isinstance(sp, int) or isinstance(sp, bool) or sp <= 0:
                return False, f"slow_period must be positive integer, got {sp}"
        if "fast_period" in parameters and "slow_period" in parameters:
            if parameters["fast_period"] >= parameters["slow_period"]:
                return False, f"fast_period ({parameters['fast_period']}) must be < slow_period ({parameters['slow_period']})"

        # allocation_pct: finite float in (0.0, 1.0]
        if "allocation_pct" in parameters:
            val = parameters["allocation_pct"]
            if not isinstance(val, (int, float)) or isinstance(val, bool) or math.isnan(val) or math.isinf(val):
                return False, f"allocation_pct must be finite numeric, got {val}"
            if val <= 0.0 or val > 1.0:
                return False, f"allocation_pct {val} outside valid range (0.0, 1.0]"

        return True, None

    @classmethod
    def dispatch_symbol(
        cls,
        strategy_or_name: Union[str, BaseStrategy, None],
        symbol: str,
        market_data: Dict[str, Any],
        parameters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Dispatch point-in-time symbol evaluation through selected strategy implementation.
        
        Unknown strategy or WAIT yields WAIT with no generic scanner fallback.
        """
        params = parameters or {}
        price = float(market_data.get("price", 0.0))

        if isinstance(strategy_or_name, BaseStrategy):
            strategy = strategy_or_name
        else:
            strategy = cls.get_strategy(strategy_or_name, params)

        if strategy is None:
            return {
                "symbol": symbol,
                "signal": "WAIT",
                "price": price,
                "stop_loss": None,
                "target": None,
                "confidence": 0.0,
                "reason": f"Strategy '{strategy_or_name}' unknown or WAIT; yielding WAIT",
                "evidence": {},
                "strategy_id": str(strategy_or_name),
                "strategy_version": "1.0.0",
            }

        # Evaluate strategy directly
        if hasattr(strategy, "evaluate_data"):
            decision = strategy.evaluate_data(symbol, market_data, params)
        else:
            # Fallback to evaluate() if market_data has bars
            bars = market_data.get("bars", [])
            if bars:
                decision = strategy.evaluate(bars[-1], bars[:-1])
            else:
                decision = strategy.default_wait(symbol, market_data.get("bar_timestamp"), "No evaluation method")

        sig_val = decision.signal.value if hasattr(decision.signal, "value") else str(decision.signal)

        # Apply stop_loss_atr and target_atr to actual protection
        sl = decision.stop_loss
        tp = decision.target_price
        atr = float(market_data.get("atr", price * 0.01))

        if sig_val == "BUY":
            sl_atr_mult = float(params.get("stop_loss_atr", getattr(strategy, "stop_loss_atr", 1.5)))
            tp_atr_mult = float(params.get("target_atr", getattr(strategy, "target_atr", 3.0)))
            if sl is None:
                sl = round(price - (sl_atr_mult * atr), 2)
            if tp is None:
                tp = round(price + (tp_atr_mult * atr), 2)

        return {
            "symbol": symbol,
            "signal": sig_val,
            "price": price,
            "stop_loss": sl,
            "target": tp,
            "confidence": decision.confidence,
            "reason": decision.reason,
            "evidence": decision.evidence,
            "strategy_id": strategy.strategy_id,
            "strategy_version": strategy.version,
            "sizing_ratio": getattr(decision, "position_sizing_ratio", None),
        }


# Register Canonical Built-in Strategies
StrategyRegistry.register(
    SMACross,
    aliases=[
        "SMA_CROSS",
        "SMACROSS",
        "STRAT_SMA",
        "STRAT_EMA_MOMENTUM",
        "EMA_MOMENTUM",
        "EMA_CROSSOVER",
        "CANONICAL_SMA",
        "STRAT_ALPHA",
        "ALPHA",
    ],
)

StrategyRegistry.register(
    VWAPReversion,
    aliases=[
        "VWAP_REVERSION",
        "STRAT_VWAP_REVERSION",
        "VWAP_MEAN_REVERSION",
        "VWAPREVERSION",
    ],
)

StrategyRegistry.register(
    OpeningRangeBreakout,
    aliases=[
        "OPENINGRANGEBREAKOUT",
        "ORB_STRATEGY",
        "ORB",
        "STRAT_ORB",
    ],
)

StrategyRegistry.register(
    BuyAndHold,
    aliases=[
        "BUYANDHOLD",
        "BUY_AND_HOLD",
        "CANONICAL_BUYANDHOLD",
    ],
)

StrategyRegistry.register(
    DonchianBreakout,
    aliases=[
        "STRAT_DONCHIAN_BREAKOUT",
        "DONCHIAN_BREAKOUT",
        "DONCHIANBREAKOUT",
    ],
)

StrategyRegistry.register(
    BollingerReversion,
    aliases=[
        "STRAT_BOLLINGER_REVERSION",
        "BOLLINGER_REVERSION",
        "BOLLINGERREVERSION",
        "BOLLINGER_MEAN_REVERSION",
    ],
)
