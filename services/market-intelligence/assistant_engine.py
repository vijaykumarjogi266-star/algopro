"""
Algo Lab — Market Intelligence Assistant & Multi-Interval Scheduler Engine
Provides multi-interval scheduled harvesting across live news, macro feeds, and
financial fundamentals, alongside an interactive conversational query assistant.
"""

import json
import logging
import math
import os
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple

from services.market_intelligence.news_fundamental_contracts import (
    NewsItem,
    MacroNewsItem,
    CorporateCalendarEvent,
    AnalystConsensus,
    FundamentalSnapshot,
    QuantamentalDecisionManifest,
    CollectionScheduleConfig,
    CompositeBias,
    HealthTier,
    NewsUrgency,
)
from services.market_intelligence.news_fundamental_agent import (
    NewsFundamentalAgent,
    DEFAULT_UNIVERSE,
)
from services.market_intelligence.collector_service import (
    NewsCollector,
    FundamentalCollector,
    SYMBOL_ALIASES,
)

logger = logging.getLogger("MarketIntelligenceAssistant")

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_DB_PATH = os.path.join(PROJECT_ROOT, "data", "market_intelligence.db")
DEFAULT_INTELLIGENCE_DIR = os.path.join(PROJECT_ROOT, "data", "intelligence")


