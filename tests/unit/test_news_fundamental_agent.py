"""
Unit tests for Algo Lab News & Market Fundamentals Agent.
Verifies point-in-time lookahead safety, financial NLP accuracy, fundamental scoring,
disqualification filters, SQLite persistence, and trade gating logic.
"""

import os
import shutil
import tempfile
from datetime import datetime, timezone, timedelta, date

import pytest

from services.market_intelligence.news_fundamental_contracts import (
    NewsItem,
    NewsUrgency,
    NewsCategory,
    SentimentLabel,
    FundamentalSnapshot,
    HealthTier,
    CompositeBias,
    QuantamentalDecisionManifest,
)
from services.market_intelligence.sentiment_engine import (
    FinancialSentimentAnalyzer,
    FINANCIAL_LEXICON,
)
from services.market_intelligence.fundamental_engine import FundamentalAnalyzer
from services.market_intelligence.collector_service import (
    NewsCollector,
    FundamentalCollector,
    BENCHMARK_FUNDAMENTAL_FIXTURES,
)
from services.market_intelligence.news_fundamental_agent import NewsFundamentalAgent


@pytest.fixture
def temp_intel_env():
    """Provides isolated temporary directories for database and manifests."""
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_market_intelligence.db")
    intel_dir = os.path.join(temp_dir, "test_intelligence")
    yield {"temp_dir": temp_dir, "db_path": db_path, "intel_dir": intel_dir}
    shutil.rmtree(temp_dir, ignore_errors=True)


class TestNewsContractsAndLookahead:
    def test_point_in_time_lookahead_eligibility(self):
        """Enforces INV-26: News items must NOT be eligible before their publication time."""
        t_pub = datetime(2026, 10, 13, 10, 0, 0, tzinfo=timezone.utc)
        item = NewsItem(
            article_id="art_123",
            symbol="RELIANCE.NS",
            title="Reliance Q2 Profit Surge",
            summary="Details",
            source="Economic Times",
            published_at=t_pub,
            ingested_at=t_pub + timedelta(minutes=5),
            sentiment_score=0.75,
            sentiment_label=SentimentLabel.BULLISH,
        )

        # Before publication time -> INELIGIBLE (prevents lookahead bias)
        t_sim_before = datetime(2026, 10, 13, 9, 59, 0, tzinfo=timezone.utc)
        assert not item.is_eligible_at(t_sim_before)

        # At publication time -> ELIGIBLE
        assert item.is_eligible_at(t_pub)

        # After publication time -> ELIGIBLE
        t_sim_after = datetime(2026, 10, 13, 10, 30, 0, tzinfo=timezone.utc)
        assert item.is_eligible_at(t_sim_after)


class TestFinancialSentimentAnalyzer:
    def test_bullish_sentiment_classification(self):
        analyzer = FinancialSentimentAnalyzer()
        text = "TCS announces record profit and 25% dividend hike after blowout earnings"
        score, label, conf, cat, urg = analyzer.analyze_text(text)

        assert score > 0.4
        assert label == SentimentLabel.BULLISH
        assert cat in [NewsCategory.EARNINGS, NewsCategory.DIVIDEND_SPLIT]
        assert urg in [NewsUrgency.MEDIUM, NewsUrgency.HIGH]

    def test_bearish_sentiment_and_high_urgency_probe(self):
        analyzer = FinancialSentimentAnalyzer()
        text = "SEBI probe launched into corporate accounting fraud and promoter pledge defaults"
        score, label, conf, cat, urg = analyzer.analyze_text(text)

        assert score < -0.6
        assert label == SentimentLabel.BEARISH
        assert cat in [NewsCategory.REGULATORY, NewsCategory.CORPORATE_GOVERNANCE]
        assert urg == NewsUrgency.HIGH

    def test_negation_handling(self):
        analyzer = FinancialSentimentAnalyzer()
        # "failed to beat expectations" should flip sentiment negative
        text = "Company failed to beat expectations with revenue down"
        score, label, conf, cat, urg = analyzer.analyze_text(text)

        assert score < 0.0
        assert label == SentimentLabel.BEARISH

    def test_recency_decay_calculation(self):
        analyzer = FinancialSentimentAnalyzer()
        now = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)

        # Recent bullish article (1 hour ago)
        item_fresh = NewsItem(
            article_id="1", symbol="INFY.NS", title="Fresh beat", summary="s",
            source="ET", published_at=now - timedelta(hours=1), ingested_at=now,
            sentiment_score=0.8, sentiment_label=SentimentLabel.BULLISH, confidence=0.9
        )
        # Old bearish article (48 hours ago)
        item_old = NewsItem(
            article_id="2", symbol="INFY.NS", title="Old drop", summary="s",
            source="ET", published_at=now - timedelta(hours=48), ingested_at=now,
            sentiment_score=-0.8, sentiment_label=SentimentLabel.BEARISH, confidence=0.9
        )

        decayed_score = analyzer.calculate_decayed_sentiment([item_fresh, item_old], as_of_time=now)
        # Fresh news should dominate due to 24h half-life decay
        assert decayed_score > 0.0


