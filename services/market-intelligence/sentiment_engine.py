"""
Algo Lab — Financial NLP Sentiment Analysis & News Classification Engine
Provides domain-tuned financial dictionary scoring, negation detection,
urgency classification, and exponential recency decay aggregation.
"""

import math
import re
from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple, Optional

from services.market_intelligence.news_fundamental_contracts import (
    NewsItem,
    SentimentLabel,
    NewsUrgency,
    NewsCategory,
)

# Domain-specific financial dictionary with polarity weights [-1.0, +1.0]
FINANCIAL_LEXICON = {
    # High Bullish (+0.8 to +1.0)
    "record profit": 1.0,
    "all-time high": 0.8,
    "blowout earnings": 1.0,
    "beats estimates": 0.9,
    "beat expectations": 0.9,
    "strong buy": 0.9,
    "upgrade": 0.75,
    "multi-year high": 0.8,
    "dividend hike": 0.85,
    "special dividend": 0.85,
    "bonus issue": 0.8,
    "debt free": 0.95,
    "order win": 0.85,
    "bagged contract": 0.85,
    "cleared by sebi": 0.9,
    "clean chit": 0.85,
    "acquisition approved": 0.75,
    "ebitda expansion": 0.8,
    "margin expansion": 0.85,
    "robust growth": 0.8,
    "fii buying": 0.75,
    "fii inflow": 0.75,

    # Moderate Bullish (+0.3 to +0.7)
    "profit rises": 0.6,
    "revenue up": 0.55,
    "growth": 0.4,
    "expansion": 0.5,
    "rally": 0.5,
    "outperform": 0.65,
    "bullish": 0.6,
    "gain": 0.35,
    "surge": 0.6,
    "optimistic": 0.45,
    "partner": 0.4,
    "launch": 0.35,
    "turnaround": 0.65,
    "positive": 0.4,
    "recovery": 0.5,

    # High Bearish (-0.8 to -1.0)
    "accounting fraud": -1.0,
    "sebi probe": -0.95,
    "cbi raid": -1.0,
    "ed raid": -1.0,
    "default": -1.0,
    "insolvency": -1.0,
    "bankruptcy": -1.0,
    "promoter pledge": -0.85,
    "pledged shares invoked": -0.95,
    "auditor resigns": -0.95,
    "earnings miss": -0.85,
    "misses estimates": -0.85,
    "profit plunges": -0.9,
    "slashes guidance": -0.9,
    "downgrade": -0.8,
    "penalty imposed": -0.85,
    "legal action": -0.75,
    "heavy loss": -0.85,
    "strike": -0.7,
    "fii selling": -0.75,
    "margin compression": -0.8,

    # Moderate Bearish (-0.3 to -0.7)
    "profit falls": -0.6,
    "revenue down": -0.55,
    "slump": -0.6,
    "decline": -0.4,
    "drop": -0.35,
    "bearish": -0.6,
    "underperform": -0.65,
    "selloff": -0.65,
    "headwinds": -0.5,
    "concerns": -0.45,
    "warning": -0.55,
    "layoffs": -0.5,
    "weak": -0.4,
    "cautious": -0.3,
    "slowdown": -0.5,
}

NEGATION_TERMS = {"not", "no", "never", "without", "hardly", "barely", "fails to", "failed to"}


