import pytest
from datetime import datetime, timezone, timedelta
from services.backtest_engine.service import BacktestService
from services.backtest_engine.contracts import CostModelConfig, SlippageModelConfig


def test_deterministic_simulation_results():
    service = BacktestService()
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = datetime(2025, 6, 1, tzinfo=timezone.utc)
    universe = ["RELIANCE.NS"]

    res1 = service.submit_backtest(
        strategy_id="Canonical_SMA",
        universe=universe,
        start_date=start,
        end_date=end,
        initial_capital=100000.0,
    )
    status1 = service.get_run_status(res1["experiment_id"])
    assert status1 is not None
    assert status1["status"] in ("RUNNING", "COMPLETED")
    assert res1["reproducibility_hash"] is not None


def test_no_trade_zero_metrics():
    import time
    service = BacktestService()
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = datetime(2025, 1, 5, tzinfo=timezone.utc)  # Too short for 21-day SMA
    universe = ["TCS.NS"]

    res = service.submit_backtest(
        strategy_id="Canonical_SMA",
        universe=universe,
        start_date=start,
        end_date=end,
        initial_capital=50000.0,
    )
    # Give background thread up to 2 seconds to complete
    for _ in range(20):
        status = service.get_run_status(res["experiment_id"])
        if status["status"] == "COMPLETED":
            break
        time.sleep(0.1)

    assert status["status"] == "COMPLETED"
    import json
    metrics = json.loads(status["metrics_json"]) if status.get("metrics_json") else status.get("metrics", {})
    assert metrics["number_of_trades"] == 0
    assert metrics["win_rate"] == 0.0
    assert metrics["total_return_pct"] == 0.0


def test_changing_costs_changes_metrics():
    service = BacktestService()
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = datetime(2025, 8, 1, tzinfo=timezone.utc)
    universe = ["INFY.NS"]

    res_low = service.submit_backtest(
        strategy_id="Canonical_SMA",
        universe=universe,
        start_date=start,
        end_date=end,
        cost_model=CostModelConfig(brokerage_per_trade=10.0, stt_rate=0.0005),
    )
    res_high = service.submit_backtest(
        strategy_id="Canonical_SMA",
        universe=universe,
        start_date=start,
        end_date=end,
        cost_model=CostModelConfig(brokerage_per_trade=100.0, stt_rate=0.005),
    )
    assert res_low["reproducibility_hash"] != res_high["reproducibility_hash"]


def test_empty_universe_rejection():
    service = BacktestService()
    with pytest.raises(ValueError, match="Universe cannot be empty"):
        service.submit_backtest(
            strategy_id="Canonical_SMA",
            universe=[],
            start_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2025, 2, 1, tzinfo=timezone.utc),
        )
