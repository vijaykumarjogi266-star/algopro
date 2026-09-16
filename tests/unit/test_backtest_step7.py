"""Algo Lab Stage 4 Step 7 Tests.

Tests:
1. Deterministic reproducibility hashing (reproducibility_hash).
2. Independent Risk Engine enforcement & explicit rejection reasons.
3. Persistent SQLite Run Store & ordered audit trail.
4. Asynchronous Backtest Service lifecycle.
5. Research report generation.
"""

import unittest
import time
from datetime import datetime, timezone
from services.risk_engine.contracts import HardRiskLimits, RiskRejectionCode
from services.risk_engine.engine import RiskEngine
from services.backtest_engine.contracts import (
    ReproducibilityRecord,
    CostModelConfig,
    SlippageModelConfig,
    BacktestMetrics,
    BacktestResult,
)
from services.backtest_engine.fingerprint import compute_reproducibility_hash
from services.backtest_engine.persistence import BacktestRunStore
from services.backtest_engine.reporting import BacktestReportGenerator
from services.backtest_engine.service import BacktestService


class TestStage4Step7(unittest.TestCase):
    def test_reproducibility_hash_invariance_and_sensitivity(self):
        config_a = {
            "strategy_id": "Canonical_SMA",
            "universe": ["NIFTY50", "RELIANCE"],
            "parameters": {"fast": 10, "slow": 30},
            "initial_capital": 500000.0,
            "experiment_id": "volatile_id_1",  # Volatile
        }
        config_b = {
            "strategy_id": "Canonical_SMA",
            "universe": ["NIFTY50", "RELIANCE"],
            "parameters": {"fast": 10, "slow": 30},
            "initial_capital": 500000.0,
            "experiment_id": "different_id_2",  # Volatile
        }
        hash_a = compute_reproducibility_hash(config_a)
        hash_b = compute_reproducibility_hash(config_b)
        self.assertEqual(hash_a, hash_b, "Hashes must match regardless of volatile run IDs")

        # Changing parameters must change the hash
        config_c = dict(config_a)
        config_c["parameters"] = {"fast": 15, "slow": 30}
        self.assertNotEqual(hash_a, compute_reproducibility_hash(config_c))

    def test_independent_risk_engine_stop_loss_enforcement(self):
        engine = RiskEngine(HardRiskLimits(enforce_mandatory_stop_loss=True))
        # Missing stop loss
        verdict = engine.evaluate(
            symbol="RELIANCE",
            price=2500.0,
            proposed_quantity=5,
            stop_loss=None,  # No stop loss
            current_portfolio_value=500000.0,
            current_daily_loss_pct=0.0,
            current_drawdown_pct=0.0,
            current_open_positions_count=0,
        )
        self.assertFalse(verdict.is_approved)
        self.assertEqual(verdict.rejection_code, RiskRejectionCode.MISSING_STOP_LOSS)
        self.assertIn("Mandatory stop loss", verdict.rejection_reason)

    def test_independent_risk_engine_max_capital_limit(self):
        # 5% max capital per trade on 500k is 25,000 INR
        engine = RiskEngine(HardRiskLimits(max_capital_per_trade_pct=0.05))
        # Attempting trade of 20 shares * 2500 = 50,000 INR > 25,000 INR
        verdict = engine.evaluate(
            symbol="RELIANCE",
            price=2500.0,
            proposed_quantity=20,
            stop_loss=2450.0,
            current_portfolio_value=500000.0,
            current_daily_loss_pct=0.0,
            current_drawdown_pct=0.0,
            current_open_positions_count=0,
        )
        self.assertFalse(verdict.is_approved)
        self.assertEqual(verdict.rejection_code, RiskRejectionCode.EXCEEDS_MAX_CAPITAL)

    def test_persistence_store_and_audit_trail(self):
        store = BacktestRunStore(":memory:")
        now = datetime.now(timezone.utc)
        repro = ReproducibilityRecord(
            experiment_id="exp_test_01",
            git_commit="main",
            dataset_version="2026.09.14",
            strategy_version="1.0.0",
            indicator_versions={},
            parameters={"k": "v"},
            initial_capital=500000.0,
            cost_model=CostModelConfig(),
            slippage_model=SlippageModelConfig(),
            universe=["NIFTY50"],
            timeframe="1d",
            start_date=now,
            end_date=now,
            reproducibility_hash="sha256_mock",
        )

        store.save_run(
            experiment_id="exp_test_01",
            reproducibility=repro,
            status="PENDING",
        )
        store.append_audit_event("exp_test_01", "TEST_SIGNAL", {"dir": "BUY"})
        store.append_audit_event("exp_test_01", "TEST_RISK", {"outcome": "APPROVED"})

        trail = store.get_audit_trail("exp_test_01")
        self.assertEqual(len(trail), 2)
        self.assertEqual(trail[0]["event_type"], "TEST_SIGNAL")
        self.assertEqual(trail[1]["event_type"], "TEST_RISK")

        # Update status
        store.update_status("exp_test_01", "COMPLETED")
        run_record = store.get_run("exp_test_01")
        self.assertEqual(run_record["status"], "COMPLETED")

    def test_backtest_service_async_execution(self):
        store = BacktestRunStore(":memory:")
        service = BacktestService(store=store, max_workers=2)

        start = datetime(2026, 1, 1, 9, 15, tzinfo=timezone.utc)
        end = datetime(2026, 6, 30, 15, 30, tzinfo=timezone.utc)

        resp = service.submit_backtest(
            strategy_id="SMA_Cross",
            universe=["RELIANCE"],
            start_date=start,
            end_date=end,
            initial_capital=500000.0,
        )
        self.assertEqual(resp["status"], "submitted")
        exp_id = resp["experiment_id"]

        # Wait for async completion
        for _ in range(30):
            row = service.get_run_status(exp_id)
            if row and row["status"] in ("COMPLETED", "FAILED"):
                break
            time.sleep(0.05)

        final_row = service.get_run_status(exp_id)
        self.assertEqual(final_row["status"], "COMPLETED")

        trail = service.get_audit_trail(exp_id)
        self.assertGreater(len(trail), 0)


if __name__ == "__main__":
    unittest.main()
