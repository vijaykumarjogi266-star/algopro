"""
Algo Lab — Stage 8 Sector Rotation Engine
Calculates relative strength ranking across sector indices enforcing point-in-time constituent integrity (INV-27).
"""

from datetime import date, datetime
from typing import List, Dict, Any, Optional
from services.market_intelligence.contracts import (
    SectorMembershipRecord,
    SectorRank,
    MissingMembershipError,
)


class SectorRotationEngine:
    """Calculates sector relative strength and rotation rankings (INV-21, INV-27)."""

    def __init__(
        self,
        membership_history: Optional[List[SectorMembershipRecord]] = None,
    ):
        self._memberships: List[SectorMembershipRecord] = []
        if membership_history:
            for m in membership_history:
                self.add_membership_record(m)

    def add_membership_record(self, record: SectorMembershipRecord) -> None:
        """Adds versioned sector membership record."""
        self._memberships.append(record)
        # Sort by sector_id asc, effective_date asc
        self._memberships.sort(key=lambda m: (m.sector_id, m.effective_date))

    def get_point_in_time_constituents(
        self,
        sector_id: str,
        target_date: date,
    ) -> List[str]:
        """Resolves constituent list active on `target_date` without survivorship bias (INV-27)."""
        eligible = [
            m for m in self._memberships
            if m.sector_id == sector_id and m.effective_date <= target_date
        ]

        if not eligible:
            raise MissingMembershipError(
                f"Historical constituent membership for sector '{sector_id}' on date {target_date} "
                f"cannot be established."
            )

        # Active constituents as of latest effective date <= target_date
        return list(eligible[-1].active_constituents)

    def calculate_sector_rankings(
        self,
        target_date: date,
        sector_price_series: Dict[str, List[float]],
        benchmark_prices: List[float],
    ) -> List[SectorRank]:
        """Ranks sectors by relative strength performance against benchmark (INV-21)."""

        if not sector_price_series or not benchmark_prices or len(benchmark_prices) < 2:
            return []

        benchmark_return = (benchmark_prices[-1] - benchmark_prices[0]) / benchmark_prices[0]

        scores: List[Dict[str, Any]] = []

        # Sort sector IDs alphabetically to guarantee deterministic ordering
        for sector_id in sorted(sector_price_series.keys()):
            prices = sector_price_series[sector_id]
            if len(prices) < 2 or prices[0] <= 0:
                continue

            sector_return = (prices[-1] - prices[0]) / prices[0]
            # Relative strength score = sector_return - benchmark_return
            rs_score = round(sector_return - benchmark_return, 4)

            if rs_score > 0.05:
                cat = "LEADING"
            elif rs_score > 0.0:
                cat = "IMPROVING"
            elif rs_score > -0.05:
                cat = "WEAKENING"
            else:
                cat = "LAGGING"

            scores.append({
                "sector_id": sector_id,
                "rs_score": rs_score,
                "category": cat,
            })

        # Sort by rs_score desc, sector_id asc (canonical tie-breaker AT-112)
        scores.sort(key=lambda s: (-s["rs_score"], s["sector_id"]))

        rankings: List[SectorRank] = []
        for idx, item in enumerate(scores):
            rankings.append(
                SectorRank(
                    sector_id=item["sector_id"],
                    relative_strength_score=item["rs_score"],
                    rank=idx + 1,
                    momentum_category=item["category"],
                )
            )

        return rankings
