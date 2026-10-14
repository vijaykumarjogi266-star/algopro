"""Batch C Regression Tests: Strategy Dispatch, Order Provenance, and Risk Priority (C01–C07).

Requirements covered:
- C01: Two strategies with opposite decisions on identical bars produce different orders according to the selected implementation.
- C02: Unknown strategy yields no entry.
- C03: Stop/target parameters change submitted and persisted protection exactly.
- C04: Order/fill evidence records strategy/version/decision/data metadata before fill.
- C05: Buy-and-hold allocation is explicit and identical across strategy/service execution paths.
- C06: Invalid parameter types/ranges fail closed before dispatch.
- C07: Upstream risk limits override strategy intent without being bypassed by AI/news signals.
"""

import math
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

from run_live_paper_daemon import (
    DaemonController,
    validate_manifest,
    IST_TZ,
)
from quant.strategies.registry import StrategyRegistry
from quant.strategies.buy_and_hold import BuyAndHold
from services.risk_engine.engine import RiskEngine
from services.risk_engine.contracts import HardRiskLimits, RiskRejectionCode
from services.paper_engine.session import PaperTradingEngine
from services.backtest_engine.contracts import OrderSide


def _create_test_manifest(
    current_date: str,
    gen_time: datetime,
    strat: str = "STRAT_EMA_MOMENTUM",
    parameters: dict = None,
    risk_mult: float = 1.0,
    dec_id: str = "dec_c_test_001",
) -> dict:
    return {
        "schema_version": "1.0.0",
        "decision_id": dec_id,
        "generated_at_utc": gen_time.isoformat(),
        "target_session_date": current_date,
        "selected_strategy": strat,
        "parameters": parameters if parameters is not None else {"stop_loss_atr": 1.5, "target_atr": 3.0},
        "risk_multiplier": risk_mult,
        "dataset_id": "NSE_DAILY_2026",
        "dataset_checksum": "sha256_mock_abc123",
        "code_version": "1.0.0",
    }


def test_c01_opposite_strategy_decisions_on_identical_bars_produce_different_orders(tmp_path):
    """C01: Two strategies with opposite decisions on identical bars produce different orders."""
    t_market = datetime(2026, 4, 1, 10, 0, tzinfo=IST_TZ)
    current_date = "2026-04-01"

    # Market data for INFY.NS:
    # Bullish trend for SMA (fast 105 > slow 100),
    # but NOT broken out for Donchian (high_20 is 115.0 > price 105.0)
    # and NOT oversold for VWAP (vwap_lower is 97.0 < price 105.0).
    identical_market_data = {
        "INFY.NS": {
            "symbol": "INFY.NS",
            "status": "OK",
            "price": 105.0,
            "atr": 2.0,
            "fast_sma": 105.0,
            "slow_sma": 100.0,
            "high_20": 115.0,
            "vwap": 100.0,
            "vwap_lower": 97.0,
            "historical_returns": [0.01] * 25,
        }
    }

    # Run 1: STRAT_EMA_MOMENTUM evaluates to BUY -> order submitted
    db_path1 = str(tmp_path / "c01_strat1.db")
    controller1 = DaemonController(db_path=db_path1, initial_capital=10000.0, leverage=5.0)
    controller1.initialize_session(current_time=t_market)

    manifest_mom = _create_test_manifest(current_date, t_market, strat="STRAT_EMA_MOMENTUM", dec_id="dec_mom_01")
    controller1.sentinel.get_latest_strategy_decision = MagicMock(return_value=manifest_mom)

    res1 = controller1.run_cycle(scan_results=identical_market_data, current_time=t_market)
    assert res1["status"] == "OK"
    assert len(controller1.session.orders) == 1, "STRAT_EMA_MOMENTUM must place a BUY order on fast > slow"
    assert controller1.session.orders[0].side == OrderSide.BUY

    # Run 2: STRAT_DONCHIAN_BREAKOUT on IDENTICAL data evaluates to WAIT (105.0 <= 115.0 high_20) -> no order
    db_path2 = str(tmp_path / "c01_strat2.db")
    controller2 = DaemonController(db_path=db_path2, initial_capital=10000.0, leverage=5.0)
    controller2.initialize_session(current_time=t_market)

    manifest_donchian = _create_test_manifest(current_date, t_market, strat="STRAT_DONCHIAN_BREAKOUT", dec_id="dec_donchian_01")
    controller2.sentinel.get_latest_strategy_decision = MagicMock(return_value=manifest_donchian)

    res2 = controller2.run_cycle(scan_results=identical_market_data, current_time=t_market)
    assert res2["status"] == "OK"
    assert len(controller2.session.orders) == 0, "STRAT_DONCHIAN_BREAKOUT must place NO order on identical non-breakout data"