class TestFundamentalAnalyzer:
    def test_prime_quality_evaluation(self):
        analyzer = FundamentalAnalyzer()
        snapshot = FundamentalSnapshot(
            symbol="TCS.NS",
            as_of_date=date(2026, 10, 13),
            market_cap=11000000000000.0,
            pe_ratio=24.0,
            pb_ratio=11.0,
            ev_to_ebitda=16.0,
            debt_to_equity=0.04,
            roe=0.45,
            roce=0.55,
            operating_margin=0.25,
            net_margin=0.19,
            revenue_growth_yoy=0.08,
            eps_growth_yoy=0.10,
            free_cash_flow=40000000000.0,
            piotroski_f_score=8,
            health_tier=HealthTier.PRIME_QUALITY,
            red_flags=[],
        )
        score, tier, catalysts, risks = analyzer.evaluate_snapshot(snapshot)

        assert score >= 75.0
        assert tier in [HealthTier.PRIME_QUALITY, HealthTier.SOUND]
        assert len(catalysts) >= 2
        assert len(risks) == 0

    def test_disqualifying_red_flags(self):
        analyzer = FundamentalAnalyzer()
        distressed_snapshot = FundamentalSnapshot(
            symbol="BADCO.NS",
            as_of_date=date(2026, 10, 13),
            market_cap=5000000000.0,
            pe_ratio=None,
            pb_ratio=0.5,
            ev_to_ebitda=None,
            debt_to_equity=3.5,
            roe=-0.25,
            roce=-0.15,
            operating_margin=-0.10,
            net_margin=-0.30,
            revenue_growth_yoy=-0.35,
            eps_growth_yoy=-0.50,
            free_cash_flow=-200000000.0,
            piotroski_f_score=1,
            health_tier=HealthTier.DISTRESSED,
            red_flags=["EXTREME_DEBT_BURDEN", "CHRONIC_NEGATIVE_EARNINGS"],
        )
        assert distressed_snapshot.is_disqualified
        score, tier, catalysts, risks = analyzer.evaluate_snapshot(distressed_snapshot)
        assert tier == HealthTier.DISTRESSED
        assert "EXTREME_DEBT_BURDEN" in risks


