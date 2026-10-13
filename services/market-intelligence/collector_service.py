"""
Algo Lab — Financial News & Fundamentals Ingestion & Collector Services
Fetches real-time RSS market news and fundamental equity metrics with point-in-time
lookahead protection, robust error handling, caching, and deterministic offline fallbacks.
"""

import hashlib
import json
import logging
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, date, timedelta
from typing import Dict, Any, List, Optional, Tuple

import yfinance as yf

from services.market_intelligence.news_fundamental_contracts import (
    NewsItem,
    NewsUrgency,
    NewsCategory,
    SentimentLabel,
    FundamentalSnapshot,
    HealthTier,
    MacroNewsItem,
    CorporateCalendarEvent,
    AnalystConsensus,
)
from services.market_intelligence.sentiment_engine import FinancialSentimentAnalyzer

logger = logging.getLogger("NewsFundamentalCollector")

# Deterministic fundamental baseline fixtures for core NSE universe
BENCHMARK_FUNDAMENTAL_FIXTURES: Dict[str, Dict[str, Any]] = {
    "RELIANCE.NS": {
        "market_cap": 15800000000000.0,
        "pe_ratio": 21.0,
        "pb_ratio": 1.75,
        "ev_to_ebitda": 11.2,
        "debt_to_equity": 0.46,
        "roe": 0.14,
        "roce": 0.12,
        "operating_margin": 0.123,
        "net_margin": 0.082,
        "revenue_growth_yoy": 0.297,
        "eps_growth_yoy": 0.15,
        "free_cash_flow": 125000000000.0,
        "piotroski_f_score": 7,
        "health_tier": HealthTier.PRIME_QUALITY,
        "red_flags": [],
    },
    "TCS.NS": {
        "market_cap": 11200000000000.0,
        "pe_ratio": 24.5,
        "pb_ratio": 12.1,
        "ev_to_ebitda": 17.5,
        "debt_to_equity": 0.05,
        "roe": 0.48,
        "roce": 0.59,
        "operating_margin": 0.252,
        "net_margin": 0.198,
        "revenue_growth_yoy": 0.065,
        "eps_growth_yoy": 0.082,
        "free_cash_flow": 42000000000.0,
        "piotroski_f_score": 8,
        "health_tier": HealthTier.PRIME_QUALITY,
        "red_flags": [],
    },
    "INFY.NS": {
        "market_cap": 6100000000000.0,
        "pe_ratio": 22.8,
        "pb_ratio": 7.8,
        "ev_to_ebitda": 15.2,
        "debt_to_equity": 0.08,
        "roe": 0.31,
        "roce": 0.39,
        "operating_margin": 0.211,
        "net_margin": 0.165,
        "revenue_growth_yoy": 0.058,
        "eps_growth_yoy": 0.069,
        "free_cash_flow": 23000000000.0,
        "piotroski_f_score": 7,
        "health_tier": HealthTier.PRIME_QUALITY,
        "red_flags": [],
    },
    "HDFCBANK.NS": {
        "market_cap": 12500000000000.0,
        "pe_ratio": 17.8,
        "pb_ratio": 2.6,
        "ev_to_ebitda": None,
        "debt_to_equity": None,  # Bank
        "roe": 0.165,
        "roce": 0.158,
        "operating_margin": 0.38,
        "net_margin": 0.22,
        "revenue_growth_yoy": 0.18,
        "eps_growth_yoy": 0.14,
        "free_cash_flow": None,
        "piotroski_f_score": 7,
        "health_tier": HealthTier.SOUND,
        "red_flags": [],
    },
    "ICICIBANK.NS": {
        "market_cap": 8700000000000.0,
        "pe_ratio": 16.9,
        "pb_ratio": 2.9,
        "ev_to_ebitda": None,
        "debt_to_equity": None,  # Bank
        "roe": 0.185,
        "roce": 0.172,
        "operating_margin": 0.41,
        "net_margin": 0.24,
        "revenue_growth_yoy": 0.21,
        "eps_growth_yoy": 0.19,
        "free_cash_flow": None,
        "piotroski_f_score": 8,
        "health_tier": HealthTier.PRIME_QUALITY,
        "red_flags": [],
    },
    "SBIN.NS": {
        "market_cap": 7100000000000.0,
        "pe_ratio": 10.5,
        "pb_ratio": 1.45,
        "ev_to_ebitda": None,
        "debt_to_equity": None,  # Bank
        "roe": 0.168,
        "roce": 0.145,
        "operating_margin": 0.32,
        "net_margin": 0.17,
        "revenue_growth_yoy": 0.14,
        "eps_growth_yoy": 0.16,
        "free_cash_flow": None,
        "piotroski_f_score": 7,
        "health_tier": HealthTier.SOUND,
        "red_flags": [],
    },
    "BHARTIARTL.NS": {
        "market_cap": 9800000000000.0,
        "pe_ratio": 42.0,
        "pb_ratio": 7.4,
        "ev_to_ebitda": 11.8,
        "debt_to_equity": 1.45,
        "roe": 0.192,
        "roce": 0.148,
        "operating_margin": 0.235,
        "net_margin": 0.088,
        "revenue_growth_yoy": 0.135,
        "eps_growth_yoy": 0.32,
        "free_cash_flow": 38000000000.0,
        "piotroski_f_score": 6,
        "health_tier": HealthTier.SOUND,
        "red_flags": [],
    },
    "ITC.NS": {
        "market_cap": 5800000000000.0,
        "pe_ratio": 26.2,
        "pb_ratio": 7.1,
        "ev_to_ebitda": 18.2,
        "debt_to_equity": 0.01,
        "roe": 0.29,
        "roce": 0.37,
        "operating_margin": 0.362,
        "net_margin": 0.278,
        "revenue_growth_yoy": 0.075,
        "eps_growth_yoy": 0.089,
        "free_cash_flow": 16000000000.0,
        "piotroski_f_score": 8,
        "health_tier": HealthTier.PRIME_QUALITY,
        "red_flags": [],
    },
}

