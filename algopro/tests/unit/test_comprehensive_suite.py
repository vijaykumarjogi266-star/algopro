import sys
import os
import unittest

# Ensure working directory is added to sys.path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from services.broker_integration import LiveBrokerAdapter
from services.risk_engine.engine import RiskEngine
from services.risk_engine.contracts import HardRiskLimits, RiskRejectionCode
from quant.strategies.vwap_reversion import VWAPReversion
from data.schemas.contracts import OHLCVBar, TimeFrame, Exchange
from datetime import datetime, timezone

class TestAlgoLabComprehensiveSuite(unittest.TestCase):

    def test_broker_adapter_comprehensive(self):
        adapter = LiveBrokerAdapter("ComprehensiveBroker")
        self.assertFalse(adapter.connect("", ""))
        self.assertTrue(adapter.connect("valid_key", "valid_secret"))
        
        receipt = adapter.place_order("INFY.NS", 25, 1500.0)
        self.assertEqual(receipt["status"], "FILLED")
        self.assertEqual(receipt["quantity"], 25)

    def test_risk_engine_safeguards(self):
        engine = RiskEngine(HardRiskLimits(max_capital_per_trade_pct=0.10))
        
        # Test valid order
        result = engine.evaluate(
            symbol="RELIANCE.NS",
            price=1200.0,
            proposed_quantity=5,
            stop_loss=1150.0,
            current_portfolio_value=100000.0,
            current_daily_loss_pct=0.01,
            current_drawdown_pct=0.02,
            current_open_positions_count=2
        )
        self.assertTrue(result.is_approved)

        # Test trade exceeding max capital limit
        result_large = engine.evaluate(
            symbol="RELIANCE.NS",
            price=1200.0,
            proposed_quantity=100,
            stop_loss=1150.0,
            current_portfolio_value=100000.0,
            current_daily_loss_pct=0.01,
            current_drawdown_pct=0.02,
            current_open_positions_count=2
        )
        self.assertFalse(result_large.is_approved)
        self.assertEqual(result_large.rejection_code, RiskRejectionCode.EXCEEDS_MAX_CAPITAL)

    def test_strategy_vwap_signal(self):
        strategy = VWAPReversion(std_dev_threshold=2.0, stop_loss_atr_mult=1.5)
        bar = OHLCVBar(
            symbol="TCS.NS",
            timeframe=TimeFrame.ONE_HOUR,
            market_timestamp=datetime.now(timezone.utc),
            open=3300.0, high=3310.0, low=3250.0, close=3260.0,
            volume=50000, vwap=3300.0, exchange=Exchange.NSE, is_verified=True
        )
        indicators = {"vwap": 3300.0, "vwap_lower": 3270.0, "atr_14": 15.0, "rsi_14": 30.0}
        candidate = strategy.on_bar(bar, [bar], indicators, has_open_position=False)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.symbol, "TCS.NS")

if __name__ == "__main__":
    unittest.main()