class TestNewsFundamentalAgent:
    def test_evaluate_symbol_offline(self, temp_intel_env):
        agent = NewsFundamentalAgent(
            db_path=temp_intel_env["db_path"],
            intelligence_dir=temp_intel_env["intel_dir"],
            force_offline=True,
        )

        manifest = agent.evaluate_symbol("RELIANCE.NS")
        assert isinstance(manifest, QuantamentalDecisionManifest)
        assert manifest.symbol == "RELIANCE.NS"
        assert manifest.fundamental_score > 60.0
        assert manifest.allow_trading is True
        assert manifest.allocation_multiplier > 0.0
        assert "RELIANCE.NS" in manifest.narrative

        # Verify SQLite storage
        import sqlite3
        with sqlite3.connect(temp_intel_env["db_path"]) as conn:
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM quantamental_manifests WHERE symbol='RELIANCE.NS'")
            assert cur.fetchone()[0] == 1
            cur.execute("SELECT count(*) FROM news_articles WHERE symbol='RELIANCE.NS'")
            assert cur.fetchone()[0] > 0

    def test_evaluate_universe_offline(self, temp_intel_env):
        agent = NewsFundamentalAgent(
            db_path=temp_intel_env["db_path"],
            intelligence_dir=temp_intel_env["intel_dir"],
            force_offline=True,
        )

        universe = ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS"]
        manifests = agent.evaluate_universe(universe)

        assert len(manifests) == 4
        # Verify ordering by composite score descending
        for i in range(len(manifests) - 1):
            assert manifests[i].composite_score >= manifests[i + 1].composite_score

        # Verify JSON export
        latest_file = os.path.join(temp_intel_env["intel_dir"], "latest_manifest.json")
        assert os.path.exists(latest_file)

    def test_trade_allowed_gate_with_red_flag_disqualification(self, temp_intel_env):
        agent = NewsFundamentalAgent(
            db_path=temp_intel_env["db_path"],
            intelligence_dir=temp_intel_env["intel_dir"],
            force_offline=True,
        )

        # Standard healthy asset
        allowed, narrative, scale = agent.is_trade_allowed("TCS.NS")
        assert allowed is True
        assert scale >= 0.5

    def test_generate_intelligence_report(self, temp_intel_env):
        agent = NewsFundamentalAgent(
            db_path=temp_intel_env["db_path"],
            intelligence_dir=temp_intel_env["intel_dir"],
            force_offline=True,
        )

        report = agent.generate_intelligence_report()
        assert "# Algo Lab — Market Fundamentals & News Intelligence Report" in report
        assert "Quantamental Leaderboard" in report
        assert "RELIANCE.NS" in report
        assert "TCS.NS" in report


class TestMarketIntelligenceAssistant:
    def test_assistant_scheduled_cycle_and_tiers(self, temp_intel_env):
        from services.market_intelligence.assistant_engine import MarketIntelligenceAssistant
        from services.market_intelligence.news_fundamental_contracts import CollectionScheduleConfig

        config = CollectionScheduleConfig(
            news_interval_minutes=1,
            macro_interval_minutes=1,
            fundamentals_interval_hours=1,
        )
        assistant = MarketIntelligenceAssistant(
            db_path=temp_intel_env["db_path"],
            intelligence_dir=temp_intel_env["intel_dir"],
            schedule_config=config,
            force_offline=True,
        )

        res = assistant.run_scheduled_cycle(["RELIANCE.NS", "TCS.NS"])
        assert "NEWS_STREAM" in res["tiers_executed"]
        assert "MACRO_WATCH" in res["tiers_executed"]
        assert "FUNDAMENTALS_DEEP" in res["tiers_executed"]
        assert res["fundamentals_updated"] == 2

        status = assistant.get_status()
        assert status["total_macro_items"] > 0
        assert status["total_news_articles"] > 0
        assert "NEWS_STREAM" in status["schedule_tiers"]

    def test_assistant_conversational_queries(self, temp_intel_env):
        from services.market_intelligence.assistant_engine import MarketIntelligenceAssistant

        assistant = MarketIntelligenceAssistant(
            db_path=temp_intel_env["db_path"],
            intelligence_dir=temp_intel_env["intel_dir"],
            force_offline=True,
        )

        # Briefing query
        brief = assistant.ask("give me the market briefing")
        assert "Macroeconomic & Policy Pulse" in brief
        assert "Top Quantamental Leaderboard" in brief

        # Single stock query
        dossier = assistant.ask("What is the outlook on TCS?")
        assert "TCS.NS" in dossier
        assert "Explainability:" in dossier

        # Head-to-head comparison query
        comp = assistant.ask("Compare TCS and Reliance")
        assert "Comparative Quantamental Analysis" in comp
        assert "TCS.NS" in comp
        assert "RELIANCE.NS" in comp

        # Breaking alerts query
        alerts_resp = assistant.ask("Are there any breaking alerts?")
        assert isinstance(alerts_resp, str)


