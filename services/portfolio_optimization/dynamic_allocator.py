"""
Algo Lab — Stage 9 Dynamic Allocation Engine
"""

from typing import Dict, List, Tuple
from datetime import datetime
import math

from services.portfolio_optimization.contracts import (
    WeightingScheme,
    StrategyAllocationConfig,
    StrategyAllocationRecord,
    AllocationError,
    MissingMetricError,
)


class DynamicAllocationEngine:
    """Calculates dynamic strategy allocation weights based on walk-forward degradation and macro intelligence."""

    @staticmethod
    def calculate_allocations(
        scheme: WeightingScheme,
        configs: List[StrategyAllocationConfig],
        strategy_degradation_scores: Dict[str, float],
        macro_regime_score: float = 0.0,
        cash_floor_pct: float = 0.05,
        stale_macro_warning: bool = False,
        timestamp: datetime = None,
    ) -> Tuple[Dict[str, float], float, List[StrategyAllocationRecord]]:
        """Calculates dynamic weights for a list of strategy allocation configs.

        Returns:
            Tuple[assigned_weights, cash_weight, allocation_records]
        """
        if timestamp is None:
            timestamp = datetime.now()

        # 1. Non-finite check for macro_regime_score & cash_floor (INV-37)
        for name, val in [("macro_regime_score", macro_regime_score), ("cash_floor_pct", cash_floor_pct)]:
            if math.isnan(val) or math.isinf(val):
                raise AllocationError(f"Non-finite value detected: {name}={val}")

        # 2. Check total base weight overflow (AT-144)
        total_base = sum(c.base_weight for c in configs)
        if total_base > 1.000001:
            raise AllocationError(f"Total base weights sum to {total_base:.4f} > 1.0")

        # 3. Check for missing metrics (AT-145)
        for cfg in configs:
            if cfg.strategy_id not in strategy_degradation_scores:
                raise MissingMetricError(f"Missing OOS degradation metric for strategy '{cfg.strategy_id}'")
            deg = strategy_degradation_scores[cfg.strategy_id]
            if math.isnan(deg) or math.isinf(deg):
                raise AllocationError(f"Non-finite degradation score for {cfg.strategy_id}: {deg}")

        # Sort configs deterministically by strategy_id string alphabetical order (INV-31 / AT-152)
        sorted_configs = sorted(configs, key=lambda c: c.strategy_id)

        records: List[StrategyAllocationRecord] = []
        raw_weights: Dict[str, float] = {}

        # Determine macro regime multiplier
        macro_factor = 1.0
        if macro_regime_score < 0.0:
            # Scale down equity exposure when macro is bearish (e.g. -0.80 -> 0.50x factor)
            macro_factor = max(0.20, 1.0 + (macro_regime_score * 0.50))
        if stale_macro_warning:
            # Cap equity weight at 50% if macro data is stale (AT-146)
            macro_factor = min(macro_factor, 0.50)

        for cfg in sorted_configs:
            deg_score = strategy_degradation_scores[cfg.strategy_id]
            reason = "Normal allocation"
            is_throttled = False

            # AT-137: Throttling check for degradation exceeding threshold
            if deg_score > cfg.max_degradation_threshold:
                w = 0.0
                is_throttled = True
                reason = f"Throttled: degradation {deg_score:.2f} > threshold {cfg.max_degradation_threshold:.2f}"
            else:
                w = cfg.base_weight
                # Apply scheme scaling
                if scheme == WeightingScheme.DEGRADATION_ADJUSTED:
                    # Scale down linearly with degradation score
                    w = w * max(0.0, (1.0 - deg_score))
                elif scheme == WeightingScheme.MACRO_ALIGNED:
                    w = w * macro_factor

                # Apply macro factor if macro is bearish or stale
                if macro_regime_score < 0.0 or stale_macro_warning:
                    w = w * macro_factor
                    reason = f"Scaled by macro factor {macro_factor:.2f}"

                # Cap at max_weight_cap
                if w > cfg.max_weight_cap:
                    w = cfg.max_weight_cap
                    reason = f"Capped at max weight cap {cfg.max_weight_cap}"

            w = round(max(0.0, w), 6)
            raw_weights[cfg.strategy_id] = w

            records.append(
                StrategyAllocationRecord(
                    timestamp=timestamp,
                    strategy_id=cfg.strategy_id,
                    assigned_weight=w,
                    allocated_capital=0.0,  # Will be populated when total capital is known
                    degradation_score=deg_score,
                    macro_regime_multiplier=macro_factor,
                    is_throttled=is_throttled,
                    reason=reason,
                )
            )

        # Scale weights if sum exceeds available equity pool (1.0 - cash_floor_pct)
        max_equity_pool = round(1.0 - cash_floor_pct, 6)
        total_raw = sum(raw_weights.values())

        final_weights: Dict[str, float] = {}
        if total_raw > max_equity_pool:
            scale = max_equity_pool / total_raw
            for s_id in sorted_configs:
                final_weights[s_id.strategy_id] = round(raw_weights[s_id.strategy_id] * scale, 6)
        else:
            final_weights = raw_weights

        total_allocated = sum(final_weights.values())
        cash_weight = round(1.0 - total_allocated, 6)

        # Ensure non-negative cash weight
        if cash_weight < 0.0:
            cash_weight = 0.0
            # Normalize equity weights to sum to 1.0
            tot = sum(final_weights.values())
            for s_id in final_weights:
                final_weights[s_id] = round(final_weights[s_id] / tot, 6)

        return final_weights, cash_weight, records
