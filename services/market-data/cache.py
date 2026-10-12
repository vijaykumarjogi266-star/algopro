"""Algo Lab Market Data LRU Cache & Persistent Store.

Provides thread-safe in-memory LRU caching with persistent query fallback,
reducing replay latency and cold-start overhead during backtesting and live data ingestion.
"""

from collections import OrderedDict
from datetime import datetime, timezone
import threading
from typing import Any, Dict, List, Optional, Tuple
import polars as pl

from data.schemas.contracts import Exchange, OHLCVBar, TimeFrame
from apps.api.core.logging import get_logger

logger = get_logger(__name__)


class LRUMarketDataCache:
    """Thread-safe LRU Cache for parsed market data frames and bar sequences."""

    def __init__(self, max_entries: int = 128):
        self.max_entries = max_entries
        self._cache: OrderedDict[str, Any] = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def _make_key(
        self,
        exchange: Exchange,
        timeframe: TimeFrame,
        symbol: str,
        year_or_range: Any,
    ) -> str:
        return f"{exchange.value.upper()}:{timeframe.value.lower()}:{symbol.upper()}:{year_or_range}"

    def get(
        self,
        exchange: Exchange,
        timeframe: TimeFrame,
        symbol: str,
        year_or_range: Any,
    ) -> Optional[Any]:
        """Retrieves cached item, updating access order."""
        key = self._make_key(exchange, timeframe, symbol, year_or_range)
        with self._lock:
            if key in self._cache:
                self._hits += 1
                self._cache.move_to_end(key)
                return self._cache[key]
            self._misses += 1
            return None

    def put(
        self,
        exchange: Exchange,
        timeframe: TimeFrame,
        symbol: str,
        year_or_range: Any,
        data: Any,
    ) -> None:
        """Stores item in cache, evicting least-recently used entry if capacity exceeded."""
        key = self._make_key(exchange, timeframe, symbol, year_or_range)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = data
            if len(self._cache) > self.max_entries:
                evicted_key, _ = self._cache.popitem(last=False)
                logger.debug(f"Evicted LRU market data cache entry: {evicted_key}")

    def clear(self) -> None:
        """Clears all entries and resets statistics."""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0

    @property
    def stats(self) -> Dict[str, Any]:
        """Returns cache telemetry stats."""
        with self._lock:
            total = self._hits + self._misses
            ratio = (self._hits / total) if total > 0 else 0.0
            return {
                "size": len(self._cache),
                "max_entries": self.max_entries,
                "hits": self._hits,
                "misses": self._misses,
                "hit_ratio": round(ratio, 4),
            }