# Deterministic simulated news headlines for offline/air-gapped execution
OFFLINE_NEWS_FIXTURES: Dict[str, List[Dict[str, str]]] = {
    "RELIANCE.NS": [
        {"title": "Reliance Q2 Results Beat Expectations with 15% EBITDA Growth across Retail and Telecom", "source": "Economic Times"},
        {"title": "Jio Financial and BlackRock joint venture receives SEBI approval for mutual fund operations", "source": "LiveMint"},
        {"title": "Reliance Industries expands green hydrogen capacity with new solar gigafactory investment", "source": "Moneycontrol"},
    ],
    "TCS.NS": [
        {"title": "TCS bags mega multi-billion dollar digital transformation contract from European banking client", "source": "Business Standard"},
        {"title": "TCS announces record dividend hike of 25% following strong quarterly operational margins", "source": "Economic Times"},
        {"title": "Brokerages maintain Buy on TCS citing sustained deal wins and AI infrastructure momentum", "source": "CNBC-TV18"},
    ],
    "INFY.NS": [
        {"title": "Infosys secures cloud modernization deal with global logistics leader, raises lower band of guidance", "source": "LiveMint"},
        {"title": "FII buying observed in Infosys as large deal total contract value hits multi-quarter high", "source": "Financial Express"},
    ],
    "HDFCBANK.NS": [
        {"title": "HDFC Bank net profit rises 16% YoY on steady loan growth and asset quality improvement", "source": "Moneycontrol"},
        {"title": "HDFC Bank completes deposit accretion milestone post-merger with robust CASA ratio", "source": "Economic Times"},
    ],
    "ICICIBANK.NS": [
        {"title": "ICICI Bank delivers industry-leading ROE of 18.5% with pristine asset quality in retail book", "source": "Business Standard"},
        {"title": "Analysts upgrade ICICI Bank target price following strong NIM stability and loan book growth", "source": "LiveMint"},
    ],
    "SBIN.NS": [
        {"title": "State Bank of India reports all-time high quarterly profit on declining gross NPA levels", "source": "Financial Express"},
        {"title": "SBI credit growth outpaces market expectations driven by infrastructure corporate lending", "source": "Economic Times"},
    ],
    "BHARTIARTL.NS": [
        {"title": "Bharti Airtel ARPU rises to record INR 215 as 5G subscriber conversions accelerate", "source": "LiveMint"},
        {"title": "Airtel Africa debt reduced significantly, boosting parent company consolidated balance sheet", "source": "Moneycontrol"},
    ],
    "ITC.NS": [
        {"title": "ITC shares maintain steady uptrend as FMCG margin expansion offsets commodity headwinds", "source": "Economic Times"},
        {"title": "ITC hotel business demerger receives final shareholder approval, unlocking shareholder value", "source": "Business Standard"},
    ],
}