class MarketIntelligenceAssistant:
    """
    Quantamental Research Assistant with autonomous multi-interval harvesting:
    - Tier 1: Real-time News Ingestion (e.g. Every 15 minutes)
    - Tier 2: Macroeconomic & Policy Watch (e.g. Every 60 minutes)
    - Tier 3: Fundamental Ratios & Balance Sheets (e.g. Every 12 hours)
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        intelligence_dir: Optional[str] = None,
        schedule_config: Optional[CollectionScheduleConfig] = None,
        force_offline: bool = False,
        allow_synthetic_fallback: bool = True,
    ):
        self.db_path = db_path or DEFAULT_DB_PATH
        self.intelligence_dir = intelligence_dir or DEFAULT_INTELLIGENCE_DIR
        self.config = schedule_config or CollectionScheduleConfig()
        self.force_offline = force_offline
        self.allow_synthetic_fallback = allow_synthetic_fallback

        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        os.makedirs(self.intelligence_dir, exist_ok=True)

        self.agent = NewsFundamentalAgent(
            db_path=self.db_path,
            intelligence_dir=self.intelligence_dir,
            force_offline=self.force_offline,
            allow_synthetic_fallback=self.allow_synthetic_fallback,
        )
        self.news_collector = self.agent.news_collector
        self.fundamental_collector = self.agent.fundamental_collector

        from services.market_intelligence.stock_decision_engine import StockDecisionEngine
        self.decision_engine = StockDecisionEngine(
            agent=self.agent,
            db_path=self.db_path,
        )

        self._init_assistant_db()

    def _init_assistant_db(self):
        """Initializes tables for macro news, calendar, consensus, schedule tracking, and decisions."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS macro_news (
                    item_id TEXT PRIMARY KEY,
                    headline TEXT NOT NULL,
                    source TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    sentiment_score REAL NOT NULL,
                    theme TEXT NOT NULL,
                    url TEXT
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS corporate_calendar (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    event_date TEXT,
                    description TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS analyst_consensus (
                    symbol TEXT PRIMARY KEY,
                    target_mean REAL,
                    target_high REAL,
                    target_low REAL,
                    current_price REAL,
                    upside_potential_pct REAL,
                    recommendation_key TEXT NOT NULL,
                    number_of_analysts INTEGER,
                    updated_at TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS collection_schedule_state (
                    tier_name TEXT PRIMARY KEY,
                    last_run_utc TEXT NOT NULL,
                    records_collected INTEGER NOT NULL,
                    status TEXT NOT NULL
                )
            """)
            cursor.execute("""
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
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_stock_selections_generated_at ON stock_selections(generated_at)")
            cursor.execute("""
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
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_selection_candidates_selection_id ON stock_selection_candidates(selection_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_selection_candidates_symbol ON stock_selection_candidates(symbol)")
            cursor.execute("""
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
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trade_decisions_symbol ON trade_decisions(symbol)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trade_decisions_evaluated_at ON trade_decisions(evaluated_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trade_decisions_action ON trade_decisions(action)")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS eod_reports (
                    report_date TEXT PRIMARY KEY,
                    generated_at TEXT NOT NULL,
                    session_id TEXT,
                    starting_capital REAL NOT NULL,
                    ending_equity REAL NOT NULL,
                    gross_pnl REAL NOT NULL,
                    net_pnl REAL NOT NULL,
                    total_trades INTEGER NOT NULL,
                    winning_trades INTEGER NOT NULL,
                    losing_trades INTEGER NOT NULL,
                    win_rate_pct REAL NOT NULL,
                    profit_factor REAL,
                    max_drawdown_pct REAL,
                    reconciliation_status TEXT NOT NULL,
                    variance REAL NOT NULL,
                    market_regime TEXT NOT NULL,
                    selected_strategy TEXT NOT NULL,
                    risk_multiplier REAL NOT NULL,
                    top_stock_picks TEXT NOT NULL,
                    executive_summary TEXT NOT NULL,
                    report_markdown TEXT NOT NULL,
                    metrics_json TEXT NOT NULL
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_eod_reports_generated_at ON eod_reports(generated_at)")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS research_strategy_decisions (
                    decision_date TEXT PRIMARY KEY,
                    target_session_date TEXT NOT NULL,
                    evaluated_at TEXT NOT NULL,
                    market_regime TEXT NOT NULL,
                    selected_strategy TEXT NOT NULL,
                    risk_multiplier REAL NOT NULL,
                    allocation_reason TEXT NOT NULL,
                    candidate_evaluations_json TEXT NOT NULL,
                    stock_selection_json TEXT,
                    eod_audit_json TEXT,
                    decision_manifest_json TEXT NOT NULL
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_research_decisions_target ON research_strategy_decisions(target_session_date)")
            conn.commit()

    # =========================================================================
    # MULTI-INTERVAL SCHEDULED HARVESTING
    # =========================================================================

    def run_scheduled_cycle(self, universe: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Evaluates elapsed time against configured intervals for each data tier:
        - News (every N mins)
        - Macro (every M mins)
        - Fundamentals (every H hours)
        Executes only eligible collection routines.
        """
        targets = universe or DEFAULT_UNIVERSE
        now = datetime.now(timezone.utc)
        results = {
            "timestamp": now.isoformat(),
            "tiers_executed": [],
            "news_count": 0,
            "macro_count": 0,
            "fundamentals_updated": 0,
        }

        # 1. Tier 1: News Stream (Default: 15 mins)
        if self._is_tier_due("NEWS_STREAM", self.config.news_interval_minutes * 60, now):
            logger.info("Executing Scheduled Tier 1: Real-time News Stream Collection...")
            collected_news = 0
            for sym in targets:
                try:
                    items = self.news_collector.fetch_symbol_news(sym, limit=15, as_of_time=now)
                    self._persist_news_items(items)
                    collected_news += len(items)
                except Exception as e:
                    logger.warning(f"Scheduled news error for {sym}: {e}")

            self._update_tier_state("NEWS_STREAM", now, collected_news)
            results["tiers_executed"].append("NEWS_STREAM")
            results["news_count"] = collected_news

        # 2. Tier 2: Macro & Policy Watch (Default: 60 mins)
        if self._is_tier_due("MACRO_WATCH", self.config.macro_interval_minutes * 60, now):
            logger.info("Executing Scheduled Tier 2: Macroeconomic & Policy Collection...")
            try:
                macro_items = self.news_collector.fetch_macro_news(limit=20, as_of_time=now)
                self._persist_macro_news(macro_items)
                self._update_tier_state("MACRO_WATCH", now, len(macro_items))
                results["tiers_executed"].append("MACRO_WATCH")
                results["macro_count"] = len(macro_items)
            except Exception as e:
                logger.warning(f"Scheduled macro news error: {e}")

        # 3. Tier 3: Fundamentals, Balance Sheets & Analyst Consensus (Default: 12 hours)
        if self._is_tier_due("FUNDAMENTALS_DEEP", self.config.fundamentals_interval_hours * 3600, now):
            logger.info("Executing Scheduled Tier 3: Fundamentals & Analyst Consensus...")
            fund_count = 0
            for sym in targets:
                try:
                    # Refresh fundamentals
                    snap = self.fundamental_collector.fetch_fundamental_snapshot(sym, as_of_date=now.date())
                    # Refresh calendar & consensus
                    cal = self.fundamental_collector.fetch_corporate_calendar(sym)
                    consensus = self.fundamental_collector.fetch_analyst_consensus(sym)
                    self._persist_consensus_and_calendar(sym, consensus, cal, now)
                    fund_count += 1
                except Exception as e:
                    logger.warning(f"Scheduled fundamentals error for {sym}: {e}")

            # Re-evaluate quantamental decision manifests for universe
            self.agent.evaluate_universe(targets, as_of_time=now)
            self._update_tier_state("FUNDAMENTALS_DEEP", now, fund_count)
            results["tiers_executed"].append("FUNDAMENTALS_DEEP")
            results["fundamentals_updated"] = fund_count

        return results

    def _is_tier_due(self, tier_name: str, interval_seconds: float, now: datetime) -> bool:
        """Checks if elapsed seconds since last run exceeds interval threshold."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT last_run_utc FROM collection_schedule_state WHERE tier_name=?", (tier_name,))
            row = cur.fetchone()
            if not row:
                return True
            try:
                last_run = datetime.fromisoformat(row[0])
                elapsed = (now - last_run).total_seconds()
                return elapsed >= interval_seconds
            except Exception:
                return True

    def _update_tier_state(self, tier_name: str, now: datetime, count: int):
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT OR REPLACE INTO collection_schedule_state (tier_name, last_run_utc, records_collected, status)
                VALUES (?, ?, ?, ?)
            """, (tier_name, now.isoformat(), count, "COMPLETED"))
            conn.commit()

    def _persist_macro_news(self, items: List[MacroNewsItem]):
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            for it in items:
                cur.execute("""
                    INSERT OR REPLACE INTO macro_news (item_id, headline, source, published_at, sentiment_score, theme, url)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (it.item_id, it.headline, it.source, it.published_at.isoformat(), it.sentiment_score, it.theme, it.url))
            conn.commit()

    def _persist_consensus_and_calendar(
        self,
        symbol: str,
        consensus: AnalystConsensus,
        events: List[CorporateCalendarEvent],
        now: datetime,
    ):
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT OR REPLACE INTO analyst_consensus (
                    symbol, target_mean, target_high, target_low, current_price,
                    upside_potential_pct, recommendation_key, number_of_analysts, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                consensus.symbol, consensus.target_mean, consensus.target_high,
                consensus.target_low, consensus.current_price, consensus.upside_potential_pct,
                consensus.recommendation_key, consensus.number_of_analysts, now.isoformat()
            ))

            for ev in events:
                cur.execute("""
                    INSERT INTO corporate_calendar (symbol, event_type, event_date, description, recorded_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (ev.symbol, ev.event_type, ev.event_date, ev.description, now.isoformat()))
            conn.commit()

    def _persist_news_items(self, items: List[NewsItem]):
        """Persists newly fetched news items into news_articles table."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            for it in items:
                cur.execute("""
                    INSERT OR REPLACE INTO news_articles (
                        article_id, symbol, title, source, published_at,
                        sentiment_score, sentiment_label, confidence, urgency, category
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    it.article_id, it.symbol, it.title, it.source,
                    it.published_at.isoformat(), it.sentiment_score,
                    it.sentiment_label.value, it.confidence,
                    it.urgency.value, it.category.value
                ))
            conn.commit()

    def get_latest_stock_selection(self) -> Optional[Dict[str, Any]]:
        """Retrieves the latest stock selection manifest from SQLite database."""
        return self.decision_engine.get_latest_stock_selection()

    def get_recent_decisions(
        self,
        limit: int = 15,
        symbol: Optional[str] = None,
        action: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieves recent trade decisions from SQLite database."""
        return self.decision_engine.get_recent_trade_decisions(limit=limit, symbol=symbol, action=action)

    def format_decisions_table(self, decisions: List[Dict[str, Any]]) -> str:
        """Formats trade decisions list into a markdown audit table."""
        if not decisions:
            return "ℹ️ No trade gating decisions recorded in the database."
        lines = [
            "### 📋 Trade Decision Audit Trail (from SQLite Database)",
            "",
            "| Timestamp (UTC) | Symbol | Signal | Action | Sizing Scale | Conviction | Decision Rationale |",
            "| :--- | :--- | :---: | :---: | :---: | :---: | :--- |",
        ]
        for d in decisions:
            t_str = d["evaluated_at"][:19].replace("T", " ")
            act = d["action"]
            badge = "✅ BUY" if act == "APPROVE_BUY" else ("🚫 VETO" if act == "VETO" else ("🚨 EXIT" if act == "EMERGENCY_EXIT" else "⏳ WAIT"))
            scale = f"{d['approved_quantity_scale']*100:.0f}%"
            reason_snip = d["reason"][:75] + ("..." if len(d["reason"]) > 75 else "")
            lines.append(f"| {t_str} | **{d['symbol']}** | `{d['proposed_signal']}` | {badge} | {scale} | {d['conviction_score']:.1f} | {reason_snip} |")
        return "\n".join(lines)

    def format_stock_selection_markdown(self, sel: Dict[str, Any]) -> str:
        """Formats a stock selection manifest into rich markdown."""
        t_str = sel["generated_at"][:19].replace("T", " ")
        lines = [
            f"### 🎯 Latest Stock Selection Manifest ({t_str} UTC)",
            f"> **Selection ID:** `{sel['selection_id']}`",
            f"> **Audit Rationale:** {sel['narrative']}",
            "",
            f"- 🌟 **Top Conviction Picks:** {', '.join(sel['top_picks'])}",
            f"- ✅ **Approved Universe:** {', '.join(sel['selected_portfolio'])}",
            f"- 🚫 **Excluded / Vetoed:** {', '.join(sel['excluded_portfolio']) or 'None'}",
            "",
            "| Rank | Symbol | Tier | Score | F-Score | ROE | Upside | Allocation | Gate |",
            "| :---: | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
        ]
        for c in sel["candidates"]:
            t_name = c["tier"].replace("TIER_", "T").replace("_", " ")
            upside = f"{c['analyst_upside_pct']:+.1f}%" if c.get("analyst_upside_pct") is not None else "N/A"
            gate = "✅ APPROVED" if c["is_eligible_for_trading"] else "🚫 EXCLUDED"
            lines.append(f"| {c['rank']} | **{c['symbol']}** | `{t_name}` | {c['quantamental_score']:+.1f} | {c['piotroski_f_score']}/9 | {c['roe_pct']:.1f}% | {upside} | {c['allocation_multiplier']*100:.0f}% | {gate} |")
        return "\n".join(lines)

    # =========================================================================
    # EOD REPORTS & RESEARCH STRATEGY PERSISTENCE
    # =========================================================================

    def save_eod_report(self, report_data: Dict[str, Any]) -> str:
        """Persists a complete daily EOD report to SQLite."""
        report_date = report_data["report_date"]
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT OR REPLACE INTO eod_reports (
                    report_date, generated_at, session_id, starting_capital, ending_equity,
                    gross_pnl, net_pnl, total_trades, winning_trades, losing_trades,
                    win_rate_pct, profit_factor, max_drawdown_pct, reconciliation_status,
                    variance, market_regime, selected_strategy, risk_multiplier,
                    top_stock_picks, executive_summary, report_markdown, metrics_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                report_date,
                report_data.get("generated_at", datetime.now(timezone.utc).isoformat()),
                report_data.get("session_id", ""),
                float(report_data.get("starting_capital", 0.0)),
                float(report_data.get("ending_equity", 0.0)),
                float(report_data.get("gross_pnl", 0.0)),
                float(report_data.get("net_pnl", 0.0)),
                int(report_data.get("total_trades", 0)),
                int(report_data.get("winning_trades", 0)),
                int(report_data.get("losing_trades", 0)),
                float(report_data.get("win_rate_pct", 0.0)),
                float(report_data.get("profit_factor", 0.0)) if report_data.get("profit_factor") is not None else None,
                float(report_data.get("max_drawdown_pct", 0.0)),
                report_data.get("reconciliation_status", "MATCH"),
                float(report_data.get("variance", 0.0)),
                report_data.get("market_regime", "UNKNOWN"),
                report_data.get("selected_strategy", "WAIT"),
                float(report_data.get("risk_multiplier", 1.0)),
                json.dumps(report_data.get("top_stock_picks", [])),
                report_data.get("executive_summary", ""),
                report_data.get("report_markdown", ""),
                json.dumps(report_data.get("metrics_json", {})),
            ))
            conn.commit()
        return report_date

    def get_eod_report(self, report_date: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Retrieves an EOD report from SQLite by date or returns the latest."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            if report_date:
                cur.execute("SELECT * FROM eod_reports WHERE report_date = ?", (report_date,))
            else:
                cur.execute("SELECT * FROM eod_reports ORDER BY report_date DESC LIMIT 1")
            row = cur.fetchone()
            if not row:
                return None
            return {
                "report_date": row["report_date"],
                "generated_at": row["generated_at"],
                "session_id": row["session_id"],
                "starting_capital": row["starting_capital"],
                "ending_equity": row["ending_equity"],
                "gross_pnl": row["gross_pnl"],
                "net_pnl": row["net_pnl"],
                "total_trades": row["total_trades"],
                "winning_trades": row["winning_trades"],
                "losing_trades": row["losing_trades"],
                "win_rate_pct": row["win_rate_pct"],
                "profit_factor": row["profit_factor"],
                "max_drawdown_pct": row["max_drawdown_pct"],
                "reconciliation_status": row["reconciliation_status"],
                "variance": row["variance"],
                "market_regime": row["market_regime"],
                "selected_strategy": row["selected_strategy"],
                "risk_multiplier": row["risk_multiplier"],
                "top_stock_picks": json.loads(row["top_stock_picks"]) if row["top_stock_picks"] else [],
                "executive_summary": row["executive_summary"],
                "report_markdown": row["report_markdown"],
                "metrics_json": json.loads(row["metrics_json"]) if row["metrics_json"] else {},
            }

    def get_recent_eod_reports(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Retrieves summaries of recent EOD reports from SQLite."""
        results = []
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("""
                SELECT report_date, generated_at, session_id, net_pnl, win_rate_pct,
                       total_trades, market_regime, selected_strategy, reconciliation_status
                FROM eod_reports ORDER BY report_date DESC LIMIT ?
            """, (limit,))
            for r in cur.fetchall():
                results.append({
                    "report_date": r["report_date"],
                    "generated_at": r["generated_at"],
                    "session_id": r["session_id"],
                    "net_pnl": r["net_pnl"],
                    "win_rate_pct": r["win_rate_pct"],
                    "total_trades": r["total_trades"],
                    "market_regime": r["market_regime"],
                    "selected_strategy": r["selected_strategy"],
                    "reconciliation_status": r["reconciliation_status"],
                })
        return results

    def save_research_strategy_decision(self, manifest: Dict[str, Any]) -> str:
        """Persists autonomous quantitative research strategy decision to SQLite."""
        dec_date = manifest.get("decision_date", datetime.now(timezone.utc).isoformat())[:10]
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT OR REPLACE INTO research_strategy_decisions (
                    decision_date, target_session_date, evaluated_at, market_regime,
                    selected_strategy, risk_multiplier, allocation_reason,
                    candidate_evaluations_json, stock_selection_json, eod_audit_json,
                    decision_manifest_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                dec_date,
                manifest.get("target_session_date", ""),
                manifest.get("decision_date", datetime.now(timezone.utc).isoformat()),
                manifest.get("market_regime", "UNKNOWN"),
                manifest.get("selected_strategy", "WAIT"),
                float(manifest.get("risk_multiplier", 1.0)),
                manifest.get("allocation_reason", ""),
                json.dumps(manifest.get("candidate_evaluations", [])),
                json.dumps(manifest.get("stock_selection", {})),
                json.dumps(manifest.get("eod_audit", {})),
                json.dumps(manifest),
            ))
            conn.commit()
        return dec_date

    def get_latest_research_strategy_decision(self) -> Optional[Dict[str, Any]]:
        """Retrieves the latest autonomous strategy allocation decision from SQLite."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT * FROM research_strategy_decisions ORDER BY decision_date DESC LIMIT 1")
            row = cur.fetchone()
            if not row:
                return None
            return {
                "decision_date": row["decision_date"],
                "target_session_date": row["target_session_date"],
                "evaluated_at": row["evaluated_at"],
                "market_regime": row["market_regime"],
                "selected_strategy": row["selected_strategy"],
                "risk_multiplier": row["risk_multiplier"],
                "allocation_reason": row["allocation_reason"],
                "candidate_evaluations": json.loads(row["candidate_evaluations_json"]),
                "stock_selection": json.loads(row["stock_selection_json"]) if row["stock_selection_json"] else {},
                "eod_audit": json.loads(row["eod_audit_json"]) if row["eod_audit_json"] else {},
            }

    # =========================================================================
    # ASSISTANT REPORTING & CONVERSATIONAL QUERY FEATURES
    # =========================================================================

    def get_market_briefing(self) -> str:
        """Returns an executive macro & equity intelligence briefing."""
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        manifests = self.agent.evaluate_universe()
        macro_news = self.news_collector.fetch_macro_news(limit=5)
        alerts = self.get_breaking_alerts()

        lines = [
            f"# Algo Lab Assistant — Market Intelligence Briefing ({now_str})",
            "",
            "## 🌍 Macroeconomic & Policy Pulse",
        ]
        if macro_news:
            for m in macro_news:
                sent_emoji = "🟢" if m.sentiment_score > 0.1 else ("🔴" if m.sentiment_score < -0.1 else "⚪")
                lines.append(f"- {sent_emoji} **[{m.theme}]** {m.headline} *({m.source})*")
        else:
            lines.append("- Domestic macro policy remains steady.")

        lines.extend([
            "",
            "## 📊 Top Quantamental Leaderboard",
            "| Symbol | Bias | Score | Fund Score | Sentiment | Trade Gating | Allocation |",
            "| :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
        ])
        for m in manifests:
            status = "✅ ALLOW" if m.allow_trading else "🚫 BLOCK"
            lines.append(
                f"| **{m.symbol}** | `{m.bias.value}` | **{m.composite_score:+.1f}** | {m.fundamental_score:.1f}/100 | {m.sentiment_score:+.1f} | {status} | {m.allocation_multiplier*100:.0f}% |"
            )

        if alerts:
            lines.extend([
                "",
                "## ⚠️ High Urgency Breaking Alerts",
            ])
            for a in alerts:
                lines.append(f"- 🚨 **{a['symbol']}**: {a['title']} *({a['source']})* [Sentiment: {a['sentiment']:+.2f}]")

        return "\n".join(lines)

    def get_breaking_alerts(self) -> List[Dict[str, Any]]:
        """Finds breaking news articles with HIGH urgency in the last 24 hours."""
        alerts: List[Dict[str, Any]] = []
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT symbol, title, source, published_at, sentiment_score, urgency, category
                FROM news_articles
                WHERE urgency = 'HIGH'
                ORDER BY published_at DESC LIMIT 10
            """)
            for row in cur.fetchall():
                alerts.append({
                    "symbol": row[0],
                    "title": row[1],
                    "source": row[2],
                    "published_at": row[3],
                    "sentiment": row[4],
                    "urgency": row[5],
                    "category": row[6],
                })
        return alerts

    def compare_assets(self, symbols: List[str]) -> str:
        """Produces a side-by-side comparative table of fundamental ratios, sentiment, and consensus."""
        lines = [
            f"# Comparative Quantamental Analysis: {', '.join(symbols)}",
            "",
            "| Metric | " + " | ".join(symbols) + " |",
            "| :--- | " + " | ".join([":---:"] * len(symbols)) + " |",
        ]

        data = {}
        for sym in symbols:
            manifest = self.agent.evaluate_symbol(sym)
            snap = self.fundamental_collector.fetch_fundamental_snapshot(sym)
            consensus = self.fundamental_collector.fetch_analyst_consensus(sym)
            data[sym] = {"manifest": manifest, "snap": snap, "consensus": consensus}

        # Rows
        lines.append("| **Composite Bias** | " + " | ".join(f"`{data[s]['manifest'].bias.value}`" for s in symbols) + " |")
        lines.append("| **Composite Score** | " + " | ".join(f"{data[s]['manifest'].composite_score:+.1f}" for s in symbols) + " |")
        lines.append("| **Trade Permission** | " + " | ".join("✅ PERMITTED" if data[s]["manifest"].allow_trading else "🚫 BLOCKED" for s in symbols) + " |")
        lines.append("| **Piotroski F-Score** | " + " | ".join(f"{data[s]['snap'].piotroski_f_score}/9" for s in symbols) + " |")
        lines.append("| **P/E Ratio** | " + " | ".join(f"{data[s]['snap'].pe_ratio:.1f}x" if data[s]['snap'].pe_ratio else "N/A" for s in symbols) + " |")
        lines.append("| **ROE** | " + " | ".join(f"{data[s]['snap'].roe*100:.1f}%" if data[s]['snap'].roe else "N/A" for s in symbols) + " |")
        lines.append("| **Operating Margin** | " + " | ".join(f"{data[s]['snap'].operating_margin*100:.1f}%" if data[s]['snap'].operating_margin else "N/A" for s in symbols) + " |")
        lines.append("| **Debt / Equity** | " + " | ".join(f"{data[s]['snap'].debt_to_equity:.2f}x" if data[s]['snap'].debt_to_equity is not None else "Bank/N/A" for s in symbols) + " |")
        lines.append("| **News Sentiment** | " + " | ".join(f"{data[s]['manifest'].sentiment_score:+.1f}" for s in symbols) + " |")
        lines.append("| **Consensus Rating** | " + " | ".join(f"{data[s]['consensus'].recommendation_key.upper()}" for s in symbols) + " |")
        lines.append("| **Target Upside** | " + " | ".join(f"{data[s]['consensus'].upside_potential_pct:+.1f}%" if data[s]['consensus'].upside_potential_pct is not None else "N/A" for s in symbols) + " |")

        return "\n".join(lines)

    def ask(self, query: str) -> str:
        """
        Processes conversational questions and returns explainable assistant answers.
        """
        q = query.lower()

        # Check if comparing symbols
        matched_symbols = []
        for sym, aliases in SYMBOL_ALIASES.items():
            if any(alias in q for alias in aliases) or sym.lower() in q:
                matched_symbols.append(sym)

        if "brief" in q or "overview" in q or "market" in q and not matched_symbols:
            return self.get_market_briefing()

        if "alert" in q or "breaking" in q or "risk" in q and not matched_symbols:
            alerts = self.get_breaking_alerts()
            if not alerts:
                return "✅ No breaking high-urgency alerts or governance red flags in the past 24 hours across the universe."
            resp = ["### 🚨 High Urgency Alerts:"]
            for a in alerts:
                resp.append(f"- **{a['symbol']}**: {a['title']} *({a['source']})* [Sentiment: {a['sentiment']:+.2f}]")
            return "\n".join(resp)

        if len(matched_symbols) > 1 and ("compare" in q or "vs" in q):
            return self.compare_assets(matched_symbols)

        # Check EOD report query
        if any(w in q for w in ["eod report", "today's report", "today eod", "daily report", "performance report", "eod audit", "tearsheet", "how did we do", "today's performance"]):
            eod = self.get_eod_report()
            if eod:
                return eod["report_markdown"]
            return "ℹ️ No EOD report found in the database. Run the EOD audit cycle to generate."

        # Check research strategy decision query
        if any(w in q for w in ["strategy allocation", "research decision", "selected strategy", "tomorrow's strategy", "strategy decision", "backtest results"]):
            strat = self.get_latest_research_strategy_decision()
            if strat:
                lines = [
                    f"### 🤖 Autonomous Strategy Research Decision ({strat['decision_date']})",
                    f"> **Target Session:** `{strat['target_session_date']}`",
                    f"> **Market Regime:** `{strat['market_regime']}`",
                    f"> **Selected Strategy:** `{strat['selected_strategy']}` (Risk Multiplier: {strat['risk_multiplier']}x)",
                    f"> **Rationale:** {strat['allocation_reason']}",
                    "",
                    "| Strategy | Trades | Win Rate | Profit Factor | Sharpe | DSR | Status |",
                    "| :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
                ]
                for c in strat.get("candidate_evaluations", []):
                    status_badge = "✅ SELECTED" if c.get("is_robust") else "🚫 REJECTED"
                    lines.append(f"| **{c['strategy']}** | {c.get('trades_count', 0)} | {c.get('win_rate_pct', 0.0)}% | {c.get('profit_factor', 0.0):.2f} | {c.get('sharpe_ratio', 0.0):.2f} | {c.get('dsr', 0.0):.4f} | {status_badge} |")
                return "\n".join(lines)
            return "ℹ️ No strategy research decisions recorded in the database yet."

        # Check decision history query
        if any(w in q for w in ["decision history", "recent decision", "past decision", "trade decision", "veto history", "decisions"]):
            matched_sym = matched_symbols[0] if matched_symbols else None
            decisions = self.get_recent_decisions(limit=10, symbol=matched_sym)
            if not decisions:
                return "ℹ️ No trade gating decisions recorded in the database yet."
            return self.format_decisions_table(decisions)

        # Check stock selection history query
        if any(w in q for w in ["last selection", "latest selection", "recent selection", "stock selection", "portfolio pick", "top pick", "selection history"]):
            sel = self.get_latest_stock_selection()
            if not sel:
                return "ℹ️ No stock selection runs recorded in the database yet. Run --select-stocks to generate one."
            return self.format_stock_selection_markdown(sel)

        if len(matched_symbols) == 1:
            sym = matched_symbols[0]
            manifest = self.agent.evaluate_symbol(sym)
            snap = self.fundamental_collector.fetch_fundamental_snapshot(sym)
            consensus = self.fundamental_collector.fetch_analyst_consensus(sym)
            cal = self.fundamental_collector.fetch_corporate_calendar(sym)

            lines = [
                f"### 📋 Assistant Quantamental Dossier: {sym}",
                f"> **Explainability:** {manifest.narrative}",
                "",
                f"- **Composite Bias:** `{manifest.bias.value}` (Score: {manifest.composite_score:+.1f})",
                f"- **Trade Gating:** {'✅ PERMITTED' if manifest.allow_trading else '🚫 BLOCKED'} (Allocation Scale: {manifest.allocation_multiplier*100:.0f}%)",
                f"- **Fundamental Quality:** {snap.health_tier.value} | Piotroski: {snap.piotroski_f_score}/9 | ROE: {snap.roe*100:.1f}% | P/E: {snap.pe_ratio:.1f}x",
                f"- **Analyst Consensus:** {consensus.recommendation_key.upper()} ({consensus.number_of_analysts or 'N/A'} analysts) | Target Price Upside: {consensus.upside_potential_pct or 'N/A'}%",
                f"- **Recent News Sentiment:** {manifest.sentiment_score:+.1f} across {manifest.recent_news_count} sources.",
            ]
            if manifest.catalysts:
                lines.append("**Key Catalysts:**")
                for c in manifest.catalysts[:3]:
                    lines.append(f"  + {c}")
            if manifest.risks:
                lines.append("**Identified Risks:**")
                for r in manifest.risks[:3]:
                    lines.append(f"  - {r}")
            if cal:
                lines.append("**Upcoming Calendar:**")
                for ev in cal[:2]:
                    lines.append(f"  📅 {ev.description}")

            return "\n".join(lines)

        # Fallback to general briefing
        return self.get_market_briefing()

    def get_status(self) -> Dict[str, Any]:
        """Returns internal state and telemetry of collection tiers and persisted data tables."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM news_articles")
            news_count = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM macro_news")
            macro_count = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM fundamental_snapshots")
            fund_count = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM corporate_calendar")
            cal_count = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM analyst_consensus")
            consensus_count = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM quantamental_manifests")
            manifest_count = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM stock_selections")
            sel_count = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM stock_selection_candidates")
            cand_count = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM trade_decisions")
            dec_count = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM eod_reports")
            eod_count = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM research_strategy_decisions")
            research_count = cur.fetchone()[0]

            cur.execute("SELECT tier_name, last_run_utc, records_collected FROM collection_schedule_state")
            tiers = {r[0]: {"last_run": r[1], "records": r[2]} for r in cur.fetchall()}

        return {
            "database_path": self.db_path,
            "total_news_articles": news_count,
            "total_macro_items": macro_count,
            "total_fundamental_snapshots": fund_count,
            "total_calendar_events": cal_count,
            "total_analyst_consensus": consensus_count,
            "total_quantamental_manifests": manifest_count,
            "total_stock_selections": sel_count,
            "total_selection_candidates": cand_count,
            "total_trade_decisions": dec_count,
            "total_eod_reports": eod_count,
            "total_research_strategy_decisions": research_count,
            "schedule_intervals": {
                "news_minutes": self.config.news_interval_minutes,
                "macro_minutes": self.config.macro_interval_minutes,
                "fundamentals_hours": self.config.fundamentals_interval_hours,
            },
            "schedule_tiers": tiers,
        }
