"""
Algo Lab — Stage 7 Acceptance Tests (Part 2: AT-18 to AT-90)
Covers Walk-Forward, Deterministic Replay Evaluation, Cost/Slippage Frictions,
Analytics, Sensitivity Sweeps, Market Regimes, Out-of-Sample Degradation,
and Audit Trail Provenance.
"""

from datetime import datetime, date, timezone, timedelta
import pytest

from services.evaluation_engine.manifest import (
    ExperimentManifest,
    FrictionConfig,
    TemporalPartition,
    EvaluationEnvironment,
    PartitionType,
)
from services.evaluation_engine.partitioning import (
    create_disjoint_partitions,
    validate_partition_chronology,
)
from services.evaluation_engine.walk_forward import (
    WalkForwardEngine,
    WalkForwardConfig,
    WalkForwardMode,
    LookAheadBiasError,
)
from services.evaluation_engine.engine import (
    DeterministicEvaluationEngine,
    EvaluationResult,
)
from services.evaluation_engine.analytics import (
    PerformanceAnalytics,
    PerformanceMetrics,
)
from services.evaluation_engine.sensitivity import (
    SensitivityEngine,
)
from services.evaluation_engine.regimes import (
    HistoricalRegimeClassifier,
    MarketRegime,
)
from services.evaluation_engine.audit import (
    EvidenceClassifier,
    EvidenceStatus,
    AuditManifest,
    ResearchReportGenerator,
)


def create_sample_bars(num_bars: int = 300) -> list:
    """Helper to generate deterministic OHLCV bar series."""
    base_ts = datetime(2024, 1, 1, 9, 15, tzinfo=timezone.utc)
    bars = []
    price = 100.0
    for i in range(num_bars):
        ts = base_ts + timedelta(days=i)
        # deterministic price oscillation
        price += (1.0 if i % 2 == 0 else -0.5)
        bars.append({
            "timestamp": ts,
            "open": price - 0.2,
            "high": price + 0.5,
            "low": price - 0.5,
            "close": price,
            "volume": 1000,
            "symbol": "NSE_RELIANCE",
        })
    return bars


# Area 6: Walk-Forward Simulation (AT-26 to AT-30)

def test_at_26_expanding_window_execution():
    config = WalkForwardConfig(
        mode=WalkForwardMode.EXPANDING,
        initial_train_size=100,
        test_size=20,
        step_size=20,
        min_train_size=50,
    )
    engine = WalkForwardEngine(config)
    windows = engine.generate_windows(data_length=200)

    assert len(windows) >= 4
    # Step 0: train [0, 100], test [100, 120]
    assert windows[0].train_start_idx == 0
    assert windows[0].train_end_idx == 100
    assert windows[0].test_start_idx == 100
    assert windows[0].test_end_idx == 120

    # Step 1: expanding train [0, 120], test [120, 140]
    assert windows[1].train_start_idx == 0
    assert windows[1].train_end_idx == 120
    assert windows[1].test_start_idx == 120
    assert windows[1].test_end_idx == 140


def test_at_27_rolling_window_execution():
    config = WalkForwardConfig(
        mode=WalkForwardMode.ROLLING,
        initial_train_size=100,
        test_size=20,
        step_size=20,
        min_train_size=50,
    )
    engine = WalkForwardEngine(config)
    windows = engine.generate_windows(data_length=200)

    assert len(windows) >= 4
    # Step 0: train [0, 100], test [100, 120]
    assert windows[0].train_start_idx == 0
    assert windows[0].train_end_idx == 100

    # Step 1: rolling train [20, 120], test [120, 140]
    assert windows[1].train_start_idx == 20
    assert windows[1].train_end_idx == 120


def test_at_28_sub_minimum_window_rejection():
    with pytest.raises(ValueError, match="below minimum required threshold"):
        WalkForwardConfig(
            initial_train_size=40,
            min_train_size=100,
        )


def test_at_29_invalid_step_size_rejection():
    with pytest.raises(ValueError, match="strictly positive"):
        WalkForwardConfig(step_size=0)

    with pytest.raises(ValueError, match="strictly positive"):
        WalkForwardConfig(step_size=-5)


def test_at_30_step_n_plus_1_leakage_prevention():
    config = WalkForwardConfig(
        initial_train_size=100,
        test_size=20,
        step_size=20,
        min_train_size=50,
    )
    engine = WalkForwardEngine(config)
    windows = engine.generate_windows(data_length=200)
    w0 = windows[0]

    # Test index 120 is end index (boundary)
    with pytest.raises(LookAheadBiasError, match="Look-ahead access attempt"):
        w0.validate_no_leakage(120)

    w0.validate_no_leakage(119)  # valid index within window