class FinancialSentimentAnalyzer:
    """Specialized NLP Sentiment Analyzer for financial headlines and corporate news."""

    def __init__(self, lexicon: Optional[Dict[str, float]] = None):
        self.lexicon = lexicon or FINANCIAL_LEXICON

    def analyze_text(self, text: str) -> Tuple[float, SentimentLabel, float, NewsCategory, NewsUrgency]:
        """
        Analyzes a piece of financial news text (title + summary).
        Returns:
            sentiment_score: float [-1.0, 1.0]
            sentiment_label: SentimentLabel
            confidence: float [0.0, 1.0]
            category: NewsCategory
            urgency: NewsUrgency
        """
        clean_text = text.lower()
        words = re.findall(r"\b[a-z0-9\-]+\b", clean_text)

        score = 0.0
        matches = 0

        # Check multi-word phrase matches first
        matched_phrase_words = set()
        for phrase, weight in self.lexicon.items():
            if " " in phrase and phrase in clean_text:
                idx = clean_text.find(phrase)
                preceding_text = clean_text[max(0, idx - 30):idx]
                negated = any(neg in preceding_text for neg in ["not", "no ", "fails to", "failed to", "without", "never", "unable to"])
                val = -weight * 0.9 if negated else weight
                score += val
                matches += 1
                for w in phrase.split():
                    matched_phrase_words.add(w)

        # Check single word matches (skip words already matched as part of a phrase)
        for i, word in enumerate(words):
            if word in self.lexicon and " " not in word and word not in matched_phrase_words:
                weight = self.lexicon[word]
                # Look back up to 3 words for negation
                window = words[max(0, i - 3):i]
                negated = any(neg in window for neg in NEGATION_TERMS)
                val = -weight * 0.9 if negated else weight
                score += val
                matches += 1
                matches += 1

        # Normalize score to [-1.0, 1.0]
        if matches > 0:
            raw_score = score / math.sqrt(matches + 1)
            normalized_score = max(-1.0, min(1.0, raw_score))
            confidence = min(0.95, 0.4 + (0.15 * matches))
        else:
            normalized_score = 0.0
            confidence = 0.3

        # Categorize sentiment label
        if normalized_score >= 0.15:
            label = SentimentLabel.BULLISH
        elif normalized_score <= -0.15:
            label = SentimentLabel.BEARISH
        else:
            label = SentimentLabel.NEUTRAL

        category = self._detect_category(clean_text)
        urgency = self._detect_urgency(clean_text, normalized_score)

        return normalized_score, label, round(confidence, 2), category, urgency

    def _detect_category(self, text: str) -> NewsCategory:
        if any(w in text for w in ["result", "profit", "revenue", "ebitda", "earning", "q1", "q2", "q3", "q4"]):
            return NewsCategory.EARNINGS
        if any(w in text for w in ["sebi", "rbi", "cbi", "court", "probe", "order", "compliance", "penalty"]):
            return NewsCategory.REGULATORY
        if any(w in text for w in ["ceo", "cfo", "board", "director", "governance", "resigns", "promoter"]):
            return NewsCategory.CORPORATE_GOVERNANCE
        if any(w in text for w in ["contract", "order win", "deal", "agreement", "bagged", "tender"]):
            return NewsCategory.CONTRACT_ORDER
        if any(w in text for w in ["dividend", "split", "bonus", "buyback"]):
            return NewsCategory.DIVIDEND_SPLIT
        if any(w in text for w in ["target price", "upgrade", "downgrade", "brokerage", "rating"]):
            return NewsCategory.ANALYST_OPINION
        if any(w in text for w in ["inflation", "gdp", "rate hike", "repo rate", "fed", "macro"]):
            return NewsCategory.MACRO_POLICY
        return NewsCategory.GENERAL

    def _detect_urgency(self, text: str, sentiment: float) -> NewsUrgency:
        high_urgency_triggers = [
            "sebi", "cbi", "raid", "probe", "fraud", "default", "bankruptcy",
            "auditor resign", "penalty", "halt", "circuit limit"
        ]
        if any(t in text for t in high_urgency_triggers) or abs(sentiment) >= 0.8:
            return NewsUrgency.HIGH

        med_urgency_triggers = [
            "result", "earnings", "contract", "upgrade", "downgrade", "dividend", "acquisition"
        ]
        if any(t in text for t in med_urgency_triggers) or abs(sentiment) >= 0.4:
            return NewsUrgency.MEDIUM

        return NewsUrgency.LOW

    def calculate_decayed_sentiment(
        self,
        news_items: List[NewsItem],
        as_of_time: Optional[datetime] = None,
        half_life_hours: float = 24.0,
    ) -> float:
        """
        Calculates time-decayed aggregate sentiment across multiple news items.
        Older news decays exponentially according to half_life_hours.
        Returns aggregate sentiment scaled to [-100.0, +100.0].
        """
        if not news_items:
            return 0.0

        ref_time = as_of_time or datetime.now(timezone.utc)
        total_weight = 0.0
        weighted_sum = 0.0

        for item in news_items:
            # Enforce lookahead protection (INV-26)
            if not item.is_eligible_at(ref_time):
                continue

            dt_hours = max(0.0, (ref_time - item.published_at).total_seconds() / 3600.0)
            decay_factor = math.exp(-math.log(2) * (dt_hours / half_life_hours))

            # High urgency news carries 1.5x weight; Medium 1.2x; Low 1.0x
            urgency_mult = 1.5 if item.urgency == NewsUrgency.HIGH else (1.2 if item.urgency == NewsUrgency.MEDIUM else 1.0)
            weight = decay_factor * item.confidence * urgency_mult

            weighted_sum += item.sentiment_score * weight
            total_weight += weight

        if total_weight <= 0.0:
            return 0.0

        aggregate = (weighted_sum / total_weight) * 100.0
        return round(max(-100.0, min(100.0, aggregate)), 2)
