"""
Algo Lab — Stage 8 Market Breadth Engine
Computes Advance-Decline ratios, McClellan indicators, and universe SMA breadth metrics
strictly using historical OHLCV data up to simulation timestamp t.
"""

from datetime import datetime
from typing import List, Dict, Any, Optional
from services.market_intelligence.contracts import BreadthRecord


class MarketBreadthCalculator:
    """Calculates point-in-time universe breadth metrics deterministically (INV-19)."""

    @classmethod
    def calculate_breadth(
        cls,
        timestamp: datetime,
        universe_id: str,
        stock_price_histories: Dict[str, List[float]],
    ) -> BreadthRecord:
        """Calculates market breadth for `universe_id` at `timestamp`.
        
        `stock_price_histories`: Dict mapping symbol -> list of close prices up to `timestamp`.
        """
        if not stock_price_histories:
            return BreadthRecord(
                timestamp=timestamp,
                universe_id=universe_id,
                advances_count=0,
                declines_count=0,
                unchanged_count=0,
                ad_ratio=0.0,
                pct_above_20_sma=0.0,
                pct_above_50_sma=0.0,
                pct_above_200_sma=0.0,
            )

        advances = 0
        declines = 0
        unchanged = 0

        above_20_count = 0
        above_50_count = 0
        above_200_count = 0
        valid_sma_20_total = 0
        valid_sma_50_total = 0
        valid_sma_200_total = 0

        # Sort symbols alphabetically to guarantee deterministic execution
        sorted_symbols = sorted(stock_price_histories.keys())

        for sym in sorted_symbols:
            closes = stock_price_histories[sym]
            if not closes:
                continue

            curr_close = closes[-1]

            # Advance / Decline logic (compare against previous bar close if available)
            if len(closes) >= 2:
                prev_close = closes[-2]
                if curr_close > prev_close:
                    advances += 1
                elif curr_close < prev_close:
                    declines += 1
                else:
                    unchanged += 1
            else:
                unchanged += 1

            # 20 SMA check
            if len(closes) >= 20:
                sma_20 = sum(closes[-20:]) / 20.0
                valid_sma_20_total += 1
                if curr_close >= sma_20:
                    above_20_count += 1

            # 50 SMA check
            if len(closes) >= 50:
                sma_50 = sum(closes[-50:]) / 50.0
                valid_sma_50_total += 1
                if curr_close >= sma_50:
                    above_50_count += 1

            # 200 SMA check
            if len(closes) >= 200:
                sma_200 = sum(closes[-200:]) / 200.0
                valid_sma_200_total += 1
                if curr_close >= sma_200:
                    above_200_count += 1

        ad_ratio = round(advances / declines, 4) if declines > 0 else (float(advances) if advances > 0 else 0.0)
        pct_20 = round(above_20_count / valid_sma_20_total, 4) if valid_sma_20_total > 0 else 0.0
        pct_50 = round(above_50_count / valid_sma_50_total, 4) if valid_sma_50_total > 0 else 0.0
        pct_200 = round(above_200_count / valid_sma_200_total, 4) if valid_sma_200_total > 0 else 0.0

        return BreadthRecord(
            timestamp=timestamp,
            universe_id=universe_id,
            advances_count=advances,
            declines_count=declines,
            unchanged_count=unchanged,
            ad_ratio=ad_ratio,
            pct_above_20_sma=pct_20,
            pct_above_50_sma=pct_50,
            pct_above_200_sma=pct_200,
        )