SYMBOL_ALIASES: Dict[str, List[str]] = {
    "RELIANCE.NS": ["reliance", "ril", "jio"],
    "TCS.NS": ["tcs", "tata consultancy"],
    "INFY.NS": ["infosys", "infy"],
    "HDFCBANK.NS": ["hdfc bank", "hdfcbank", "hdfc"],
    "ICICIBANK.NS": ["icici bank", "icicibank", "icici"],
    "SBIN.NS": ["state bank of india", "sbi", "sbin"],
    "BHARTIARTL.NS": ["bharti airtel", "airtel", "bharti"],
    "ITC.NS": ["itc"],
}

MULTI_SOURCE_FEEDS: List[Tuple[str, str]] = [
    ("Economic Times", "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms"),
    ("Moneycontrol", "https://www.moneycontrol.com/rss/MCtopnews.xml"),
    ("LiveMint", "https://www.livemint.com/rss/markets"),
]


class NewsCollector:
    """Ingests, cleans, and scores financial news items with point-in-time provenance."""

    def __init__(
        self,
        sentiment_analyzer: Optional[FinancialSentimentAnalyzer] = None,
        force_offline: bool = False,
        cache_dir: str = "/home/ubuntu/algopro/data/intelligence/cache",
    ):
        self.sentiment_analyzer = sentiment_analyzer or FinancialSentimentAnalyzer()
        self.force_offline = force_offline
        self.cache_dir = cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)

    def fetch_symbol_news(
        self,
        symbol: str,
        limit: int = 15,
        as_of_time: Optional[datetime] = None,
    ) -> List[NewsItem]:
        """
        Fetches news items for a given equity symbol across multiple sources:
        Google News, Economic Times, Moneycontrol, and LiveMint.
        Strictly enforces INV-26 (published_at <= as_of_time).
        """
        ref_time = as_of_time or datetime.now(timezone.utc)
        sym_clean = symbol.replace(".NS", "").replace(".BO", "")
        items: List[NewsItem] = []

        if not self.force_offline:
            try:
                items = self._fetch_live_rss(symbol, sym_clean, limit, ref_time)
            except Exception as e:
                logger.warning(f"Live news fetch failed for {symbol}: {e}. Engaging offline fallback.")

        if not items:
            items = self._fetch_offline_fixtures(symbol, sym_clean, ref_time)

        # Enforce point-in-time lookahead safety (INV-26)
        valid_items = [item for item in items if item.is_eligible_at(ref_time)]
        # Sort newest first
        valid_items.sort(key=lambda x: x.published_at, reverse=True)
        return valid_items[:limit]

    def _fetch_live_rss(
        self,
        symbol: str,
        sym_clean: str,
        limit: int,
        ref_time: datetime,
    ) -> List[NewsItem]:
        items: List[NewsItem] = []
        seen_titles = set()
        aliases = [a.lower() for a in SYMBOL_ALIASES.get(symbol, [sym_clean.lower()])]

        # 1. Primary Source: Targeted Google News search for symbol
        query = urllib.parse.quote(f"{sym_clean} share price NSE")
        url = f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
        self._scrape_feed(url, "Google News (India)", symbol, ref_time, items, seen_titles, limit, match_aliases=None)

        # 2. Secondary Sources: Financial Press Feeds (Economic Times, Moneycontrol, LiveMint)
        if len(items) < limit:
            for source_name, feed_url in MULTI_SOURCE_FEEDS:
                try:
                    self._scrape_feed(feed_url, source_name, symbol, ref_time, items, seen_titles, limit, match_aliases=aliases)
                    if len(items) >= limit:
                        break
                except Exception as e:
                    logger.debug(f"Feed error on {source_name}: {e}")

        return items

    def _scrape_feed(
        self,
        url: str,
        source_label: str,
        symbol: str,
        ref_time: datetime,
        items: List[NewsItem],
        seen_titles: set,
        limit: int,
        match_aliases: Optional[List[str]] = None,
    ):
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            content = resp.read()
            root = ET.fromstring(content)
            for item_elem in root.findall(".//item"):
                title_elem = item_elem.find("title")
                pub_elem = item_elem.find("pubDate")
                link_elem = item_elem.find("link")
                source_elem = item_elem.find("source")

                if title_elem is None or title_elem.text is None:
                    continue

                title = title_elem.text.strip()
                t_lower = title.lower()

                # If alias filtering is active, only include headlines mentioning the company
                if match_aliases and not any(re.search(rf"\b{re.escape(alias)}\b", t_lower) for alias in match_aliases):
                    continue

                if t_lower in seen_titles:
                    continue
                seen_titles.add(t_lower)

                link = link_elem.text.strip() if link_elem is not None and link_elem.text else None
                source = source_elem.text.strip() if source_elem is not None and source_elem.text else source_label

                pub_dt = self._parse_pub_date(pub_elem.text if pub_elem is not None else None, ref_time)
                if pub_dt > ref_time:
                    continue

                article_id = hashlib.sha256(f"{symbol}_{title}_{pub_dt.isoformat()}".encode("utf-8")).hexdigest()[:16]
                score, label, conf, cat, urg = self.sentiment_analyzer.analyze_text(title)

                items.append(NewsItem(
                    article_id=article_id,
                    symbol=symbol,
                    title=title,
                    summary=title,
                    source=source,
                    published_at=pub_dt,
                    ingested_at=datetime.now(timezone.utc),
                    url=link,
                    sentiment_score=score,
                    sentiment_label=label,
                    confidence=conf,
                    urgency=urg,
                    category=cat,
                ))

                if len(items) >= limit:
                    break

    def fetch_macro_news(
        self,
        limit: int = 15,
        as_of_time: Optional[datetime] = None,
    ) -> List[MacroNewsItem]:
        """Fetches broader macroeconomic news (RBI, inflation, bond yields, Nifty sentiment)."""
        ref_time = as_of_time or datetime.now(timezone.utc)
        macro_items: List[MacroNewsItem] = []
        seen = set()

        if not self.force_offline:
            try:
                query = urllib.parse.quote("RBI repo rate inflation monetary policy Indian economy Nifty")
                url = f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=4.0) as resp:
                    root = ET.fromstring(resp.read())
                    for item_elem in root.findall(".//item")[:limit * 2]:
                        title_elem = item_elem.find("title")
                        pub_elem = item_elem.find("pubDate")
                        link_elem = item_elem.find("link")
                        source_elem = item_elem.find("source")

                        if title_elem is None or not title_elem.text:
                            continue
                        title = title_elem.text.strip()
                        if title.lower() in seen:
                            continue
                        seen.add(title.lower())

                        pub_dt = self._parse_pub_date(pub_elem.text if pub_elem is not None else None, ref_time)
                        if pub_dt > ref_time:
                            continue

                        item_id = hashlib.sha256(f"MACRO_{title}_{pub_dt.isoformat()}".encode("utf-8")).hexdigest()[:16]
                        score, _, _, _, _ = self.sentiment_analyzer.analyze_text(title)

                        # Determine macro theme
                        t_lower = title.lower()
                        if any(w in t_lower for w in ["rbi", "repo", "monetary policy", "interest rate"]):
                            theme = "MONETARY_POLICY"
                        elif any(w in t_lower for w in ["inflation", "cpi", "wpi", "price rise"]):
                            theme = "INFLATION"
                        elif any(w in t_lower for w in ["fii", "dii", "foreign flow", "outflow"]):
                            theme = "FII_FLOWS"
                        else:
                            theme = "MACRO_GROWTH"

                        source = source_elem.text.strip() if source_elem is not None and source_elem.text else "Financial Press"
                        link = link_elem.text.strip() if link_elem is not None and link_elem.text else None

                        macro_items.append(MacroNewsItem(
                            item_id=item_id,
                            headline=title,
                            source=source,
                            published_at=pub_dt,
                            sentiment_score=score,
                            theme=theme,
                            url=link,
                        ))
                        if len(macro_items) >= limit:
                            break
            except Exception as e:
                logger.warning(f"Live macro news fetch failed: {e}")

        if not macro_items:
            # Deterministic offline macro fixtures
            defaults = [
                ("RBI leaves repo rate unchanged at 6.50% citing resilient domestic economic expansion", "LiveMint", "MONETARY_POLICY", 0.4),
                ("India CPI inflation remains within tolerance band as food prices stabilize", "Economic Times", "INFLATION", 0.35),
                ("FII inflows accelerate into domestic large-cap equities amid strong economic outlook", "Moneycontrol", "FII_FLOWS", 0.6),
            ]
            for i, (head, src, th, sc) in enumerate(defaults):
                dt = ref_time - timedelta(hours=i * 3 + 1)
                macro_items.append(MacroNewsItem(
                    item_id=f"MACRO_OFFLINE_{i}",
                    headline=head,
                    source=src,
                    published_at=dt,
                    sentiment_score=sc,
                    theme=th,
                ))

        macro_items.sort(key=lambda x: x.published_at, reverse=True)
        return macro_items[:limit]


    def _fetch_offline_fixtures(self, symbol: str, sym_clean: str, ref_time: datetime) -> List[NewsItem]:
        raw_list = OFFLINE_NEWS_FIXTURES.get(symbol, [
            {"title": f"{sym_clean} trading steady with normal institutional volumes on NSE", "source": "Market Wire"}
        ])

        items: List[NewsItem] = []
        for i, item_dict in enumerate(raw_list):
            title = item_dict["title"]
            source = item_dict["source"]
            # Generate deterministic publication timestamp within past 24 hours
            pub_dt = ref_time - timedelta(hours=(i * 4 + 1))
            article_id = hashlib.sha256(f"{symbol}_{title}_{pub_dt.isoformat()}".encode("utf-8")).hexdigest()[:16]

            score, label, conf, cat, urg = self.sentiment_analyzer.analyze_text(title)

            items.append(NewsItem(
                article_id=article_id,
                symbol=symbol,
                title=title,
                summary=title,
                source=source,
                published_at=pub_dt,
                ingested_at=ref_time,
                url=None,
                sentiment_score=score,
                sentiment_label=label,
                confidence=conf,
                urgency=urg,
                category=cat,
            ))

        return items

    def _parse_pub_date(self, date_str: Optional[str], default_dt: datetime) -> datetime:
        if not date_str:
            return default_dt
        # Format: Sat, 10 Oct 2026 22:12:16 GMT
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(date_str)
            return dt.astimezone(timezone.utc)
        except Exception:
            return default_dt