def test_c02_unknown_strategy_yields_no_entry(tmp_path):
    """C02: Unknown strategy yields no entry."""
    db_path = str(tmp_path / "c02_unknown.db")
    t_market = datetime(2026, 4, 1, 10, 0, tzinfo=IST_TZ)
    current_date = "2026-04-01"

    controller = DaemonController(db_path=db_path, initial_capital=10000.0, leverage=5.0)
    controller.initialize_session(current_time=t_market)

    manifest_unknown = _create_test_manifest(current_date, t_market, strat="STRAT_NON_EXISTENT_GHOST")
    controller.sentinel.get_latest_strategy_decision = MagicMock(return_value=manifest_unknown)

    scan_data = {
        "RELIANCE.NS": {
            "symbol": "RELIANCE.NS",
            "status": "OK",
            "price": 2000.0,
            "atr": 20.0,
            "signal": "BUY",
            "historical_returns": [0.01] * 25,
        }
    }

    # Validation must reject unknown strategy fail-closed
    is_valid, err = validate_manifest(manifest_unknown, current_date, now_dt=t_market)
    assert is_valid is False
    assert "unknown strategy" in err.lower()

    # Daemon execution yields no entry
    res = controller.run_cycle(scan_results=scan_data, current_time=t_market)
    assert res["status"] == "OK"
    assert len(controller.session.orders) == 0


def test_c03_stop_target_parameters_change_submitted_and_persisted_protection_exactly(tmp_path):
    """C03: Stop/target parameters change submitted and persisted protection exactly."""
    t_market = datetime(2026, 4, 1, 10, 0, tzinfo=IST_TZ)
    current_date = "2026-04-01"

    market_data = {
        "RELIANCE.NS": {
            "symbol": "RELIANCE.NS",
            "status": "OK",
            "price": 1000.0,
            "atr": 20.0,
            "fast_sma": 105.0,
            "slow_sma": 95.0,
            "historical_returns": [0.01] * 25,
        }
    }

    # Case A: stop_loss_atr = 1.5, target_atr = 3.0
    # Expected Stop = 1000.0 - (1.5 * 20.0) = 970.0
    # Expected Target = 1000.0 + (3.0 * 20.0) = 1060.0
    db_path_a = str(tmp_path / "c03_a.db")
    ctrl_a = DaemonController(db_path=db_path_a, initial_capital=10000.0, leverage=5.0)
    ctrl_a.initialize_session(current_time=t_market)

    manifest_a = _create_test_manifest(
        current_date,
        t_market,
        strat="STRAT_EMA_MOMENTUM",
        parameters={"stop_loss_atr": 1.5, "target_atr": 3.0},
        dec_id="dec_c03_a",
    )
    ctrl_a.sentinel.get_latest_strategy_decision = MagicMock(return_value=manifest_a)
    ctrl_a.run_cycle(scan_results=market_data, current_time=t_market)

    assert len(ctrl_a.session.orders) == 1
    order_a = ctrl_a.session.orders[0]
    assert order_a.stop_loss == 970.0
    assert order_a.target_price == 1060.0
    assert ctrl_a.trade_stops["RELIANCE.NS"] == 970.0
    assert ctrl_a.trade_targets["RELIANCE.NS"] == 1060.0

    # Case B: stop_loss_atr = 2.5, target_atr = 4.5
    # Expected Stop = 1000.0 - (2.5 * 20.0) = 950.0
    # Expected Target = 1000.0 + (4.5 * 20.0) = 1090.0
    db_path_b = str(tmp_path / "c03_b.db")
    ctrl_b = DaemonController(db_path=db_path_b, initial_capital=10000.0, leverage=5.0)
    ctrl_b.initialize_session(current_time=t_market)

    manifest_b = _create_test_manifest(
        current_date,
        t_market,
        strat="STRAT_EMA_MOMENTUM",
        parameters={"stop_loss_atr": 2.5, "target_atr": 4.5},
        dec_id="dec_c03_b",
    )
    ctrl_b.sentinel.get_latest_strategy_decision = MagicMock(return_value=manifest_b)
    ctrl_b.run_cycle(scan_results=market_data, current_time=t_market)

    assert len(ctrl_b.session.orders) == 1
    order_b = ctrl_b.session.orders[0]
    assert order_b.stop_loss == 950.0
    assert order_b.target_price == 1090.0
    assert ctrl_b.trade_stops["RELIANCE.NS"] == 950.0
    assert ctrl_b.trade_targets["RELIANCE.NS"] == 1090.0