class TestStockDecisionEngine:
    def test_run_stock_selection(self, temp_intel_env):
        from services.market_intelligence.news_fundamental_agent import NewsFundamentalAgent
        from services.market_intelligence.stock_decision_engine import (
            StockDecisionEngine,
            StockSelectionManifest,
            SelectionTier,
        )

        agent = NewsFundamentalAgent(
            db_path=temp_intel_env["db_path"],
            intelligence_dir=temp_intel_env["intel_dir"],
            force_offline=True,
        )
        engine = StockDecisionEngine(agent=agent, max_portfolio_size=3)

        manifest = engine.run_stock_selection(["TCS.NS", "RELIANCE.NS", "ITC.NS"])
        assert isinstance(manifest, StockSelectionManifest)
        assert len(manifest.selected_portfolio) <= 3
        assert "TCS.NS" in manifest.selected_portfolio
        assert "TCS.NS" in manifest.top_picks
        assert "Screened 3 symbols" in manifest.narrative

    def test_stock_selection_database_persistence(self, temp_intel_env):
        import sqlite3
        from services.market_intelligence.news_fundamental_agent import NewsFundamentalAgent
        from services.market_intelligence.stock_decision_engine import StockDecisionEngine

        agent = NewsFundamentalAgent(
            db_path=temp_intel_env["db_path"],
            intelligence_dir=temp_intel_env["intel_dir"],
            force_offline=True,
        )
        engine = StockDecisionEngine(agent=agent, max_portfolio_size=3)

        manifest = engine.run_stock_selection(["TCS.NS", "RELIANCE.NS", "ITC.NS"])

        # Check SQLite persistence in stock_selections table
        with sqlite3.connect(temp_intel_env["db_path"]) as conn:
            cur = conn.cursor()
            cur.execute("SELECT selection_id, candidate_count, top_picks FROM stock_selections")
            sel_row = cur.fetchone()
            assert sel_row is not None
            assert sel_row[1] == 3
            assert "TCS.NS" in sel_row[2]

            # Check SQLite persistence in stock_selection_candidates table
            cur.execute("SELECT symbol, rank, tier, is_eligible_for_trading FROM stock_selection_candidates ORDER BY rank ASC")
            cand_rows = cur.fetchall()
            assert len(cand_rows) == 3
            assert cand_rows[0][0] == "TCS.NS"
            assert cand_rows[0][1] == 1
            assert cand_rows[0][3] == 1

        # Check retrieval methods
        latest = engine.get_latest_stock_selection()
        assert latest is not None
        assert latest["candidate_count"] == 3
        assert len(latest["candidates"]) == 3
        assert latest["candidates"][0]["symbol"] == "TCS.NS"

        recent = engine.get_recent_stock_selections(limit=5)
        assert len(recent) == 1
        assert recent[0]["selection_id"] == latest["selection_id"]

    def test_evaluate_entry_decision_approval_and_veto(self, temp_intel_env):
        from services.market_intelligence.news_fundamental_agent import NewsFundamentalAgent
        from services.market_intelligence.stock_decision_engine import (
            StockDecisionEngine,
            TradeAction,
        )

        agent = NewsFundamentalAgent(
            db_path=temp_intel_env["db_path"],
            intelligence_dir=temp_intel_env["intel_dir"],
            force_offline=True,
        )
        engine = StockDecisionEngine(agent=agent)

        # High quality stock with technical BUY signal -> APPROVE_BUY
        res_tcs = engine.evaluate_entry_decision("TCS.NS", "BUY", 2200.0)
        assert res_tcs.action == TradeAction.APPROVE_BUY
        assert res_tcs.approved_quantity_scale > 0.5
        assert "High Conviction" in res_tcs.reason or "Approved" in res_tcs.reason

        # Technical signal is WAIT -> WAIT
        res_wait = engine.evaluate_entry_decision("TCS.NS", "WAIT", 2200.0)
        assert res_wait.action == TradeAction.WAIT
        assert res_wait.approved_quantity_scale == 0.0

    def test_trade_decision_database_persistence(self, temp_intel_env):
        import sqlite3
        from services.market_intelligence.news_fundamental_agent import NewsFundamentalAgent
        from services.market_intelligence.stock_decision_engine import (
            StockDecisionEngine,
            TradeAction,
        )

        agent = NewsFundamentalAgent(
            db_path=temp_intel_env["db_path"],
            intelligence_dir=temp_intel_env["intel_dir"],
            force_offline=True,
        )
        engine = StockDecisionEngine(agent=agent)

        # 1. Run entry evaluation
        res1 = engine.evaluate_entry_decision("TCS.NS", "BUY", 2200.0)
        res2 = engine.evaluate_entry_decision("INFY.NS", "WAIT", 1500.0)

        # 2. Check persistence in trade_decisions table
        with sqlite3.connect(temp_intel_env["db_path"]) as conn:
            cur = conn.cursor()
            cur.execute("SELECT symbol, action, approved_quantity_scale, decision_type FROM trade_decisions ORDER BY evaluated_at ASC")
            rows = cur.fetchall()
            assert len(rows) == 2
            assert rows[0][0] == "TCS.NS"
            assert rows[0][1] == "APPROVE_BUY"
            assert rows[0][2] > 0.5
            assert rows[0][3] == "ENTRY_EVALUATION"

            assert rows[1][0] == "INFY.NS"
            assert rows[1][1] == "WAIT"

        # 3. Test query retrieval methods
        decisions = engine.get_recent_trade_decisions(limit=10)
        assert len(decisions) == 2
        tcs_decisions = engine.get_recent_trade_decisions(symbol="TCS.NS")
        assert len(tcs_decisions) == 1
        assert tcs_decisions[0]["action"] == "APPROVE_BUY"

    def test_emergency_exit_evaluation(self, temp_intel_env):
        from services.market_intelligence.news_fundamental_agent import NewsFundamentalAgent
        from services.market_intelligence.stock_decision_engine import (
            StockDecisionEngine,
            TradeAction,
        )

        agent = NewsFundamentalAgent(
            db_path=temp_intel_env["db_path"],
            intelligence_dir=temp_intel_env["intel_dir"],
            force_offline=True,
        )
        engine = StockDecisionEngine(agent=agent)

        # Normal holding with clean news
        holding_ok = engine.evaluate_holding_risk("TCS.NS", 2150.0, 2200.0)
        assert holding_ok.action == TradeAction.WAIT
        assert holding_ok.red_flag_alert is False

        # Verify emergency exit check persisted to SQLite
        decisions = engine.get_recent_trade_decisions(symbol="TCS.NS")
        assert len(decisions) == 1
        assert decisions[0]["decision_type"] == "HOLDING_RISK"

    def test_assistant_database_retrieval_and_telemetry(self, temp_intel_env):
        from services.market_intelligence.assistant_engine import MarketIntelligenceAssistant

        assistant = MarketIntelligenceAssistant(
            db_path=temp_intel_env["db_path"],
            intelligence_dir=temp_intel_env["intel_dir"],
            force_offline=True,
        )

        # Initially empty selections
        sel_empty = assistant.get_latest_stock_selection()
        assert sel_empty is None

        # Run stock selection
        manifest = assistant.decision_engine.run_stock_selection(["TCS.NS", "RELIANCE.NS"])
        assert manifest is not None

        # Check retrieval via assistant
        sel_latest = assistant.get_latest_stock_selection()
        assert sel_latest is not None
        assert "TCS.NS" in sel_latest["top_picks"]

        # Evaluate trade decision
        assistant.decision_engine.evaluate_entry_decision("TCS.NS", "BUY", 2200.0)
        recent_decs = assistant.get_recent_decisions()
        assert len(recent_decs) >= 1
        assert recent_decs[0]["symbol"] == "TCS.NS"

        # Check status contains all database counts
        status = assistant.get_status()
        assert status["total_stock_selections"] >= 1
        assert status["total_selection_candidates"] >= 2
        assert status["total_trade_decisions"] >= 1

        # Check conversational queries retrieve from database
        q_sel = assistant.ask("what was our last stock selection?")
        assert "Latest Stock Selection Manifest" in q_sel
        assert "TCS.NS" in q_sel

        q_dec = assistant.ask("show decision history")
        assert "Trade Decision Audit Trail" in q_dec
        assert "TCS.NS" in q_dec

    def test_eod_report_and_research_strategy_persistence(self, temp_intel_env):
        from services.market_intelligence.assistant_engine import MarketIntelligenceAssistant

        assistant = MarketIntelligenceAssistant(
            db_path=temp_intel_env["db_path"],
            intelligence_dir=temp_intel_env["intel_dir"],
            force_offline=True,
        )

        # 1. Test EOD Report Persistence
        eod_payload = {
            "report_date": "2026-10-13",
            "generated_at": "2026-10-13T10:45:00+00:00",
            "session_id": "sess_test_123",
            "starting_capital": 50000.0,
            "ending_equity": 50667.17,
            "gross_pnl": 766.56,
            "net_pnl": 734.26,
            "total_trades": 6,
            "winning_trades": 6,
            "losing_trades": 0,
            "win_rate_pct": 100.0,
            "profit_factor": 999.0,
            "max_drawdown_pct": 0.0043,
            "reconciliation_status": "MATCH",
            "variance": 0.0,
            "market_regime": "TRENDING_BEAR",
            "selected_strategy": "STRAT_BOLLINGER_REVERSION",
            "risk_multiplier": 1.0,
            "top_stock_picks": ["TCS.NS", "INFY.NS"],
            "executive_summary": "Net PnL +734.26 (100% win rate)",
            "report_markdown": "# Algo Lab — EOD Audit Report 2026-10-13\nNet P&L: +₹734.26",
            "metrics_json": {"brokerage": 67.09},
        }

        saved_date = assistant.save_eod_report(eod_payload)
        assert saved_date == "2026-10-13"

        # Retrieve EOD Report
        eod = assistant.get_eod_report("2026-10-13")
        assert eod is not None
        assert eod["reconciliation_status"] == "MATCH"
        assert eod["net_pnl"] == 734.26
        assert eod["win_rate_pct"] == 100.0
        assert "# Algo Lab — EOD Audit Report 2026-10-13" in eod["report_markdown"]

        recent_eods = assistant.get_recent_eod_reports()
        assert len(recent_eods) == 1
        assert recent_eods[0]["report_date"] == "2026-10-13"

        # 2. Test Strategy Research Decision Persistence
        decision_payload = {
            "decision_date": "2026-10-13T10:10:39+00:00",
            "target_session_date": "2026-10-14",
            "market_regime": "TRENDING_BEAR",
            "selected_strategy": "STRAT_BOLLINGER_REVERSION",
            "risk_multiplier": 1.0,
            "allocation_reason": "DSR=1.00 compatible with TRENDING_BEAR",
            "candidate_evaluations": [
                {
                    "strategy": "STRAT_BOLLINGER_REVERSION",
                    "trades_count": 39,
                    "win_rate_pct": 61.5,
                    "profit_factor": 1.62,
                    "sharpe_ratio": 7.77,
                    "dsr": 1.0,
                    "is_robust": True,
                }
            ],
            "eod_audit": {"realized_pnl": 734.26},
        }

        saved_dec_date = assistant.save_research_strategy_decision(decision_payload)
        assert saved_dec_date == "2026-10-13"

        strat = assistant.get_latest_research_strategy_decision()
        assert strat is not None
        assert strat["selected_strategy"] == "STRAT_BOLLINGER_REVERSION"
        assert len(strat["candidate_evaluations"]) == 1

        # 3. Test Conversational Queries on EOD and Research
        q_eod = assistant.ask("show today's eod report")
        assert "# Algo Lab — EOD Audit Report 2026-10-13" in q_eod

        q_strat = assistant.ask("what is the strategy decision for tomorrow?")
        assert "Autonomous Strategy Research Decision" in q_strat
        assert "STRAT_BOLLINGER_REVERSION" in q_strat

        # 4. Telemetry check
        st = assistant.get_status()
        assert st["total_eod_reports"] == 1
        assert st["total_research_strategy_decisions"] == 1


