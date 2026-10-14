"""
Algo Lab — Quantamental Stock Selection & Actionable Decision Engine
Translates financial news sentiment, balance sheet fundamentals, and analyst
consensus into disciplined stock selection and real-time trade gating decisions.
"""

import json
import logging
import math
import os
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Any, List, Optional, Tuple

from services.market_intelligence.news_fundamental_contracts import (
    FundamentalSnapshot,
    NewsItem,
    QuantamentalDecisionManifest,
    CompositeBias,
    HealthTier,
    NewsUrgency,
)
from services.market_intelligence.news_fundamental_agent import NewsFundamentalAgent

logger = logging.getLogger("StockDecisionEngine")

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_DB_PATH = os.path.join(PROJECT_ROOT, "data", "market_intelligence.db")


class SelectionTier(str, Enum):
    TIER_1_HIGH_CONVICTION = "TIER_1_HIGH_CONVICTION"  # Pristine fundamentals + bullish catalysts (100% allocation scale)
    TIER_2_TACTICAL = "TIER_2_TACTICAL"                # Sound fundamentals + positive/neutral sentiment (60-80% scale)
    TIER_3_DEFENSIVE_NEUTRAL = "TIER_3_DEFENSIVE_NEUTRAL" # Average fundamentals, waiting for catalysts (30-50% scale)
    TIER_4_EXCLUDED = "TIER_4_EXCLUDED"                # Disqualified or bearish; strictly excluded from trading (0% scale)


class TradeAction(str, Enum):
    APPROVE_BUY = "APPROVE_BUY"         # High conviction quantamental backing + technical confirmation
    WAIT = "WAIT"                       # Inconclusive evidence or lack of catalysts (Principle 2)
    VETO = "VETO"                       # Hard veto: Technical signal blocked by fundamental/news red flag
    EMERGENCY_EXIT = "EMERGENCY_EXIT"   # Active holding compromised by breaking scandal or governance breach


@dataclass(frozen=True)
class StockSelectionCandidate:
    """Individual stock evaluation for portfolio selection."""
    symbol: str
    rank: int
    tier: SelectionTier
    quantamental_score: float           # Scaled [-100.0, +100.0]
    fundamental_score: float            # [0.0, 100.0]
    sentiment_score: float              # [-100.0, +100.0]
    piotroski_f_score: int              # [0, 9]
    roe_pct: float
    pe_ratio: Optional[float]
    debt_to_equity: Optional[float]
    analyst_upside_pct: Optional[float]
    analyst_consensus: str
    allocation_multiplier: float        # [0.0, 1.0]
    is_eligible_for_trading: bool
    veto_reasons: List[str]
    primary_catalysts: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "rank": self.rank,
            "tier": self.tier.value,
            "quantamental_score": self.quantamental_score,
            "fundamental_score": self.fundamental_score,
            "sentiment_score": self.sentiment_score,
            "piotroski_f_score": self.piotroski_f_score,
            "roe_pct": self.roe_pct,
            "pe_ratio": self.pe_ratio,
            "debt_to_equity": self.debt_to_equity,
            "analyst_upside_pct": self.analyst_upside_pct,
            "analyst_consensus": self.analyst_consensus,
            "allocation_multiplier": self.allocation_multiplier,
            "is_eligible_for_trading": self.is_eligible_for_trading,
            "veto_reasons": list(self.veto_reasons),
            "primary_catalysts": list(self.primary_catalysts),
        }


@dataclass(frozen=True)
class StockSelectionManifest:
    """Session stock selection manifest specifying vetted universe and exclusions."""
    generated_at: datetime
    selected_portfolio: List[str]       # Symbols approved for active trading
    excluded_portfolio: List[str]       # Symbols prohibited from trading
    candidates: List[StockSelectionCandidate]
    top_picks: List[str]                # Top 3 highest conviction picks
    narrative: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "selected_portfolio": list(self.selected_portfolio),
            "excluded_portfolio": list(self.excluded_portfolio),
            "top_picks": list(self.top_picks),
            "narrative": self.narrative,
            "candidates": [c.to_dict() for c in self.candidates],
        }