# Area 7 & 8: Deterministic Replay & Frictions (AT-31 to AT-37)

def test_at_31_to_37_deterministic_evaluation_loop_and_frictions():
    manifest = ExperimentManifest(
        strategy_id="SMA_CROSSOVER",
        dataset_id="NSE_DAILY_V1",
        timeframe="1d",
        start_date="2024-01-01",
        end_date="2024-06-30",
        initial_capital=100000.0,
        friction_config=FrictionConfig(
            brokerage_per_order=20.0,
            fixed_tick_slippage_pts=0.05,
            variable_slippage_pct=0.0,
        ),
        partitions=create_disjoint_partitions("2024-01-01", "2024-06-30"),
    )

    engine = DeterministicEvaluationEngine(manifest)
    bars = create_sample_bars(100)
    signals = [
        {"bar_index": 10, "side": "BUY", "quantity": 10},
        {"bar_index": 30, "side": "SELL", "quantity": 10},
    ]

    res1 = engine.evaluate_bar_series(bars, signals)
    res2 = engine.evaluate_bar_series(bars, signals)

    # AT-31: Re-execution Determinism
    assert res1.final_equity == res2.final_equity
    assert res1.total_net_return == res2.total_net_return
    assert res1.total_friction_cost == res2.total_friction_cost
    assert len(res1.trades) == len(res2.trades)
    assert res1.trades[0].fill_price == res2.trades[0].fill_price

    # AT-34 & AT-37: Statutory Indian Cost Inclusion & Cost Engine Equivalence
    trade = res1.trades[0]
    assert trade.transaction_cost > 0.0
    assert trade.slippage_pts == 0.05

    # AT-35: Brokerage Cost Sensitivity
    high_friction_manifest = ExperimentManifest(
        strategy_id="SMA_CROSSOVER",
        dataset_id="NSE_DAILY_V1",
        timeframe="1d",
        start_date="2024-01-01",
        end_date="2024-06-30",
        initial_capital=100000.0,
        friction_config=FrictionConfig(
            brokerage_per_order=100.0,  # 5x higher brokerage
            fixed_tick_slippage_pts=0.05,
        ),
        partitions=create_disjoint_partitions("2024-01-01", "2024-06-30"),
    )
    high_engine = DeterministicEvaluationEngine(high_friction_manifest)
    high_res = high_engine.evaluate_bar_series(bars, signals)

    assert high_res.total_friction_cost > res1.total_friction_cost
    assert high_res.total_net_return < res1.total_net_return


# Area 9, 10, 11: Analytics & Undefined Metric Integrity (AT-38 to AT-53)

def test_at_38_to_53_analytics_and_undefined_metric_guards():
    base_ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    equity_curve = [
        (base_ts + timedelta(days=i), 100000.0 + i * 500.0)
        for i in range(10)
    ]

    # AT-46: Empty Trade Set Integrity
    empty_metrics = PerformanceAnalytics.calculate_metrics(equity_curve, trades=[])
    assert empty_metrics.is_empty_trade_set is True
    assert empty_metrics.win_rate is None
    assert empty_metrics.profit_factor is None
    assert empty_metrics.total_trades == 0

    # Test with trade set
    class MockTrade:
        def __init__(self, side, pnl, fill_price=100.0, qty=10):
            self.side = side
            self.pnl = pnl
            self.fill_price = fill_price
            self.quantity = qty

    trades = [
        MockTrade("BUY", 1000.0),
        MockTrade("SELL", -500.0),
        MockTrade("BUY", 1500.0),
    ]

    metrics = PerformanceAnalytics.calculate_metrics(equity_curve, trades=trades)

    # AT-38: Total Return Accuracy
    assert metrics.total_return == pytest.approx(0.045, abs=1e-3)  # (104500 - 100000)/100000

    # AT-44: Win Rate
    assert metrics.total_trades == 3
    assert metrics.winning_trades == 2
    assert metrics.losing_trades == 1
    assert metrics.win_rate == pytest.approx(0.6667, abs=1e-3)

    # AT-49: Profit Factor
    assert metrics.profit_factor == pytest.approx(2500.0 / 500.0, abs=1e-3)  # 5.0


