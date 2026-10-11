"""
Unit tests for Algo Lab Live/Paper Broker Adapter Integration.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

from services.broker_integration import LiveBrokerAdapter

class TestBrokerIntegration(unittest.TestCase):
    def test_broker_connection_and_order(self):
        adapter = LiveBrokerAdapter(broker_name="TestBroker")
        # Test auth failure
        self.assertFalse(adapter.connect("", ""))
        
        # Test successful connection
        self.assertTrue(adapter.connect("key", "secret"))
        
        # Test order placement
        receipt = adapter.place_order("TCS.NS", 5, 3400.0)
        self.assertEqual(receipt["status"], "FILLED")
        self.assertEqual(receipt["symbol"], "TCS.NS")
        self.assertEqual(receipt["quantity"], 5)

if __name__ == "__main__":
    unittest.main()