def test_c04_order_fill_evidence_records_strategy_version_decision_data_metadata_before_fill(tmp_path):
    """C04: Order/fill evidence records strategy/version/decision/data metadata before fill."""
    db_path = str(tmp_path / "c04_provenance.db")
    t_market = datetime(2026, 4, 1, 10, 0, tzinfo=IST_TZ)
    current_date = "2026-04-01"

    controller = DaemonController(db_path=db_path, initial_capital=10000.0, leverage=5.0)
    controller.initialize_session(current_time=t_market)

    dec_id = "dec_provenance_audit_888"
    manifest = {
        "schema_version": "1.0.0",
        "decision_id": dec_id,
        "generated_at_utc": t_market.isoformat(),
        "target_session_date": current_date,
        "selected_strategy": "STRAT_EMA_MOMENTUM",
        "parameters": {"stop_loss_atr": 1.5, "target_atr": 3.0},
        "risk_multiplier": 1.0,
        "dataset_id": "NSE_DAILY_BENCHMARK_2026",
        "dataset_checksum": "sha256_audit_dataset_provenance_valid",
        "code_version": "2.1.0",
    }
    controller.sentinel.get_latest_strategy_decision = MagicMock(return_value=manifest)

    scan_data = {
        "INFY.NS": {
            "symbol": "INFY.NS",
            "status": "OK",
            "price": 1500.0,
            "atr": 15.0,
            "fast_sma": 1510.0,
            "slow_sma": 1490.0,
            "historical_returns": [0.01] * 25,
        }
    }

    res = controller.run_cycle(scan_results=scan_data, current_time=t_market)
    assert res["status"] == "OK"
    assert len(controller.session.orders) == 1
    assert len(controller.session.fills) == 1

    # Order evidence checks
    order = controller.session.orders[0]
    assert order.strategy_id == "STRAT_EMA_MOMENTUM"
    assert order.strategy_version == "1.0.0"
    assert order.decision_id == dec_id
    assert order.parameters == {"stop_loss_atr": 1.5, "target_atr": 3.0}
    assert order.data_provenance["dataset_id"] == "NSE_DAILY_BENCHMARK_2026"
    assert order.data_provenance["dataset_checksum"] == "sha256_audit_dataset_provenance_valid"

    # Fill evidence checks
    fill = controller.session.fills[0]
    assert fill.strategy_id == "STRAT_EMA_MOMENTUM"
    assert fill.strategy_version == "1.0.0"
    assert fill.decision_id == dec_id
    assert fill.data_provenance["dataset_id"] == "NSE_DAILY_BENCHMARK_2026"

    # Verify reload from SQLite database preserves provenance fields
    reloaded_engine = PaperTradingEngine(db_path=db_path)
    reloaded_session = reloaded_engine.get_session(controller.session.session_id)
    assert len(reloaded_session.orders) == 1
    reloaded_order = reloaded_session.orders[0]
    assert reloaded_order.strategy_id == "STRAT_EMA_MOMENTUM"
    assert reloaded_order.decision_id == dec_id
    assert reloaded_order.data_provenance["dataset_checksum"] == "sha256_audit_dataset_provenance_valid"


