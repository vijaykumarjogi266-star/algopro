"""Tests verifying data, strategy, backtest, and risk contracts."""

from datetime import datetime, timezone, timedelta
import pytest
from pydantic import ValidationError

from data.schemas.contracts import (
    DataQualityStatus,
    Exchange,
    OHLCVBar,
    TimeFrame,
)
from services.data_quality.validator import DataQualityValidator
from quant.indicators.base import SMA, RSI, ATR
from quant.strategies.base import BaseStrategy, SignalType, StrategyDecision
from services.risk_engine.contracts import HardRiskLimits
from services.backtest_engine.contracts import (
    BacktestMetrics,
    CostModelConfig,
    OrderSide,
    SlippageModelConfig,
    TradeRecord,
)


def test_ohlcv_bar_valid():
    bar = OHLCVBar(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        timeframe=TimeFrame.M5,
        market_timestamp=datetime.now(timezone.utc),
        open=2500.0,
        high=2520.0,
        low=2495.0,
        close=2510.0,
        volume=10000.0,
    )
    assert bar.symbol == "RELIANCE"
    assert bar.is_usable_for_trading() is True


def test_ohlcv_bar_invalid_math():
    # High lower than open should fail validation
    with pytest.raises(ValidationError):
        OHLCVBar(
            symbol="TCS",
            exchange=Exchange.NSE,
            timeframe=TimeFrame.M5,
            market_timestamp=datetime.now(timezone.utc),
            open=3500.0,
            high=3400.0,  # Invalid: high < open
            low=3300.0,
            close=3350.0,
            volume=5000.0,
        )


def test_data_quality_validator_detects_duplicates_and_ordering():
    now = datetime.now(timezone.utc)
    bars = [
        OHLCVBar(
            symbol="INFY",
            exchange=Exchange.NSE,
            timeframe=TimeFrame.M5,
            market_timestamp=now,
            open=1500.0,
            high=1510.0,
            low=1490.0,
            close=1505.0,
            volume=1000.0,
        ),
        OHLCVBar(
            symbol="INFY",
            exchange=Exchange.NSE,
            timeframe=TimeFrame.M5,
            market_timestamp=now,  # Duplicate timestamp
            open=1505.0,
            high=1515.0,
            low=1500.0,
            close=1510.0,
            volume=1200.0,
        ),
    ]
    validator = DataQualityValidator()
    report = validator.validate_series(bars)
    assert report.has_critical_failures is True
    assert report.overall_status == DataQualityStatus.REJECTED


def test_sma_deterministic_computation():
    import numpy as np

    sma = SMA(period=3)
    closes = np.array([10.0, 20.0, 30.0, 40.0, 50.0])
    result = sma.calculate(closes)
    assert np.isnan(result[0])
    assert np.isnan(result[1])
    assert np.isclose(result[2], 20.0)
    assert np.isclose(result[3], 30.0)
    assert np.isclose(result[4], 40.0)


def test_rsi_evidence_principle():
    import numpy as np

    rsi = RSI(period=14)
    # 20 closes
    closes = np.linspace(100, 120, 20)
    result = rsi.calculate(closes)
    evidence = rsi.get_evidence(result)
    assert evidence["indicator"] == "RSI"
    assert evidence["is_evidence_only"] is True  # Principle 11 & 12


def test_strategy_wait_decision():
    class DummyStrategy(BaseStrategy):
        def evaluate(self, current_bar, history, data_quality):
            return self.default_wait(current_bar.symbol, current_bar.market_timestamp, "Testing WAIT state")

    strat = DummyStrategy(strategy_id="test_strat", name="Test", version="1.0.0")
    now = datetime.now(timezone.utc)
    bar = OHLCVBar(
        symbol="HDFCBANK",
        exchange=Exchange.NSE,
        timeframe=TimeFrame.M5,
        market_timestamp=now,
        open=1600.0,
        high=1610.0,
        low=1590.0,
        close=1605.0,
        volume=2000.0,
    )
    decision = strat.evaluate(bar, [bar], None)
    assert decision.signal == SignalType.WAIT  # Principle 2
    assert decision.confidence == 0.0


def test_hard_risk_limits_bounds():
    limits = HardRiskLimits()
    assert limits.max_leverage == 1.0  # Stage 1: No margin leverage
    assert limits.enforce_mandatory_stop_loss is True


def test_trade_record_cost_attribution():
    now = datetime.now(timezone.utc)
    record = TradeRecord(
        trade_id="TR-001",
        symbol="SBIN",
        strategy_id="orb_strategy",
        strategy_version="1.0.0",
        side=OrderSide.BUY,
        entry_timestamp=now - timedelta(hours=1),
        exit_timestamp=now,
        entry_price=750.0,
        exit_price=760.0,
        quantity=100,
        gross_pnl=1000.0,
        costs=24.50,
        slippage=10.0,
        net_pnl=965.50,
        holding_time_seconds=3600.0,
        entry_reason="ORB 15-min high breakout with volume expansion",
        exit_reason="Target R:R 1:2 achieved",
    )
    assert record.net_pnl == record.gross_pnl - record.costs - record.slippage


def test_ema_deterministic_computation():
    import numpy as np
    from quant.indicators.base import EMA

    ema = EMA(period=3)
    closes = np.array([10.0, 10.0, 10.0, 20.0, 30.0])
    result = ema.calculate(closes)
    assert np.isnan(result[0])
    assert np.isnan(result[1])
    assert np.isclose(result[2], 10.0)
    assert result[3] > 10.0


def test_atr_deterministic_computation():
    import numpy as np
    from quant.indicators.base import ATR

    atr = ATR(period=2)
    closes = np.array([100.0, 105.0, 102.0])
    highs = np.array([102.0, 107.0, 104.0])
    lows = np.array([99.0, 104.0, 100.0])
    result = atr.calculate(closes, highs=highs, lows=lows)
    assert np.isnan(result[0])
    assert not np.isnan(result[1])
    assert result[1] > 0


def test_paper_order_creation_and_fill():
    from services.paper_engine.contracts import PaperOrder, PaperFill, PaperOrderStatus
    from services.backtest_engine.contracts import OrderSide, OrderType

    order = PaperOrder(
        symbol="TCS",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=10,
        stop_loss=3400.0,
        target_price=3600.0,
    )
    assert order.status == PaperOrderStatus.PENDING
    assert order.quantity == 10

    fill = PaperFill(
        order_id=order.order_id,
        symbol=order.symbol,
        side=order.side,
        quantity=order.quantity,
        fill_price=3500.25,
        slippage=0.25,
        commission=20.0,
    )
    assert fill.fill_price == 3500.25
    assert fill.commission == 20.0
