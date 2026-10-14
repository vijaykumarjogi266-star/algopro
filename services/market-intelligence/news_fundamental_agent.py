"""
Algo Lab — News & Market Fundamentals Autonomous Agent
Integrates news collection, financial NLP sentiment analysis, and fundamental equity
scoring to produce explainable quantamental intelligence and risk gating manifests.
"""

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone, date
from typing import Dict, Any, List, Optional, Tuple

from services.market_intelligence.news_fundamental_contracts import (
    NewsItem,
    FundamentalSnapshot,
    QuantamentalDecisionManifest,
    CompositeBias,
    HealthTier,
    NewsUrgency,
)
from services.market_intelligence.sentiment_engine import FinancialSentimentAnalyzer
from services.market_intelligence.fundamental_engine import FundamentalAnalyzer
from services.market_intelligence.collector_service import (
    NewsCollector,
    FundamentalCollector,
    BENCHMARK_FUNDAMENTAL_FIXTURES,
)

logger = logging.getLogger("NewsFundamentalAgent")

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_DB_PATH = os.path.join(PROJECT_ROOT, "data", "market_intelligence.db")
DEFAULT_INTELLIGENCE_DIR = os.path.join(PROJECT_ROOT, "data", "intelligence")

DEFAULT_UNIVERSE = list(BENCHMARK_FUNDAMENTAL_FIXTURES.keys())