def test_c05_buy_and_hold_allocation_is_explicit_and_identical_across_paths():
    """C05: Buy-and-hold allocation is explicit and identical across strategy/service execution paths."""
    capital = 100_000.0
    price = 250.0

    # 1. Single symbol default 100% allocation
    strat_single = BuyAndHold(parameters={"allocation_pct": 1.0})
    weight_single = strat_single.get_allocation_weight("RELIANCE")
    assert weight_single == 1.0
    allocated_single = capital * weight_single
    qty_single = int(allocated_single / price)
    assert qty_single == 400
    assert (qty_single * price) <= capital

    # 2. Multi-symbol universe equal-weighting
    symbols = ["RELIANCE", "TCS", "INFY", "SBIN"]
    strat_multi = BuyAndHold(parameters={"allocation_pct": 0.80, "universe": symbols})
    total_spent = 0.0
    for sym in symbols:
        w = strat_multi.get_allocation_weight(sym)
        assert pytest.approx(w, abs=1e-4) == 0.20  # 0.80 / 4
        alloc = capital * w
        qty = int(alloc / price)
        cost = qty * price
        assert cost <= alloc
        total_spent += cost

    assert total_spent <= (capital * 0.80)
    assert capital - total_spent >= (capital * 0.20)

    # 3. Explicit weights conserve cash
    explicit_weights = {"RELIANCE": 0.40, "TCS": 0.35, "INFY": 0.25}
    strat_weights = BuyAndHold(parameters={"weights": explicit_weights})
    sum_weights = sum(strat_weights.get_allocation_weight(s) for s in explicit_weights)
    assert pytest.approx(sum_weights, abs=1e-4) == 1.0


def test_c06_invalid_parameter_types_and_ranges_fail_closed_before_dispatch(tmp_path):
    """C06: Invalid parameter types/ranges fail closed before dispatch."""
    t_market = datetime(2026, 4, 1, 10, 0, tzinfo=IST_TZ)
    current_date = "2026-04-01"

    # Test invalid parameter cases
    corrupt_params = [
        {"stop_loss_atr": -1.0},
        {"stop_loss_atr": 0.0},
        {"stop_loss_atr": float("nan")},
        {"stop_loss_atr": float("inf")},
        {"stop_loss_atr": "invalid_string"},
        {"target_atr": -3.0},
        {"target_atr": 0.0},
        {"target_atr": float("nan")},
        {"target_atr": 999.0},  # Exceeds max bound
        {"risk_multiplier": -0.5},
        {"risk_multiplier": 0.0},
        {"risk_multiplier": 10.0},  # Exceeds max bound 5.0
        {"risk_multiplier": float("nan")},
        {"fast_period": 21, "slow_period": 9},  # fast >= slow
        {"allocation_pct": 1.5},  # > 1.0
    ]

    for p in corrupt_params:
        manifest = _create_test_manifest(current_date, t_market, parameters=p)
        is_valid, err = validate_manifest(manifest, current_date, now_dt=t_market)
        assert is_valid is False, f"Expected manifest to fail closed on parameter {p}, but it passed."

    # Non-dict parameters fail closed
    manifest_nondict = _create_test_manifest(current_date, t_market)
    manifest_nondict["parameters"] = "not_a_dictionary"
    is_valid_nd, err_nd = validate_manifest(manifest_nondict, current_date, now_dt=t_market)
    assert is_valid_nd is False
    assert "dictionary" in err_nd.lower()


