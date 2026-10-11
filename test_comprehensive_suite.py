import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from services.broker_integration import LiveBrokerAdapter
from data.schemas.contracts import OHLCVBar, TimeFrame, Exchange, DataQualityStatus
from datetime import datetime, timezone

class TestAlgoLabCoreSuite(unittest.TestCase):

    def test_broker_adapter_comprehensive(self):
        adapter = LiveBrokerAdapter("ComprehensiveBroker")
        self.assertFalse(adapter.connect("", ""))
        self.assertTrue(adapter.connect("valid_key", "valid_secret"))
        
        receipt = adapter.place_order("INFY.NS", 25, 1500.0)
        self.assertEqual(receipt["status"], "FILLED")
        self.assertEqual(receipt["quantity"], 25)
        self.assertEqual(receipt["symbol"], "INFY.NS")

    def test_ohlcv_bar_schema(self):
        bar = OHLCVBar(
            symbol="RELIANCE.NS",
            exchange=Exchange.NSE,
            timeframe=TimeFrame.D1,
            market_timestamp=datetime.now(timezone.utc),
            open=1200.0, high=1220.0, low=1190.0, close=1210.0,
            volume=100000,
            quality_status=DataQualityStatus.VALID
        )
        self.assertEqual(bar.symbol, "RELIANCE.NS")
        self.assertEqual(bar.quality_status, DataQualityStatus.VALID)

if __name__ == "__main__":
    unittest.main()