def test_at_45_zero_losing_trades_handling():
    base_ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    equity_curve = [(base_ts, 100000.0), (base_ts + timedelta(days=1), 105000.0)]

    class MockWinTrade:
        side = "BUY"
        pnl = 5000.0
        fill_price = 100.0
        quantity = 10

    metrics = PerformanceAnalytics.calculate_metrics(equity_curve, trades=[MockWinTrade()])
    assert metrics.losing_trades == 0
    assert metrics.profit_factor == float('inf')


# Area 12: Sensitivity Analysis & Friction Sweeps (AT-54 to AT-58)

def test_at_54_to_58_sensitivity_sweeps():
    manifest = ExperimentManifest(
        strategy_id="TREND_FOLLOWING",
        dataset_id="NSE_DAILY_V1",
        timeframe="1d",
        start_date="2024-01-01",
        end_date="2024-06-30",
        initial_capital=100000.0,
        friction_config=FrictionConfig(
            brokerage_per_order=20.0,
            fixed_tick_slippage_pts=0.05,
        ),
        partitions=create_disjoint_partitions("2024-01-01", "2024-06-30"),
    )

    bars = create_sample_bars(100)
    signals = [
        {"bar_index": 5, "side": "BUY", "quantity": 10},
        {"bar_index": 25, "side": "SELL", "quantity": 10},
    ]

    sensitivity = SensitivityEngine(manifest)
    report = sensitivity.run_stress_sweep(bars, signals)

    assert report.base_result.scenario_name == "BASE"
    assert len(report.stress_scenarios) == 5
    assert report.is_monotonic_degradation is True
    # AT-58: No autonomous strategy selection
    assert report.autonomous_deployment_blocked is True


# Area 13: Market Regime Classification (AT-59 to AT-61)

def test_at_59_to_61_market_regime_classification():
    # AT-61: Low observation regime guard (< 20 bars)
    short_series = [100.0 + i for i in range(15)]
    regime_short = HistoricalRegimeClassifier.classify_slice(short_series)
    assert regime_short == MarketRegime.INSUFFICIENT_EVIDENCE

    # Bull regime (>20 bars, positive trend)
    bull_series = [100.0 + i * 2.0 for i in range(30)]
    regime_bull = HistoricalRegimeClassifier.classify_slice(bull_series)
    assert regime_bull == MarketRegime.BULL

    # Bear regime (>20 bars, negative trend)
    bear_series = [200.0 - i * 2.0 for i in range(30)]
    regime_bear = HistoricalRegimeClassifier.classify_slice(bear_series)
    assert regime_bear == MarketRegime.BEAR

    # AT-60: Look-ahead guard in regime classifier
    with pytest.raises(LookAheadBiasError, match="Look-ahead access attempt"):
        HistoricalRegimeClassifier.classify_slice(bull_series, current_index=35)


# Area 14 & 15: Out-of-Sample Degradation & Audit Provenance (AT-62 to AT-78, AT-86 to AT-90)

def test_at_62_to_90_degradation_and_audit_manifests():
    base_ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    eq_curve = [(base_ts + timedelta(days=i), 100000.0 + i * 100.0) for i in range(50)]

    class MockTrade:
        side = "BUY"
        pnl = 100.0
        fill_price = 100.0
        quantity = 10

    is_trades = [MockTrade() for _ in range(40)]
    oos_trades_insufficient = [MockTrade() for _ in range(10)]  # < 30 trades

    is_metrics = PerformanceAnalytics.calculate_metrics(eq_curve, is_trades)
    oos_metrics_insufficient = PerformanceAnalytics.calculate_metrics(eq_curve, oos_trades_insufficient)

    # AT-66: Insufficient OOS trades flag
    deg_summary = EvidenceClassifier.evaluate_degradation(is_metrics, oos_metrics_insufficient)
    assert deg_summary.evidence_status == EvidenceStatus.INSUFFICIENT_EVIDENCE

    # Markdown Report Generation (AT-86 to AT-90)
    manifest = ExperimentManifest(
        strategy_id="MOMENTUM_V1",
        dataset_id="NSE_DAILY_V1",
        timeframe="1d",
        start_date="2024-01-01",
        end_date="2024-06-30",
        initial_capital=100000.0,
        partitions=create_disjoint_partitions("2024-01-01", "2024-06-30"),
    )

    report = ResearchReportGenerator.render_markdown_report(
        manifest=manifest,
        dataset_sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        is_metrics=is_metrics,
        oos_metrics=oos_metrics_insufficient,
        degradation=deg_summary,
    )

    assert "INSUFFICIENT_EVIDENCE" in report
    assert "Methodological Limitations & Caveats" in report
