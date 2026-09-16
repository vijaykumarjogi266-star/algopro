"""Algo Lab Golden Dataset & Reproducibility Suite.

Adheres to Non-Negotiable Principles:
- Principle 4: No look-ahead bias.
- Principle 7: Every backtest must be reproducible.
- Principle 20: Optimize for robustness, not maximum historical return.
"""

from typing import Dict, Any, List
import hashlib
import json

# Certified 5-day canonical NSE series fixture (OHLCV)
GOLDEN_DATASET: List[Dict[str, Any]] = [
    {"timestamp": "2026-09-08T09:15:00Z", "symbol": "NIFTY50", "open": 24800.0, "high": 24890.0, "low": 24780.0, "close": 24850.0, "volume": 150000},
    {"timestamp": "2026-09-09T09:15:00Z", "symbol": "NIFTY50", "open": 24860.0, "high": 24950.0, "low": 24840.0, "close": 24920.0, "volume": 180000},
    {"timestamp": "2026-09-10T09:15:00Z", "symbol": "NIFTY50", "open": 24910.0, "high": 24960.0, "low": 24820.0, "close": 24830.0, "volume": 210000},
    {"timestamp": "2026-09-11T09:15:00Z", "symbol": "NIFTY50", "open": 24840.0, "high": 25000.0, "low": 24830.0, "close": 24980.0, "volume": 195000},
    {"timestamp": "2026-09-15T09:15:00Z", "symbol": "NIFTY50", "open": 24990.0, "high": 25050.0, "low": 24920.0, "close": 25010.0, "volume": 170000},
]

# Baseline expected outcomes for Canonical benchmark on this dataset
GOLDEN_EXPECTED_RESULTS = {
    "total_bars": 5,
    "entry_price": 24850.0,
    "exit_price": 25010.0,
    "gross_return_inr": 160.0,
    "zero_lookahead_verified": True,
}


class GoldenDatasetSuite:
    """Certifies reproducibility against the golden dataset baseline and detects drift."""

    @staticmethod
    def get_dataset_checksum() -> str:
        data_str = json.dumps(GOLDEN_DATASET, sort_keys=True)
        return hashlib.sha256(data_str.encode("utf-8")).hexdigest()

    @staticmethod
    def verify_reproducibility(simulated_run_output: Dict[str, Any]) -> bool:
        """Verifies that simulated output reproduces the golden baseline."""
        if simulated_run_output.get("total_bars") != GOLDEN_EXPECTED_RESULTS["total_bars"]:
            return False
        if abs(simulated_run_output.get("gross_return_inr", 0.0) - GOLDEN_EXPECTED_RESULTS["gross_return_inr"]) > 1e-4:
            return False
        return True