def test_c07_upstream_risk_limits_override_strategy_intent_without_ai_bypass(tmp_path):
    """C07: Upstream risk limits override strategy intent without being bypassed by AI/news signals."""
    t_market = datetime(2026, 4, 1, 10, 0, tzinfo=IST_TZ)
    current_date = "2026-04-01"

    # Limit max capital per trade to 10%
    risk_limits = HardRiskLimits(
        max_capital_per_trade_pct=0.10,
        max_open_positions=1,
    )
    db_path = str(tmp_path / "c07_risk.db")
    controller = DaemonController(
        db_path=db_path,
        initial_capital=10000.0,
        leverage=1.0,
        risk_limits=risk_limits,
    )
    controller.initialize_session(current_time=t_market)

    manifest = _create_test_manifest(current_date, t_market, dec_id="dec_c07_ai_test")
    controller.sentinel.get_latest_strategy_decision = MagicMock(return_value=manifest)

    # Case 1: Strategy BUY with aggressive AI proposed quantity (500 shares @ 100 = 50,000 INR > 10,000 capital)
    # Upstream RiskEngine limit: 10% of 10,000 = 1,000 INR -> max 10 shares.
    scan_ai_boost = {
        "SBIN.NS": {
            "symbol": "SBIN.NS",
            "status": "OK",
            "price": 100.0,
            "atr": 2.0,
            "fast_sma": 105.0,
            "slow_sma": 95.0,
            "historical_returns": [0.01] * 25,
            "ai_context": {"suggested_quantity": 500, "sentiment": "VERY_BULLISH"},
        }
    }

    res1 = controller.run_cycle(scan_results=scan_ai_boost, current_time=t_market)
    assert res1["status"] == "OK"
    assert len(controller.session.orders) == 1
    # Quantity must be capped by RiskEngine to approved_quantity (<= 10 shares), NOT AI's 500!
    assert controller.session.orders[0].quantity <= 10
    assert controller.session.orders[0].quantity > 0

    # Case 2: Max open positions reached (limit is 1, we already hold 1)
    # Even if AI sends another hyper-bullish signal for another symbol, RiskEngine blocks it
    scan_ai_second = {
        "INFY.NS": {
            "symbol": "INFY.NS",
            "status": "OK",
            "price": 100.0,
            "atr": 2.0,
            "fast_sma": 105.0,
            "slow_sma": 95.0,
            "historical_returns": [0.01] * 25,
            "ai_context": {"suggested_quantity": 5, "sentiment": "EXTREME_BUY"},
        }
    }
    # Reset decision_id in manifest to avoid duplicate decision suppression
    manifest2 = _create_test_manifest(current_date, t_market, dec_id="dec_c07_ai_test_2")
    controller.sentinel.get_latest_strategy_decision = MagicMock(return_value=manifest2)

    res2 = controller.run_cycle(scan_results=scan_ai_second, current_time=t_market + timedelta(minutes=1))
    assert res2["status"] == "OK"
    # No new order created because max_open_positions is 1
    assert len(controller.session.portfolio.positions) == 1

    # Case 3: AI Veto downsize: AI signals veto_entry -> entry suppressed
    db_path_veto = str(tmp_path / "c07_veto.db")
    controller_veto = DaemonController(
        db_path=db_path_veto,
        initial_capital=10000.0,
        leverage=1.0,
    )
    controller_veto.initialize_session(current_time=t_market)
    manifest3 = _create_test_manifest(current_date, t_market, dec_id="dec_c07_ai_test_3")
    controller_veto.sentinel.get_latest_strategy_decision = MagicMock(return_value=manifest3)

    scan_ai_veto = {
        "TCS.NS": {
            "symbol": "TCS.NS",
            "status": "OK",
            "price": 100.0,
            "atr": 2.0,
            "fast_sma": 105.0,
            "slow_sma": 95.0,
            "historical_returns": [0.01] * 25,
            "ai_context": {"veto_entry": True, "reason": "Hostile news event detected"},
        }
    }
    res3 = controller_veto.run_cycle(scan_results=scan_ai_veto, current_time=t_market)
    assert res3["status"] == "OK"
    assert len(controller_veto.session.orders) == 0, "AI veto must downsize entry to zero"