@dataclass(frozen=True)
class TradeDecisionResult:
    """Real-time actionable trading decision evaluating technical + quantamental confluence."""
    symbol: str
    action: TradeAction
    approved_quantity_scale: float      # Position sizing multiplier [0.0, 1.0]
    conviction_score: float             # [0.0, 100.0]
    reason: str
    red_flag_alert: bool = False

    def __post_init__(self):
        if not math.isfinite(self.approved_quantity_scale) or not (0.0 <= self.approved_quantity_scale <= 1.0):
            raise ValueError(f"approved_quantity_scale must be in range [0.0, 1.0], got {self.approved_quantity_scale}")
        if not math.isfinite(self.conviction_score) or not (0.0 <= self.conviction_score <= 100.0):
            raise ValueError(f"conviction_score must be in range [0.0, 100.0], got {self.conviction_score}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "action": self.action.value,
            "approved_quantity_scale": self.approved_quantity_scale,
            "conviction_score": self.conviction_score,
            "reason": self.reason,
            "red_flag_alert": self.red_flag_alert,
        }


class StockDecisionEngine:
    """
    Unified engine for:
    1. Multi-factor Stock Selection (screening, ranking, portfolio universe construction).
    2. Actionable Trading Decisions (trade approval, vetoing false breakouts, emergency exits).
    Persists all selection runs, candidate rankings, and real-time trade gating decisions into SQLite.
    """

    def __init__(
        self,
        agent: Optional[NewsFundamentalAgent] = None,
        min_selection_score: float = 30.0,
        max_portfolio_size: int = 4,
        db_path: Optional[str] = None,
    ):
        self.agent = agent or NewsFundamentalAgent()
        self.db_path = db_path or getattr(self.agent, "db_path", DEFAULT_DB_PATH)
        self.min_selection_score = min_selection_score
        self.max_portfolio_size = max_portfolio_size

        if self.db_path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self._init_decision_db()

    def _init_decision_db(self):
        """Initializes SQLite schema for stock selections, candidate rankings, and trade decisions."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS stock_selections (
                        selection_id TEXT PRIMARY KEY,
                        generated_at TEXT NOT NULL,
                        top_picks TEXT NOT NULL,
                        selected_portfolio TEXT NOT NULL,
                        excluded_portfolio TEXT NOT NULL,
                        candidate_count INTEGER NOT NULL,
                        narrative TEXT NOT NULL,
                        manifest_json TEXT NOT NULL
                    )
                """)
                cur.execute("CREATE INDEX IF NOT EXISTS idx_stock_selections_generated_at ON stock_selections(generated_at)")

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS stock_selection_candidates (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        selection_id TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        rank INTEGER NOT NULL,
                        tier TEXT NOT NULL,
                        quantamental_score REAL NOT NULL,
                        fundamental_score REAL NOT NULL,
                        sentiment_score REAL NOT NULL,
                        piotroski_f_score INTEGER NOT NULL,
                        roe_pct REAL NOT NULL,
                        pe_ratio REAL,
                        debt_to_equity REAL,
                        analyst_upside_pct REAL,
                        analyst_consensus TEXT NOT NULL,
                        allocation_multiplier REAL NOT NULL,
                        is_eligible_for_trading INTEGER NOT NULL,
                        veto_reasons TEXT NOT NULL,
                        primary_catalysts TEXT NOT NULL,
                        FOREIGN KEY(selection_id) REFERENCES stock_selections(selection_id)
                    )
                """)
                cur.execute("CREATE INDEX IF NOT EXISTS idx_selection_candidates_selection_id ON stock_selection_candidates(selection_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_selection_candidates_symbol ON stock_selection_candidates(symbol)")

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS trade_decisions (
                        decision_id TEXT PRIMARY KEY,
                        evaluated_at TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        decision_type TEXT NOT NULL,
                        proposed_signal TEXT NOT NULL,
                        action TEXT NOT NULL,
                        approved_quantity_scale REAL NOT NULL,
                        conviction_score REAL NOT NULL,
                        current_price REAL,
                        reason TEXT NOT NULL,
                        red_flag_alert INTEGER NOT NULL,
                        context_json TEXT
                    )
                """)
                cur.execute("CREATE INDEX IF NOT EXISTS idx_trade_decisions_symbol ON trade_decisions(symbol)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_trade_decisions_evaluated_at ON trade_decisions(evaluated_at)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_trade_decisions_action ON trade_decisions(action)")
                conn.commit()
        except Exception as e:
            logger.warning(f"Error initializing decision tables in {self.db_path}: {e}")

    def _persist_stock_selection(self, manifest: StockSelectionManifest) -> str:
        """Persists selection manifest and individual candidate records into SQLite."""
        selection_id = f"sel_{manifest.generated_at.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        manifest_dict = manifest.to_dict()
        manifest_dict["selection_id"] = selection_id

        try:
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO stock_selections (
                        selection_id, generated_at, top_picks, selected_portfolio,
                        excluded_portfolio, candidate_count, narrative, manifest_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    selection_id,
                    manifest.generated_at.isoformat(),
                    json.dumps(manifest.top_picks),
                    json.dumps(manifest.selected_portfolio),
                    json.dumps(manifest.excluded_portfolio),
                    len(manifest.candidates),
                    manifest.narrative,
                    json.dumps(manifest_dict),
                ))

                for c in manifest.candidates:
                    cur.execute("""
                        INSERT INTO stock_selection_candidates (
                            selection_id, symbol, rank, tier, quantamental_score,
                            fundamental_score, sentiment_score, piotroski_f_score,
                            roe_pct, pe_ratio, debt_to_equity, analyst_upside_pct,
                            analyst_consensus, allocation_multiplier, is_eligible_for_trading,
                            veto_reasons, primary_catalysts
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        selection_id,
                        c.symbol,
                        c.rank,
                        c.tier.value,
                        c.quantamental_score,
                        c.fundamental_score,
                        c.sentiment_score,
                        c.piotroski_f_score,
                        c.roe_pct,
                        c.pe_ratio,
                        c.debt_to_equity,
                        c.analyst_upside_pct,
                        c.analyst_consensus,
                        c.allocation_multiplier,
                        1 if c.is_eligible_for_trading else 0,
                        json.dumps(c.veto_reasons),
                        json.dumps(c.primary_catalysts),
                    ))
                conn.commit()
            return selection_id
        except Exception as e:
            logger.warning(f"Failed to persist stock selection {selection_id}: {e}")
            return selection_id

    def _persist_trade_decision(
        self,
        decision: TradeDecisionResult,
        decision_type: str,
        proposed_signal: str,
        current_price: Optional[float] = None,
        context: Optional[Dict[str, Any]] = None,
        evaluated_at: Optional[datetime] = None,
    ) -> str:
        """Persists trade gating decision to SQLite audit trail."""
        now = evaluated_at or datetime.now(timezone.utc)
        decision_id = f"dec_{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        try:
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO trade_decisions (
                        decision_id, evaluated_at, symbol, decision_type,
                        proposed_signal, action, approved_quantity_scale,
                        conviction_score, current_price, reason,
                        red_flag_alert, context_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    decision_id,
                    now.isoformat(),
                    decision.symbol,
                    decision_type,
                    proposed_signal,
                    decision.action.value,
                    decision.approved_quantity_scale,
                    decision.conviction_score,
                    current_price,
                    decision.reason,
                    1 if decision.red_flag_alert else 0,
                    json.dumps(context or {}),
                ))
                conn.commit()
            return decision_id
        except Exception as e:
            logger.warning(f"Failed to persist trade decision for {decision.symbol}: {e}")
            return decision_id

    # =========================================================================
    # 1. STOCK SELECTION & UNIVERSE STRATIFICATION
    # =========================================================================

    def run_stock_selection(
        self,
        candidate_symbols: Optional[List[str]] = None,
        as_of_time: Optional[datetime] = None,
        persist: bool = True,
    ) -> StockSelectionManifest:
        """
        Screens and ranks candidate symbols across fundamentals, news sentiment,
        and analyst consensus to construct an approved trading universe.
        """
        now = as_of_time or datetime.now(timezone.utc)
        from services.market_intelligence.news_fundamental_agent import DEFAULT_UNIVERSE
        targets = candidate_symbols or DEFAULT_UNIVERSE

        scored_candidates: List[StockSelectionCandidate] = []

        for sym in targets:
            manifest = self.agent.evaluate_symbol(sym, as_of_time=now)
            snap = self.agent.fundamental_collector.fetch_fundamental_snapshot(sym, as_of_date=now.date())
            consensus = self.agent.fundamental_collector.fetch_analyst_consensus(sym)

            veto_reasons = []
            if not manifest.allow_trading:
                veto_reasons.extend(snap.red_flags)
                if manifest.bias == CompositeBias.DISQUALIFIED and not veto_reasons:
                    veto_reasons.append("Extreme adverse news sentiment / governance alert.")
                elif manifest.bias in [CompositeBias.BEARISH, CompositeBias.STRONG_BEARISH]:
                    veto_reasons.append(f"Bearish quantamental score ({manifest.composite_score:+.1f}).")

            # Multi-factor score incorporating analyst consensus upside
            raw_score = manifest.composite_score
            if consensus.upside_potential_pct is not None:
                # Add up to +10 pts for strong analyst upside (>15%), or -5 pts for negative upside
                if consensus.upside_potential_pct > 15.0:
                    raw_score += min(10.0, consensus.upside_potential_pct * 0.3)
                elif consensus.upside_potential_pct < 0.0:
                    raw_score -= 5.0

            # Tier classification
            if not manifest.allow_trading or len(veto_reasons) > 0:
                tier = SelectionTier.TIER_4_EXCLUDED
                alloc_scale = 0.0
                eligible = False
            elif raw_score >= 50.0 and snap.health_tier in [HealthTier.PRIME_QUALITY, HealthTier.SOUND]:
                tier = SelectionTier.TIER_1_HIGH_CONVICTION
                alloc_scale = 1.0
                eligible = True
            elif raw_score >= 35.0:
                tier = SelectionTier.TIER_2_TACTICAL
                alloc_scale = 0.75
                eligible = True
            elif raw_score >= self.min_selection_score:
                tier = SelectionTier.TIER_3_DEFENSIVE_NEUTRAL
                alloc_scale = 0.40
                eligible = True
            else:
                tier = SelectionTier.TIER_4_EXCLUDED
                alloc_scale = 0.0
                eligible = False
                veto_reasons.append(f"Insufficient quantamental score ({raw_score:+.1f} < {self.min_selection_score}).")

            roe_val = (snap.roe * 100.0) if snap.roe is not None else 0.0

            candidate = StockSelectionCandidate(
                symbol=sym,
                rank=0,  # Will be assigned after sorting
                tier=tier,
                quantamental_score=round(raw_score, 1),
                fundamental_score=manifest.fundamental_score,
                sentiment_score=manifest.sentiment_score,
                piotroski_f_score=snap.piotroski_f_score,
                roe_pct=round(roe_val, 1),
                pe_ratio=snap.pe_ratio,
                debt_to_equity=snap.debt_to_equity,
                analyst_upside_pct=consensus.upside_potential_pct,
                analyst_consensus=consensus.recommendation_key.upper(),
                allocation_multiplier=alloc_scale,
                is_eligible_for_trading=eligible,
                veto_reasons=veto_reasons,
                primary_catalysts=manifest.catalysts[:3],
            )
            scored_candidates.append(candidate)

        # Sort: Eligible first by quantamental score descending, then ineligible
        scored_candidates.sort(key=lambda c: (c.is_eligible_for_trading, c.quantamental_score), reverse=True)

        # Re-assign ranks
        ranked_candidates = [
            StockSelectionCandidate(
                symbol=c.symbol,
                rank=idx + 1,
                tier=c.tier,
                quantamental_score=c.quantamental_score,
                fundamental_score=c.fundamental_score,
                sentiment_score=c.sentiment_score,
                piotroski_f_score=c.piotroski_f_score,
                roe_pct=c.roe_pct,
                pe_ratio=c.pe_ratio,
                debt_to_equity=c.debt_to_equity,
                analyst_upside_pct=c.analyst_upside_pct,
                analyst_consensus=c.analyst_consensus,
                allocation_multiplier=c.allocation_multiplier,
                is_eligible_for_trading=c.is_eligible_for_trading,
                veto_reasons=c.veto_reasons,
                primary_catalysts=c.primary_catalysts,
            )
            for idx, c in enumerate(scored_candidates)
        ]

        selected = [c.symbol for c in ranked_candidates if c.is_eligible_for_trading][:self.max_portfolio_size]
        excluded = [c.symbol for c in ranked_candidates if not c.is_eligible_for_trading]
        top_picks = [c.symbol for c in ranked_candidates if c.tier == SelectionTier.TIER_1_HIGH_CONVICTION][:3]
        if not top_picks and selected:
            top_picks = selected[:2]

        narrative = (
            f"Screened {len(ranked_candidates)} symbols. Approved {len(selected)} symbols for active session: "
            f"{', '.join(selected)}. Excluded {len(excluded)} symbols due to red flags or low conviction."
        )

        manifest = StockSelectionManifest(
            generated_at=now,
            selected_portfolio=selected,
            excluded_portfolio=excluded,
            candidates=ranked_candidates,
            top_picks=top_picks,
            narrative=narrative,
        )

        if persist:
            self._persist_stock_selection(manifest)

        return manifest

    # =========================================================================
    # 2. ACTIONABLE DECISION MAKING & TRADE GATING
    # =========================================================================

    def evaluate_entry_decision(
        self,
        symbol: str,
        technical_signal: str,
        current_price: float,
        technical_context: Optional[Dict[str, Any]] = None,
        persist: bool = True,
    ) -> TradeDecisionResult:
        """
        Evaluates a proposed trade entry combining technical signal with quantamental health.
        Prevents buying false breakouts in fundamentally deteriorating or scandal-hit stocks.
        Automatically logs trade gating decision to SQLite audit trail.
        """
        now = datetime.now(timezone.utc)

        # If technical signal is not BUY, decision is WAIT
        if technical_signal != "BUY":
            res = TradeDecisionResult(
                symbol=symbol,
                action=TradeAction.WAIT,
                approved_quantity_scale=0.0,
                conviction_score=0.0,
                reason="No technical BUY trigger generated by alpha strategy.",
            )
            if persist:
                self._persist_trade_decision(
                    res, decision_type="ENTRY_EVALUATION", proposed_signal=technical_signal,
                    current_price=current_price, context=technical_context, evaluated_at=now
                )
            return res

        manifest = self.agent.evaluate_symbol(symbol)
        snap = self.agent.fundamental_collector.fetch_fundamental_snapshot(symbol)

        # 1. Hard Disqualification Veto
        if not manifest.allow_trading or snap.is_disqualified:
            veto_msg = f"TRADE VETOED: Disqualified by fundamental red flags ({', '.join(snap.red_flags or ['Severe governance alert'])})"
            res = TradeDecisionResult(
                symbol=symbol,
                action=TradeAction.VETO,
                approved_quantity_scale=0.0,
                conviction_score=0.0,
                reason=veto_msg,
                red_flag_alert=True,
            )
            if persist:
                self._persist_trade_decision(
                    res, decision_type="ENTRY_EVALUATION", proposed_signal=technical_signal,
                    current_price=current_price, context=technical_context, evaluated_at=now
                )
            return res

        # 2. Sentiment Scandal Veto (e.g. Breaking news alert with severe negativity)
        if manifest.sentiment_score <= -40.0:
            veto_msg = f"TRADE VETOED: Negative news sentiment spike ({manifest.sentiment_score:+.1f}). Risk of headline crash."
            res = TradeDecisionResult(
                symbol=symbol,
                action=TradeAction.VETO,
                approved_quantity_scale=0.0,
                conviction_score=15.0,
                reason=veto_msg,
                red_flag_alert=True,
            )
            if persist:
                self._persist_trade_decision(
                    res, decision_type="ENTRY_EVALUATION", proposed_signal=technical_signal,
                    current_price=current_price, context=technical_context, evaluated_at=now
                )
            return res

        # 3. High Conviction Approval (Tier 1)
        if manifest.composite_score >= 50.0 and snap.health_tier in [HealthTier.PRIME_QUALITY, HealthTier.SOUND]:
            reason = (
                f"TRADE APPROVED (High Conviction): Pristine balance sheet (Piotroski {snap.piotroski_f_score}/9, "
                f"ROE {snap.roe*100:.1f}%) and supportive news sentiment ({manifest.sentiment_score:+.1f})."
            )
            res = TradeDecisionResult(
                symbol=symbol,
                action=TradeAction.APPROVE_BUY,
                approved_quantity_scale=1.0,
                conviction_score=min(95.0, manifest.composite_score + 25.0),
                reason=reason,
            )
            if persist:
                self._persist_trade_decision(
                    res, decision_type="ENTRY_EVALUATION", proposed_signal=technical_signal,
                    current_price=current_price, context=technical_context, evaluated_at=now
                )
            return res

        # 4. Moderate Tactical Approval (Tier 2)
        if manifest.composite_score >= self.min_selection_score:
            reason = (
                f"TRADE APPROVED (Tactical): Sound fundamentals (Score {manifest.fundamental_score:.1f}/100) "
                f"with 75% risk scaling."
            )
            res = TradeDecisionResult(
                symbol=symbol,
                action=TradeAction.APPROVE_BUY,
                approved_quantity_scale=0.75,
                conviction_score=manifest.composite_score,
                reason=reason,
            )
            if persist:
                self._persist_trade_decision(
                    res, decision_type="ENTRY_EVALUATION", proposed_signal=technical_signal,
                    current_price=current_price, context=technical_context, evaluated_at=now
                )
            return res

        # 5. Inconclusive Evidence -> WAIT
        res = TradeDecisionResult(
            symbol=symbol,
            action=TradeAction.WAIT,
            approved_quantity_scale=0.0,
            conviction_score=manifest.composite_score,
            reason=f"DECISION WAIT: Composite score ({manifest.composite_score:+.1f}) below conviction threshold ({self.min_selection_score}).",
        )
        if persist:
            self._persist_trade_decision(
                res, decision_type="ENTRY_EVALUATION", proposed_signal=technical_signal,
                current_price=current_price, context=technical_context, evaluated_at=now
            )
        return res

    def evaluate_holding_risk(
        self,
        symbol: str,
        current_entry_price: float,
        current_market_price: float,
        persist: bool = True,
    ) -> TradeDecisionResult:
        """
        Monitors an existing open position for emergency catalysts (SEBI raid, default, accounting fraud).
        Allows cutting losing or vulnerable positions ahead of catastrophic gap downs.
        Persists decision to SQLite database.
        """
        now = datetime.now(timezone.utc)
        news_items = self.agent.news_collector.fetch_symbol_news(symbol, limit=5)
        # 1. Check breaking news alerts and regulatory scandals
        for item in news_items:
            t_low = item.title.lower()
            is_scandal = any(
                kw in t_low for kw in [
                    "sebi probe", "cbi raid", "ed raid", "accounting fraud",
                    "auditor resign", "insolvency", "bankruptcy", "default",
                    "promoter pledge"
                ]
            )
            if (item.urgency == NewsUrgency.HIGH and item.sentiment_score <= -0.75) or is_scandal:
                res = TradeDecisionResult(
                    symbol=symbol,
                    action=TradeAction.EMERGENCY_EXIT,
                    approved_quantity_scale=0.0,
                    conviction_score=0.0,
                    reason=f"EMERGENCY EXIT TRIGGERED: Breaking High Urgency Alert: {item.title} ({item.source})",
                    red_flag_alert=True,
                )
                if persist:
                    self._persist_trade_decision(
                        res, decision_type="HOLDING_RISK", proposed_signal="HOLD",
                        current_price=current_market_price,
                        context={"entry_price": current_entry_price, "market_price": current_market_price, "headline": item.title},
                        evaluated_at=now
                    )
                return res

        # 2. Check fundamental deterioration / disqualification
        snap = self.agent.fundamental_collector.fetch_fundamental_snapshot(symbol)
        if snap.is_disqualified:
            res = TradeDecisionResult(
                symbol=symbol,
                action=TradeAction.EMERGENCY_EXIT,
                approved_quantity_scale=0.0,
                conviction_score=0.0,
                reason=f"EMERGENCY EXIT TRIGGERED: Disqualified by fundamental red flags ({', '.join(snap.red_flags)})",
                red_flag_alert=True,
            )
            if persist:
                self._persist_trade_decision(
                    res, decision_type="HOLDING_RISK", proposed_signal="HOLD",
                    current_price=current_market_price,
                    context={"entry_price": current_entry_price, "market_price": current_market_price, "red_flags": snap.red_flags},
                    evaluated_at=now
                )
            return res

        res = TradeDecisionResult(
            symbol=symbol,
            action=TradeAction.WAIT,
            approved_quantity_scale=1.0,
            conviction_score=80.0,
            reason="Holding is fundamentally sound; no adverse news alerts detected.",
        )
        if persist:
            self._persist_trade_decision(
                res, decision_type="HOLDING_RISK", proposed_signal="HOLD",
                current_price=current_market_price,
                context={"entry_price": current_entry_price, "market_price": current_market_price},
                evaluated_at=now
            )
        return res

    # =========================================================================
    # 3. DATABASE QUERY & RETRIEVAL METHODS
    # =========================================================================

    def get_latest_stock_selection(self) -> Optional[Dict[str, Any]]:
        """Retrieves the most recent stock selection manifest and candidate rankings from SQLite."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute("SELECT * FROM stock_selections ORDER BY generated_at DESC LIMIT 1")
                row = cur.fetchone()
                if not row:
                    return None

                sel_id = row["selection_id"]
                cur.execute(
                    "SELECT * FROM stock_selection_candidates WHERE selection_id = ? ORDER BY rank ASC",
                    (sel_id,)
                )
                c_rows = cur.fetchall()

                candidates = []
                for cr in c_rows:
                    candidates.append({
                        "symbol": cr["symbol"],
                        "rank": cr["rank"],
                        "tier": cr["tier"],
                        "quantamental_score": cr["quantamental_score"],
                        "fundamental_score": cr["fundamental_score"],
                        "sentiment_score": cr["sentiment_score"],
                        "piotroski_f_score": cr["piotroski_f_score"],
                        "roe_pct": cr["roe_pct"],
                        "pe_ratio": cr["pe_ratio"],
                        "debt_to_equity": cr["debt_to_equity"],
                        "analyst_upside_pct": cr["analyst_upside_pct"],
                        "analyst_consensus": cr["analyst_consensus"],
                        "allocation_multiplier": cr["allocation_multiplier"],
                        "is_eligible_for_trading": bool(cr["is_eligible_for_trading"]),
                        "veto_reasons": json.loads(cr["veto_reasons"]),
                        "primary_catalysts": json.loads(cr["primary_catalysts"]),
                    })

                return {
                    "selection_id": row["selection_id"],
                    "generated_at": row["generated_at"],
                    "top_picks": json.loads(row["top_picks"]),
                    "selected_portfolio": json.loads(row["selected_portfolio"]),
                    "excluded_portfolio": json.loads(row["excluded_portfolio"]),
                    "candidate_count": row["candidate_count"],
                    "narrative": row["narrative"],
                    "candidates": candidates,
                }
        except Exception as e:
            logger.warning(f"Failed to fetch latest stock selection from {self.db_path}: {e}")
            return None

    def get_recent_stock_selections(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Retrieves historical stock selection run summaries from SQLite."""
        selections = []
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute(
                    "SELECT selection_id, generated_at, top_picks, selected_portfolio, excluded_portfolio, candidate_count, narrative "
                    "FROM stock_selections ORDER BY generated_at DESC LIMIT ?",
                    (limit,)
                )
                for row in cur.fetchall():
                    selections.append({
                        "selection_id": row["selection_id"],
                        "generated_at": row["generated_at"],
                        "top_picks": json.loads(row["top_picks"]),
                        "selected_portfolio": json.loads(row["selected_portfolio"]),
                        "excluded_portfolio": json.loads(row["excluded_portfolio"]),
                        "candidate_count": row["candidate_count"],
                        "narrative": row["narrative"],
                    })
        except Exception as e:
            logger.warning(f"Failed to fetch recent stock selections: {e}")
        return selections

    def get_recent_trade_decisions(
        self,
        limit: int = 15,
        symbol: Optional[str] = None,
        action: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieves real-time trade gating decision logs from SQLite audit trail."""
        decisions = []
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                query = "SELECT * FROM trade_decisions"
                params = []
                clauses = []
                if symbol:
                    clauses.append("symbol = ?")
                    params.append(symbol)
                if action:
                    clauses.append("action = ?")
                    params.append(action)
                if clauses:
                    query += " WHERE " + " AND ".join(clauses)
                query += " ORDER BY evaluated_at DESC LIMIT ?"
                params.append(limit)

                cur.execute(query, tuple(params))
                for row in cur.fetchall():
                    decisions.append({
                        "decision_id": row["decision_id"],
                        "evaluated_at": row["evaluated_at"],
                        "symbol": row["symbol"],
                        "decision_type": row["decision_type"],
                        "proposed_signal": row["proposed_signal"],
                        "action": row["action"],
                        "approved_quantity_scale": row["approved_quantity_scale"],
                        "conviction_score": row["conviction_score"],
                        "current_price": row["current_price"],
                        "reason": row["reason"],
                        "red_flag_alert": bool(row["red_flag_alert"]),
                        "context": json.loads(row["context_json"]) if row["context_json"] else {},
                    })
        except Exception as e:
            logger.warning(f"Failed to fetch recent trade decisions: {e}")
        return decisions