class NewsFundamentalAgent:
    """
    Autonomous Quantamental Agent for Algo Lab.
    Collects, processes, and synthesizes news sentiment and financial fundamentals
    to provide independent trade gating and capital allocation intelligence.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        intelligence_dir: Optional[str] = None,
        force_offline: bool = False,
        allow_synthetic_fallback: bool = True,
    ):
        self.db_path = db_path or DEFAULT_DB_PATH
        self.intelligence_dir = intelligence_dir or DEFAULT_INTELLIGENCE_DIR
        self.force_offline = force_offline
        self.allow_synthetic_fallback = allow_synthetic_fallback

        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        os.makedirs(self.intelligence_dir, exist_ok=True)

        self.sentiment_analyzer = FinancialSentimentAnalyzer()
        self.fundamental_analyzer = FundamentalAnalyzer()
        self.news_collector = NewsCollector(
            sentiment_analyzer=self.sentiment_analyzer,
            force_offline=self.force_offline,
            allow_synthetic_fallback=self.allow_synthetic_fallback,
            cache_dir=os.path.join(self.intelligence_dir, "cache"),
        )
        self.fundamental_collector = FundamentalCollector(
            force_offline=self.force_offline,
            allow_synthetic_fallback=self.allow_synthetic_fallback,
        )

        self._init_db()

    def _init_db(self):
        """Initializes SQLite schema for persistence and point-in-time audit trails."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS news_articles (
                    article_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    title TEXT NOT NULL,
                    source TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    sentiment_score REAL NOT NULL,
                    sentiment_label TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    urgency TEXT NOT NULL,
                    category TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS fundamental_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    as_of_date TEXT NOT NULL,
                    pe_ratio REAL,
                    pb_ratio REAL,
                    debt_to_equity REAL,
                    roe REAL,
                    operating_margin REAL,
                    revenue_growth_yoy REAL,
                    piotroski_f_score INTEGER NOT NULL,
                    health_tier TEXT NOT NULL,
                    red_flags TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS quantamental_manifests (
                    symbol TEXT NOT NULL,
                    evaluated_at TEXT NOT NULL,
                    composite_score REAL NOT NULL,
                    bias TEXT NOT NULL,
                    allow_trading INTEGER NOT NULL,
                    allocation_multiplier REAL NOT NULL,
                    fundamental_score REAL NOT NULL,
                    sentiment_score REAL NOT NULL,
                    recent_news_count INTEGER NOT NULL,
                    manifest_json TEXT NOT NULL,
                    PRIMARY KEY (symbol, evaluated_at)
                )
            """)
            conn.commit()

    def evaluate_symbol(
        self,
        symbol: str,
        as_of_time: Optional[datetime] = None,
    ) -> QuantamentalDecisionManifest:
        """
        Executes full quantamental evaluation for a single equity symbol.
        Enforces Point-In-Time provenance and produces an explainable decision manifest.
        """
        eval_time = as_of_time or datetime.now(timezone.utc)
        eval_date = eval_time.date()

        # 1. Collect News and Compute Decayed Sentiment
        news_items = self.news_collector.fetch_symbol_news(symbol, limit=10, as_of_time=eval_time)
        sentiment_score = self.sentiment_analyzer.calculate_decayed_sentiment(
            news_items, as_of_time=eval_time, half_life_hours=24.0
        )

        # 2. Collect Fundamentals and Evaluate Health
        snapshot = self.fundamental_collector.fetch_fundamental_snapshot(symbol, as_of_date=eval_date)
        fund_score, health_tier, catalysts, risks = self.fundamental_analyzer.evaluate_snapshot(snapshot)

        # Extract breaking news catalysts and risks
        for item in news_items:
            if item.urgency == NewsUrgency.HIGH and item.sentiment_score < -0.6:
                risks.append(f"Breaking High Urgency Alert: {item.title} ({item.source})")
            elif item.sentiment_score >= 0.7:
                catalysts.append(f"Positive News Catalyst: {item.title}")

        # 3. Synthesize Composite Score & Decision Bias
        # Scale: Fund score [0, 100] converted to [-100, +100] centered at 50
        fund_centered = (fund_score - 50.0) * 2.0
        composite_score = round((0.60 * fund_centered) + (0.40 * sentiment_score), 2)

        # Hard Risk Disqualification Checks (Capital Preservation First)
        is_disqualified = False
        disqualify_reason = ""

        if snapshot.is_disqualified:
            is_disqualified = True
            disqualify_reason = f"Fundamental Red Flag: {', '.join(snapshot.red_flags)}"
        elif any(item.urgency == NewsUrgency.HIGH and item.sentiment_score <= -0.85 for item in news_items):
            is_disqualified = True
            disqualify_reason = "Severe Regulatory/Governance Alert detected in real-time news."

        if is_disqualified:
            bias = CompositeBias.DISQUALIFIED
            allow_trading = False
            allocation_multiplier = 0.0
        elif composite_score >= 45.0:
            bias = CompositeBias.STRONG_BULLISH if composite_score >= 65.0 else CompositeBias.BULLISH
            allow_trading = True
            allocation_multiplier = 1.0 if composite_score >= 65.0 else 0.85
        elif composite_score <= -40.0:
            bias = CompositeBias.STRONG_BEARISH if composite_score <= -60.0 else CompositeBias.BEARISH
            allow_trading = False  # Avoid buying declining/bearish fundamentals
            allocation_multiplier = 0.0
        else:
            bias = CompositeBias.NEUTRAL
            allow_trading = True
            allocation_multiplier = 0.5

        # 4. Synthesize Audit Narrative (Explainability)
        narrative_parts = [
            f"Asset {symbol} evaluated at {eval_time.strftime('%Y-%m-%d %H:%M UTC')}.",
            f"Fundamental Health: {health_tier.value} (Score: {fund_score:.1f}/100, F-Score: {snapshot.piotroski_f_score}/9).",
            f"News Sentiment: {sentiment_score:+.1f}/100 based on {len(news_items)} recent articles.",
            f"Composite Bias: {bias.value} (Score: {composite_score:+.1f}).",
        ]
        if is_disqualified:
            narrative_parts.append(f"GATING ACTION: TRADING PROHIBITED — {disqualify_reason}")
        elif allow_trading:
            narrative_parts.append(f"GATING ACTION: Trading permitted with {allocation_multiplier*100:.0f}% risk allocation.")
        else:
            narrative_parts.append("GATING ACTION: Defensive hold / entries blocked due to adverse bias.")

        narrative = " ".join(narrative_parts)

        manifest = QuantamentalDecisionManifest(
            symbol=symbol,
            evaluated_at=eval_time,
            fundamental_score=fund_score,
            sentiment_score=sentiment_score,
            composite_score=composite_score,
            bias=bias,
            allow_trading=allow_trading,
            allocation_multiplier=allocation_multiplier,
            recent_news_count=len(news_items),
            catalysts=catalysts[:5],
            risks=risks[:5],
            narrative=narrative,
        )

        self._persist_evaluation(manifest, snapshot, news_items)
        return manifest

    def evaluate_universe(
        self,
        universe: Optional[List[str]] = None,
        as_of_time: Optional[datetime] = None,
    ) -> List[QuantamentalDecisionManifest]:
        """
        Runs batch evaluation across an entire asset universe.
        Sorts manifest by composite score descending (Best to Worst).
        """
        targets = universe or DEFAULT_UNIVERSE
        eval_time = as_of_time or datetime.now(timezone.utc)
        results: List[QuantamentalDecisionManifest] = []

        for sym in targets:
            try:
                res = self.evaluate_symbol(sym, as_of_time=eval_time)
                results.append(res)
            except Exception as e:
                logger.error(f"Error evaluating symbol {sym}: {e}")

        results.sort(key=lambda m: m.composite_score, reverse=True)
        self._export_universe_manifest(results, eval_time)
        return results

    def is_trade_allowed(self, symbol: str) -> Tuple[bool, str, float]:
        """
        Fast lookup pluggable directly into RiskEngine or Trading Daemons.
        Returns:
            allow_trading: bool
            reason: str
            allocation_multiplier: float
        """
        manifest = self.evaluate_symbol(symbol)
        return manifest.allow_trading, manifest.narrative, manifest.allocation_multiplier

    def _persist_evaluation(
        self,
        manifest: QuantamentalDecisionManifest,
        snapshot: FundamentalSnapshot,
        news_items: List[NewsItem],
    ):
        """Persists evaluation, fundamental snapshot, and news items to SQLite."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Insert news items
                for item in news_items:
                    cursor.execute("""
                        INSERT OR REPLACE INTO news_articles (
                            article_id, symbol, title, source, published_at,
                            sentiment_score, sentiment_label, confidence, urgency, category
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        item.article_id, item.symbol, item.title, item.source,
                        item.published_at.isoformat(), item.sentiment_score,
                        item.sentiment_label.value, item.confidence,
                        item.urgency.value, item.category.value
                    ))

                # Insert fundamental snapshot
                cursor.execute("""
                    INSERT INTO fundamental_snapshots (
                        symbol, as_of_date, pe_ratio, pb_ratio, debt_to_equity,
                        roe, operating_margin, revenue_growth_yoy, piotroski_f_score,
                        health_tier, red_flags
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    snapshot.symbol, snapshot.as_of_date.isoformat(),
                    snapshot.pe_ratio, snapshot.pb_ratio, snapshot.debt_to_equity,
                    snapshot.roe, snapshot.operating_margin, snapshot.revenue_growth_yoy,
                    snapshot.piotroski_f_score, snapshot.health_tier.value,
                    json.dumps(snapshot.red_flags)
                ))

                # Insert quantamental manifest
                manifest_dict = {
                    "symbol": manifest.symbol,
                    "evaluated_at": manifest.evaluated_at.isoformat(),
                    "fundamental_score": manifest.fundamental_score,
                    "sentiment_score": manifest.sentiment_score,
                    "composite_score": manifest.composite_score,
                    "bias": manifest.bias.value,
                    "allow_trading": manifest.allow_trading,
                    "allocation_multiplier": manifest.allocation_multiplier,
                    "recent_news_count": manifest.recent_news_count,
                    "catalysts": manifest.catalysts,
                    "risks": manifest.risks,
                    "narrative": manifest.narrative,
                }
                cursor.execute("""
                    INSERT OR REPLACE INTO quantamental_manifests (
                        symbol, evaluated_at, composite_score, bias, allow_trading,
                        allocation_multiplier, fundamental_score, sentiment_score,
                        recent_news_count, manifest_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    manifest.symbol, manifest.evaluated_at.isoformat(),
                    manifest.composite_score, manifest.bias.value,
                    1 if manifest.allow_trading else 0,
                    manifest.allocation_multiplier, manifest.fundamental_score,
                    manifest.sentiment_score, manifest.recent_news_count,
                    json.dumps(manifest_dict)
                ))
                conn.commit()
        except Exception as e:
            logger.warning(f"Failed to persist evaluation for {manifest.symbol}: {e}")

    def _export_universe_manifest(self, manifests: List[QuantamentalDecisionManifest], eval_time: datetime):
        """Exports JSON manifest to data/intelligence/."""
        dt_str = eval_time.strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(self.intelligence_dir, f"quantamental_manifest_{dt_str}.json")
        payload = {
            "evaluated_at": eval_time.isoformat(),
            "symbols_count": len(manifests),
            "manifests": [
                {
                    "symbol": m.symbol,
                    "composite_score": m.composite_score,
                    "bias": m.bias.value,
                    "allow_trading": m.allow_trading,
                    "allocation_multiplier": m.allocation_multiplier,
                    "fundamental_score": m.fundamental_score,
                    "sentiment_score": m.sentiment_score,
                    "news_count": m.recent_news_count,
                    "catalysts": m.catalysts,
                    "risks": m.risks,
                    "narrative": m.narrative,
                }
                for m in manifests
            ]
        }
        try:
            with open(filepath, "w") as f:
                json.dump(payload, f, indent=2)
            # Also write latest
            latest_path = os.path.join(self.intelligence_dir, "latest_manifest.json")
            with open(latest_path, "w") as f:
                json.dump(payload, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not write universe manifest JSON: {e}")

    def generate_intelligence_report(self, manifests: Optional[List[QuantamentalDecisionManifest]] = None) -> str:
        """Generates a comprehensive Markdown intelligence report."""
        targets = manifests or self.evaluate_universe()
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        lines = [
            "# Algo Lab — Market Fundamentals & News Intelligence Report",
            f"**Generated:** {now_str}  ",
            f"**Total Universe Covered:** {len(targets)} Instruments  \n",
            "## 1. Quantamental Leaderboard",
            "| Rank | Symbol | Composite Bias | Score | Fund Score | News Sentiment | Trade Gating | Allocation |",
            "| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
        ]

        for i, m in enumerate(targets, 1):
            gate_badge = "✅ PERMITTED" if m.allow_trading else "🚫 BLOCKED"
            score_sign = f"{m.composite_score:+.1f}"
            sent_sign = f"{m.sentiment_score:+.1f}"
            lines.append(
                f"| {i} | **{m.symbol}** | `{m.bias.value}` | **{score_sign}** | {m.fundamental_score:.1f}/100 | {sent_sign} | {gate_badge} | {m.allocation_multiplier*100:.0f}% |"
            )

        lines.extend([
            "",
            "## 2. Evidence Summaries & Catalysts",
            "",
        ])

        for m in targets:
            lines.append(f"### {m.symbol} ({m.bias.value})")
            lines.append(f"> **Explainability:** {m.narrative}")
            if m.catalysts:
                lines.append("**Key Catalysts:**")
                for c in m.catalysts:
                    lines.append(f"- 📈 {c}")
            if m.risks:
                lines.append("**Identified Risks:**")
                for r in m.risks:
                    lines.append(f"- ⚠️ {r}")
            lines.append("")

        return "\n".join(lines)
