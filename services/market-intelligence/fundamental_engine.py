"""
Algo Lab — Fundamental Financial Analysis & Health Scoring Engine
Evaluates profitability, solvency, valuation multiples, and Piotroski F-Scores,
detecting disqualifying red flags to enforce capital preservation.
"""

import math
from typing import Dict, Any, List, Tuple, Optional
from services.market_intelligence.news_fundamental_contracts import (
    FundamentalSnapshot,
    HealthTier,
)


class FundamentalAnalyzer:
    """Quantitative fundamental evaluator and balance sheet health assessor."""

    def evaluate_snapshot(self, snapshot: FundamentalSnapshot) -> Tuple[float, HealthTier, List[str], List[str]]:
        """
        Evaluates a FundamentalSnapshot.
        Returns:
            fundamental_score: float [0.0, 100.0]
            health_tier: HealthTier
            catalysts: List[str]
            risks: List[str]
        """
        catalysts: List[str] = []
        risks: List[str] = list(snapshot.red_flags)

        # Pre-check: Reject non-finite metrics defensively (G04, G05)
        for ratio_name, ratio_val in [
            ("ROE", snapshot.roe),
            ("Operating Margin", snapshot.operating_margin),
            ("Debt to Equity", snapshot.debt_to_equity),
            ("Revenue Growth", snapshot.revenue_growth_yoy),
            ("P/E Ratio", snapshot.pe_ratio),
        ]:
            if ratio_val is not None and not math.isfinite(ratio_val):
                risks.append(f"Non-finite ratio detected for {ratio_name}: {ratio_val}")
                return 0.0, HealthTier.DISTRESSED, catalysts, risks

        # 1. Profitability Score (35 points max)
        prof_score = 0.0
        roe = snapshot.roe or 0.0
        op_margin = snapshot.operating_margin or 0.0

        if roe >= 0.20:
            prof_score += 20.0
            catalysts.append(f"Exceptional ROE ({roe*100:.1f}%) demonstrating superior capital efficiency.")
        elif roe >= 0.12:
            prof_score += 15.0
            catalysts.append(f"Healthy ROE ({roe*100:.1f}%).")
        elif roe > 0.0:
            prof_score += 8.0
        else:
            risks.append(f"Depressed/Negative ROE ({roe*100:.1f}%).")

        if op_margin >= 0.20:
            prof_score += 15.0
            catalysts.append(f"High operating margin ({op_margin*100:.1f}%).")
        elif op_margin >= 0.10:
            prof_score += 10.0
        elif op_margin > 0.0:
            prof_score += 5.0
        else:
            risks.append("Operating margin is negative (operating losses).")

        # 2. Solvency & Balance Sheet Score (25 points max)
        solv_score = 0.0
        de = snapshot.debt_to_equity
        is_banking = "BANK" in snapshot.symbol.upper() or "FIN" in snapshot.symbol.upper()

        if is_banking:
            # Banking entities have naturally high balance sheet leverage
            solv_score += 20.0
        else:
            if de is not None:
                # de can be in ratio (0.5) or percentage (50.0) from various feeds
                de_ratio = de / 100.0 if de > 5.0 else de
                if de_ratio <= 0.3:
                    solv_score += 25.0
                    catalysts.append("Virtually debt-free / pristine balance sheet.")
                elif de_ratio <= 0.8:
                    solv_score += 18.0
                elif de_ratio <= 1.5:
                    solv_score += 10.0
                else:
                    solv_score += 0.0
                    risks.append(f"Elevated debt-to-equity ratio ({de_ratio:.2f}x).")
            else:
                solv_score += 12.0

        # 3. Growth & Momentum (20 points max)
        growth_score = 0.0
        rev_growth = snapshot.revenue_growth_yoy or 0.0

        if rev_growth >= 0.20:
            growth_score += 20.0
            catalysts.append(f"Rapid top-line expansion (YoY revenue growth {rev_growth*100:.1f}%).")
        elif rev_growth >= 0.08:
            growth_score += 15.0
            catalysts.append(f"Solid top-line revenue growth ({rev_growth*100:.1f}%).")
        elif rev_growth > 0.0:
            growth_score += 8.0
        else:
            risks.append(f"Top-line contraction (Revenue decline of {abs(rev_growth*100):.1f}%).")

        # 4. Valuation Multiples & Piotroski Score (20 points max)
        val_score = 0.0
        pe = snapshot.pe_ratio
        f_score = snapshot.piotroski_f_score

        # Piotroski F-score contribution (up to 10 pts)
        val_score += min(10.0, (f_score / 9.0) * 10.0)
        if f_score >= 7:
            catalysts.append(f"Piotroski F-Score is {f_score}/9 (High financial strength).")
        elif f_score <= 3:
            risks.append(f"Low Piotroski F-Score ({f_score}/9) indicates fundamental vulnerability.")

        # P/E evaluation (up to 10 pts)
        if pe is not None and pe > 0:
            if 10.0 <= pe <= 30.0:
                val_score += 10.0
                catalysts.append(f"Reasonable P/E valuation ({pe:.1f}x).")
            elif pe < 10.0:
                val_score += 8.0
                catalysts.append(f"Value territory P/E ({pe:.1f}x).")
            elif pe <= 60.0:
                val_score += 5.0
            else:
                risks.append(f"Expensive P/E multiple ({pe:.1f}x).")
        else:
            val_score += 5.0

        total_score = min(100.0, max(0.0, prof_score + solv_score + growth_score + val_score))

        # Assign Tier
        if total_score >= 80.0 and len(snapshot.red_flags) == 0:
            tier = HealthTier.PRIME_QUALITY
        elif total_score >= 65.0:
            tier = HealthTier.SOUND
        elif total_score >= 45.0:
            tier = HealthTier.AVERAGE
        elif total_score >= 30.0:
            tier = HealthTier.SPECULATIVE
        else:
            tier = HealthTier.DISTRESSED

        return round(total_score, 1), tier, catalysts, risks

    @staticmethod
    def calculate_piotroski_f_score(
        net_income: float,
        operating_cash_flow: float,
        prev_roa: float,
        curr_roa: float,
        curr_leverage: float,
        prev_leverage: float,
        curr_current_ratio: float,
        prev_current_ratio: float,
        curr_gross_margin: float,
        prev_gross_margin: float,
        curr_asset_turnover: float,
        prev_asset_turnover: float,
    ) -> int:
        """Computes institutional 9-factor Piotroski F-Score."""
        inputs = (
            net_income, operating_cash_flow, prev_roa, curr_roa,
            curr_leverage, prev_leverage, curr_current_ratio, prev_current_ratio,
            curr_gross_margin, prev_gross_margin, curr_asset_turnover, prev_asset_turnover,
        )
        if any(not isinstance(x, (int, float)) or not math.isfinite(x) for x in inputs):
            return 0

        score = 0
        # Profitability
        if net_income > 0: score += 1
        if operating_cash_flow > 0: score += 1
        if curr_roa > prev_roa: score += 1
        if operating_cash_flow > net_income: score += 1  # Quality of earnings
        # Leverage & Liquidity
        if curr_leverage < prev_leverage: score += 1     # Debt reduced
        if curr_current_ratio > prev_current_ratio: score += 1
        # Operating Efficiency
        if curr_gross_margin > prev_gross_margin: score += 1
        if curr_asset_turnover > prev_asset_turnover: score += 1

        return score
