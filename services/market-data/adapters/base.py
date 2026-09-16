"""Algo Lab Market Data Provider Adapter Interface & Mock Provider (Stage 6).

Adheres to Non-Negotiable Principles:
- Principle 3: Bad or uncertain data must not produce a trading decision.
- Principle 13: Data validation must fail closed.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from data.schemas.canonical_market_data import CanonicalMarketDataBar, CanonicalMarketDataValidator


class MarketDataProvider(ABC):
    """Abstract interface for external or local market data providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Provider identifier."""
        pass

    @abstractmethod
    def test_connection(self) -> Dict[str, Any]:
        """Tests connectivity and credentials with the provider."""
        pass

    @abstractmethod
    def get_bars(
        self,
        symbol: str,
        timeframe: str,
        start_time: datetime,
        end_time: datetime,
    ) -> List[CanonicalMarketDataBar]:
        """Retrieves and normalizes market data bars into canonical schema."""
        pass

    @abstractmethod
    def get_latest_bar(self, symbol: str) -> Optional[CanonicalMarketDataBar]:
        """Retrieves the latest available canonical bar."""
        pass


class MockMarketDataProvider(MarketDataProvider):
    """Deterministic in-memory market data provider for tests and simulations."""

    def __init__(self, provider_name: str = "mock_feed", should_fail: bool = False):
        self._provider_name = provider_name
        self.should_fail = should_fail
        self._custom_bars: Dict[str, List[CanonicalMarketDataBar]] = {}

    @property
    def provider_name(self) -> str:
        return self._provider_name

    def seed_bars(self, symbol: str, bars: List[CanonicalMarketDataBar]):
        """Seeds predefined canonical bars for testing."""
        val = CanonicalMarketDataValidator.validate_series(bars)
        if not val.is_valid:
            raise ValueError(f"Seeded bars failed validation: {val.errors}")
        self._custom_bars[symbol.upper()] = sorted(bars, key=lambda b: b.timestamp)

    def test_connection(self) -> Dict[str, Any]:
        if self.should_fail:
            return {
                "status": "FAILED",
                "message": "Simulated connection timeout to data provider",
                "connected": False,
            }
        return {
            "status": "CONNECTED",
            "message": f"Successfully connected to {self.provider_name}",
            "connected": True,
            "latency_ms": 1.2,
        }

    def get_bars(
        self,
        symbol: str,
        timeframe: str,
        start_time: datetime,
        end_time: datetime,
    ) -> List[CanonicalMarketDataBar]:
        if self.should_fail:
            raise ConnectionError(f"Connection failure to {self.provider_name}")

        sym = symbol.upper()
        bars = self._custom_bars.get(sym, [])

        # Filter by time range
        filtered = [b for b in bars if start_time <= b.timestamp <= end_time]
        return filtered

    def get_latest_bar(self, symbol: str) -> Optional[CanonicalMarketDataBar]:
        if self.should_fail:
            raise ConnectionError(f"Connection failure to {self.provider_name}")

        sym = symbol.upper()
        bars = self._custom_bars.get(sym, [])
        return bars[-1] if bars else None
