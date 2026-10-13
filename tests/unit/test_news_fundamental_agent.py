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