class FundamentalCollector:
    """Ingests and calculates fundamental metrics for equities."""

    def __init__(self, force_offline: bool = False):
        self.force_offline = force_offline

    def fetch_fundamental_snapshot(
        self,
        symbol: str,
        as_of_date: Optional[date] = None,
    ) -> FundamentalSnapshot:
        """
        Fetches fundamental snapshot for a symbol.
        Leverages yfinance when online, falling back seamlessly to institutional fixtures.
        """
        eval_date = as_of_date or date.today()
        fixture = BENCHMARK_FUNDAMENTAL_FIXTURES.get(symbol)

        if self.force_offline or fixture is None:
            if fixture:
                return self._create_snapshot_from_fixture(symbol, eval_date, fixture)

        # Try live yfinance fetch
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            if info and len(info) > 10:
                return self._create_snapshot_from_yfinance(symbol, eval_date, info, fixture)
        except Exception as e:
            logger.warning(f"Live fundamental fetch for {symbol} failed: {e}. Using benchmark fixture.")

        if fixture:
            return self._create_snapshot_from_fixture(symbol, eval_date, fixture)

        # Default fallback if unknown symbol and offline
        return FundamentalSnapshot(
            symbol=symbol,
            as_of_date=eval_date,
            market_cap=50000000000.0,
            pe_ratio=20.0,
            pb_ratio=2.5,
            ev_to_ebitda=12.0,
            debt_to_equity=0.5,
            roe=0.12,
            roce=0.10,
            operating_margin=0.12,
            net_margin=0.08,
            revenue_growth_yoy=0.05,
            eps_growth_yoy=0.05,
            free_cash_flow=1000000000.0,
            piotroski_f_score=5,
            health_tier=HealthTier.AVERAGE,
            red_flags=[],
        )

    def _create_snapshot_from_yfinance(
        self,
        symbol: str,
        eval_date: date,
        info: Dict[str, Any],
        fixture: Optional[Dict[str, Any]],
    ) -> FundamentalSnapshot:
        pe = info.get("trailingPE") or (fixture.get("pe_ratio") if fixture else None)
        pb = info.get("priceToBook") or (fixture.get("pb_ratio") if fixture else None)
        de = info.get("debtToEquity")
        if de is not None:
            de = de / 100.0 if de > 5.0 else de  # Convert percentage to ratio if needed
        elif fixture:
            de = fixture.get("debt_to_equity")

        roe = info.get("returnOnEquity") or (fixture.get("roe") if fixture else 0.12)
        op_margin = info.get("operatingMargins") or (fixture.get("operating_margin") if fixture else 0.15)
        net_margin = info.get("profitMargins") or (fixture.get("net_margin") if fixture else 0.10)
        rev_growth = info.get("revenueGrowth") or (fixture.get("revenue_growth_yoy") if fixture else 0.08)
        mcap = info.get("marketCap") or (fixture.get("market_cap") if fixture else 100000000000.0)

        red_flags: List[str] = []
        is_bank = "BANK" in symbol.upper() or "FIN" in symbol.upper()
        if not is_bank and de is not None and de > 2.5:
            red_flags.append("EXTREME_DEBT_BURDEN")
        if roe is not None and roe < -0.05 and op_margin is not None and op_margin < 0:
            red_flags.append("CHRONIC_NEGATIVE_EARNINGS")
        if rev_growth is not None and rev_growth < -0.20:
            red_flags.append("SEVERE_REVENUE_CONTRACTION")

        f_score = fixture.get("piotroski_f_score", 6) if fixture else 6

        return FundamentalSnapshot(
            symbol=symbol,
            as_of_date=eval_date,
            market_cap=float(mcap),
            pe_ratio=float(pe) if pe else None,
            pb_ratio=float(pb) if pb else None,
            ev_to_ebitda=float(info.get("enterpriseToEbitda")) if info.get("enterpriseToEbitda") else (fixture.get("ev_to_ebitda") if fixture else None),
            debt_to_equity=float(de) if de is not None else None,
            roe=float(roe) if roe else None,
            roce=fixture.get("roce") if fixture else (float(roe) * 1.1 if roe else None),
            operating_margin=float(op_margin) if op_margin else None,
            net_margin=float(net_margin) if net_margin else None,
            revenue_growth_yoy=float(rev_growth) if rev_growth else None,
            eps_growth_yoy=fixture.get("eps_growth_yoy", 0.08) if fixture else None,
            free_cash_flow=float(info.get("freeCashflow")) if info.get("freeCashflow") else (fixture.get("free_cash_flow") if fixture else None),
            piotroski_f_score=f_score,
            health_tier=fixture.get("health_tier", HealthTier.SOUND) if fixture else HealthTier.SOUND,
            red_flags=red_flags,
        )

    def _create_snapshot_from_fixture(
        self,
        symbol: str,
        eval_date: date,
        fix: Dict[str, Any],
    ) -> FundamentalSnapshot:
        return FundamentalSnapshot(
            symbol=symbol,
            as_of_date=eval_date,
            market_cap=fix["market_cap"],
            pe_ratio=fix["pe_ratio"],
            pb_ratio=fix["pb_ratio"],
            ev_to_ebitda=fix["ev_to_ebitda"],
            debt_to_equity=fix["debt_to_equity"],
            roe=fix["roe"],
            roce=fix["roce"],
            operating_margin=fix["operating_margin"],
            net_margin=fix["net_margin"],
            revenue_growth_yoy=fix["revenue_growth_yoy"],
            eps_growth_yoy=fix["eps_growth_yoy"],
            free_cash_flow=fix["free_cash_flow"],
            piotroski_f_score=fix["piotroski_f_score"],
            health_tier=fix["health_tier"],
            red_flags=list(fix["red_flags"]),
        )

    def fetch_corporate_calendar(self, symbol: str) -> List[CorporateCalendarEvent]:
        """Fetches upcoming earnings release dates and corporate events."""
        events: List[CorporateCalendarEvent] = []
        if self.force_offline:
            return events
        try:
            ticker = yf.Ticker(symbol)
            cal = ticker.calendar
            if isinstance(cal, dict):
                for k, v in cal.items():
                    val_str = str(v) if v is not None else ""
                    events.append(CorporateCalendarEvent(
                        symbol=symbol,
                        event_type="CALENDAR_EVENT",
                        event_date=val_str,
                        description=f"{k}: {val_str}",
                    ))
        except Exception as e:
            logger.debug(f"Calendar fetch failed for {symbol}: {e}")
        return events

    def fetch_analyst_consensus(self, symbol: str) -> AnalystConsensus:
        """Fetches Wall Street & institutional analyst target prices and consensus recommendations."""
        if self.force_offline:
            return AnalystConsensus(
                symbol=symbol,
                target_mean=None,
                target_high=None,
                target_low=None,
                current_price=None,
                upside_potential_pct=None,
                recommendation_key="none",
                number_of_analysts=None,
            )
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info or {}
            target_mean = info.get("targetMeanPrice")
            target_high = info.get("targetHighPrice")
            target_low = info.get("targetLowPrice")
            current_price = info.get("currentPrice") or info.get("regularMarketPrice")
            rec_key = info.get("recommendationKey", "hold")
            num_analysts = info.get("numberOfAnalystOpinions")

            upside = None
            if target_mean and current_price and current_price > 0:
                upside = round(((target_mean - current_price) / current_price) * 100.0, 1)

            return AnalystConsensus(
                symbol=symbol,
                target_mean=float(target_mean) if target_mean else None,
                target_high=float(target_high) if target_high else None,
                target_low=float(target_low) if target_low else None,
                current_price=float(current_price) if current_price else None,
                upside_potential_pct=upside,
                recommendation_key=str(rec_key),
                number_of_analysts=int(num_analysts) if num_analysts else None,
            )
        except Exception as e:
            logger.debug(f"Analyst consensus fetch failed for {symbol}: {e}")
            return AnalystConsensus(
                symbol=symbol,
                target_mean=None,
                target_high=None,
                target_low=None,
                current_price=None,
                upside_potential_pct=None,
                recommendation_key="unknown",
                number_of_analysts=None,
            )

