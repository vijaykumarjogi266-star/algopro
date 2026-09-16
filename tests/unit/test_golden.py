"""Algo Lab Golden Dataset & Reproducibility Tests.

Adheres to Non-Negotiable Principles:
- Principle 4: No look-ahead bias.
- Principle 7: Every backtest must be reproducible.
"""

import unittest
from services.backtest_engine.golden import (
    GoldenDatasetSuite,
    GOLDEN_DATASET,
    GOLDEN_EXPECTED_RESULTS,
)


class TestGoldenReproducibility(unittest.TestCase):
    def test_golden_dataset_checksum_invariance(self):
        checksum1 = GoldenDatasetSuite.get_dataset_checksum()
        checksum2 = GoldenDatasetSuite.get_dataset_checksum()
        self.assertEqual(checksum1, checksum2)
        self.assertEqual(len(checksum1), 64)

    def test_golden_results_reproducibility_match(self):
        simulated = {
            "total_bars": len(GOLDEN_DATASET),
            "entry_price": GOLDEN_DATASET[0]["close"],
            "exit_price": GOLDEN_DATASET[-1]["close"],
            "gross_return_inr": GOLDEN_DATASET[-1]["close"] - GOLDEN_DATASET[0]["close"],
        }
        self.assertTrue(GoldenDatasetSuite.verify_reproducibility(simulated))

    def test_golden_drift_detection(self):
        drifted = {
            "total_bars": len(GOLDEN_DATASET),
            "gross_return_inr": 180.0,
        }
        self.assertFalse(GoldenDatasetSuite.verify_reproducibility(drifted))


if __name__ == "__main__":
    unittest.main()
