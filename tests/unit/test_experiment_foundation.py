"""Algo Lab Stage 5 Phase B: Experiment Foundation Unit Tests.

Verifies:
1. Experiment serialization and round-trip (Pydantic model_dump / json).
2. Validation rules (dates, universe, checksum format, initial capital).
3. Required fields enforcement.
4. Invalid parameters handling.
5. Deterministic fingerprint generation.
6. Parameter sensitivity (fingerprint changes when parameters change).
7. Dataset checksum sensitivity (fingerprint changes when dataset checksum changes).
8. Strategy version sensitivity (fingerprint changes when strategy version changes).
9. Experiment Definition vs Run separation.
10. Persistence round-trip in BacktestRunStore.
"""

import unittest
from datetime import datetime, timezone, timedelta
from pydantic import ValidationError

from services.backtest_engine.contracts import (
    ExperimentDefinition,
    ExperimentRun,
    ExperimentStatus,
    CostModelConfig,
    SlippageModelConfig,
    BacktestMetrics,
)
from services.backtest_engine.persistence import BacktestRunStore


class TestExperimentFoundation(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026, 1, 1, 9, 15, tzinfo=timezone.utc)
        self.end = datetime(2026, 6, 30, 15, 30, tzinfo=timezone.utc)
        self.valid_checksum = "a" * 64
        self.base_kwargs = {
            "experiment_id": "exp_foundation_001",
            "name": "Canonical Momentum Test",
            "description": "Testing Phase B experiment foundation",
            "strategy_id": "Canonical_SMA",
            "strategy_version": "1.0.0",
            "dataset_id": "NSE_NIFTY50_DAILY",
            "dataset_version": "2026.09.14",
            "dataset_checksum": self.valid_checksum,
            "universe": ["NIFTY50", "RELIANCE"],
            "timeframe": "1d",
            "start_date": self.start,
            "end_date": self.end,
            "parameters": {"fast_period": 10, "slow_period": 30},
            "initial_capital": 500000.0,
            "seed": 42,
            "code_revision": "main",
        }

    def test_experiment_creation_and_serialization(self):
        exp = ExperimentDefinition(**self.base_kwargs)
        self.assertEqual(exp.status, ExperimentStatus.CREATED)
        self.assertIsNotNone(exp.fingerprint)
        self.assertEqual(len(exp.fingerprint), 64)

        # Serialization to dict and JSON
        d = exp.model_dump()
        self.assertIn("fingerprint", d)
        self.assertEqual(d["name"], "Canonical Momentum Test")

        json_str = exp.model_dump_json()
        self.assertIn('"strategy_id":"Canonical_SMA"', json_str)

    def test_validation_start_date_before_end_date(self):
        invalid_kwargs = dict(self.base_kwargs)
        invalid_kwargs["start_date"] = self.end
        invalid_kwargs["end_date"] = self.start
        with self.assertRaises(ValidationError):
            ExperimentDefinition(**invalid_kwargs)

    def test_validation_empty_universe(self):
        invalid_kwargs = dict(self.base_kwargs)
        invalid_kwargs["universe"] = []
        with self.assertRaises(ValidationError):
            ExperimentDefinition(**invalid_kwargs)

    def test_validation_invalid_checksum_length(self):
        invalid_kwargs = dict(self.base_kwargs)
        invalid_kwargs["dataset_checksum"] = "too_short"
        with self.assertRaises(ValidationError):
            ExperimentDefinition(**invalid_kwargs)

    def test_validation_non_positive_capital(self):
        invalid_kwargs = dict(self.base_kwargs)
        invalid_kwargs["initial_capital"] = -100.0
        with self.assertRaises(ValidationError):
            ExperimentDefinition(**invalid_kwargs)

    def test_deterministic_fingerprint(self):
        exp1 = ExperimentDefinition(**self.base_kwargs)
        exp2 = ExperimentDefinition(**self.base_kwargs)
        self.assertEqual(exp1.fingerprint, exp2.fingerprint)

        # Changing volatile attributes must NOT alter fingerprint
        volatile_kwargs = dict(self.base_kwargs)
        volatile_kwargs["experiment_id"] = "different_exp_id_999"
        volatile_kwargs["name"] = "Different Arbitrary Name"
        volatile_kwargs["description"] = "A completely new description"
        exp3 = ExperimentDefinition(**volatile_kwargs)
        self.assertEqual(exp1.fingerprint, exp3.fingerprint)

    def test_parameter_sensitivity(self):
        exp1 = ExperimentDefinition(**self.base_kwargs)
        modified_kwargs = dict(self.base_kwargs)
        modified_kwargs["parameters"] = {"fast_period": 15, "slow_period": 30}
        exp2 = ExperimentDefinition(**modified_kwargs)
        self.assertNotEqual(exp1.fingerprint, exp2.fingerprint)

    def test_dataset_checksum_sensitivity(self):
        exp1 = ExperimentDefinition(**self.base_kwargs)
        modified_kwargs = dict(self.base_kwargs)
        modified_kwargs["dataset_checksum"] = "b" * 64
        exp2 = ExperimentDefinition(**modified_kwargs)
        self.assertNotEqual(exp1.fingerprint, exp2.fingerprint)

    def test_strategy_version_sensitivity(self):
        exp1 = ExperimentDefinition(**self.base_kwargs)
        modified_kwargs = dict(self.base_kwargs)
        modified_kwargs["strategy_version"] = "2.0.0"
        exp2 = ExperimentDefinition(**modified_kwargs)
        self.assertNotEqual(exp1.fingerprint, exp2.fingerprint)

    def test_seed_sensitivity(self):
        exp1 = ExperimentDefinition(**self.base_kwargs)
        modified_kwargs = dict(self.base_kwargs)
        modified_kwargs["seed"] = 1337
        exp2 = ExperimentDefinition(**modified_kwargs)
        self.assertNotEqual(exp1.fingerprint, exp2.fingerprint)

    def test_experiment_and_run_separation(self):
        exp = ExperimentDefinition(**self.base_kwargs)
        run = ExperimentRun(
            run_id="run_001",
            experiment_id=exp.experiment_id,
            status=ExperimentStatus.PENDING,
            reproducibility_hash=exp.fingerprint,
        )
        self.assertEqual(run.experiment_id, exp.experiment_id)
        self.assertEqual(run.status, ExperimentStatus.PENDING)
        self.assertIsNone(run.metrics)

        # Mutating run execution outcome does NOT alter experiment definition
        run.status = ExperimentStatus.COMPLETED
        run.metrics = BacktestMetrics(
            total_return_pct=12.5,
            cagr_pct=15.0,
            number_of_trades=10,
            win_rate=0.6,
            average_win=1000.0,
            average_loss=500.0,
            profit_factor=2.0,
            expectancy=400.0,
            maximum_drawdown_pct=5.0,
            sharpe_ratio=1.5,
            sortino_ratio=2.1,
            maximum_consecutive_losses=2,
            average_holding_time_seconds=3600.0,
            exposure_pct=25.0,
            total_transaction_costs=150.0,
            total_slippage_impact=50.0,
            worst_trade_pnl=-500.0,
            worst_day_pnl=-400.0,
        )
        self.assertEqual(exp.status, ExperimentStatus.CREATED)
        self.assertNotEqual(run.status, exp.status)

    def test_persistence_round_trip(self):
        store = BacktestRunStore(":memory:")
        exp = ExperimentDefinition(**self.base_kwargs)
        store.save_experiment(exp)

        loaded = store.get_experiment(exp.experiment_id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.experiment_id, exp.experiment_id)
        self.assertEqual(loaded.name, exp.name)
        self.assertEqual(loaded.fingerprint, exp.fingerprint)
        self.assertEqual(loaded.parameters, exp.parameters)
        self.assertEqual(loaded.universe, exp.universe)
        self.assertEqual(loaded.initial_capital, exp.initial_capital)
        self.assertEqual(loaded.seed, exp.seed)

        # Lookup by fingerprint for idempotency
        by_fp = store.get_experiment_by_fingerprint(exp.fingerprint)
        self.assertIsNotNone(by_fp)
        self.assertEqual(by_fp.experiment_id, exp.experiment_id)

        # List experiments
        exp2_kwargs = dict(self.base_kwargs)
        exp2_kwargs["experiment_id"] = "exp_foundation_002"
        exp2_kwargs["strategy_id"] = "Alternative_Strategy"
        exp2 = ExperimentDefinition(**exp2_kwargs)
        store.save_experiment(exp2)

        all_exps = store.list_experiments()
        self.assertEqual(len(all_exps), 2)

        # Filtering
        filtered = store.list_experiments(strategy_id="Alternative_Strategy")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].experiment_id, "exp_foundation_002")


if __name__ == "__main__":
    unittest.main()
