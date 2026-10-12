"""Tests for Algo Lab Enhancements:
1. Market Data LRU Cache & Persistence
2. Observability & Alerting Engine
3. Continuous Risk Auditing & Pluggable Risk Signal Hooks
"""

from datetime import datetime, timezone
import unittest
import numpy as np
import polars as pl

from data.schemas.contracts import Exchange, TimeFrame
from services.market_data.cache import LRUMarketDataCache
from services.observability.metrics import MetricsCollector
from services.observability.alerts import (
    ObservabilityAlertEngine,
    AlertRule,
    AlertSeverity,
)
from services.risk_engine.audit import ContinuousRiskAuditor, AuditComplianceStatus
from services.risk_engine.hooks import ValueAtRiskFilter, ExpectedShortfallFilter
from services.risk_engine.contracts import HardRiskLimits, RiskRejectionCode
from services.risk_engine.engine import RiskEngine


class TestEnhancementsSuite(unittest.TestCase):

    # -------------------------------------------------------------
    # 1. Market Data LRU Cache Tests
    # -------------------------------------------------------------
    def test_lru_market_data_cache_basic_and_eviction(self):
        cache = LRUMarketDataCache(max_entries=2)

        df1 = pl.DataFrame({"close": [100.0, 101.0]})
        df2 = pl.DataFrame({"close": [200.0, 202.0]})
        df3 = pl.DataFrame({"close": [300.0, 303.0]})

        cache.put(Exchange.NSE, TimeFrame.H1, "RELIANCE", 2026, df1)
        cache.put(Exchange.NSE, TimeFrame.H1, "TCS", 2026, df2)

        # Cache hit
        retrieved1 = cache.get(Exchange.NSE, TimeFrame.H1, "RELIANCE", 2026)
        self.assertIsNotNone(retrieved1)
        self.assertEqual(retrieved1["close"][0], 100.0)

        # Insert 3rd item: TCS should be evicted because RELIANCE was accessed more recently
        cache.put(Exchange.NSE, TimeFrame.H1, "INFY", 2026, df3)

        self.assertIsNone(cache.get(Exchange.NSE, TimeFrame.H1, "TCS", 2026))
        self.assertIsNotNone(cache.get(Exchange.NSE, TimeFrame.H1, "RELIANCE", 2026))
        self.assertIsNotNone(cache.get(Exchange.NSE, TimeFrame.H1, "INFY", 2026))

        stats = cache.stats
        self.assertEqual(stats["size"], 2)
        self.assertGreater(stats["hits"], 0)
        self.assertGreater(stats["misses"], 0)

    # -------------------------------------------------------------
    # 2. Observability & Alerting Tests
    # -------------------------------------------------------------
    def test_observability_alert_engine(self):
        engine = ObservabilityAlertEngine()
        rule = AlertRule(
            name="high_latency",
            metric_name="order_latency",
            threshold=0.25,
            operator=">",
            severity=AlertSeverity.CRITICAL,
            description="Order execution latency exceeded 250ms",
        )
        engine.register_rule(rule)

        # Normal value: no alert
        alerts = engine.evaluate_metric("order_latency", 0.10)
        self.assertEqual(len(alerts), 0)

        # Spiked value: triggers alert
        alerts = engine.evaluate_metric("order_latency", 0.45, metadata={"broker": "Zerodha"})
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].severity, AlertSeverity.CRITICAL)
        self.assertIn("Threshold breached", alerts[0].message)
        self.assertEqual(len(engine.alerts_history), 1)

    def test_metrics_collector(self):
        # Verify MetricsCollector records without error
        MetricsCollector.record_pipeline_lag("NSE_TICK", 0.05)
        MetricsCollector.record_order_latency("MockBroker", "LIMIT", 0.02)
        MetricsCollector.record_risk_rejection("EXCEEDS_MAX_CAPITAL", "RELIANCE")
        MetricsCollector.record_slippage_variance("INFY", "NSE", 2.5)

    # -------------------------------------------------------------
    # 3. Continuous Risk Audit Tests
    # -------------------------------------------------------------
    def test_continuous_risk_auditor_compliance_and_breach(self):
        limits = HardRiskLimits(
            max_daily_loss_pct=0.03,
            max_portfolio_drawdown_pct=0.08,
            max_capital_per_trade_pct=0.20,
            max_open_positions=5,
        )
        auditor = ContinuousRiskAuditor(limits=limits)

        # Test Compliant State
        report_ok = auditor.audit_portfolio(
            portfolio_equity=1_000_000.0,
            realized_daily_loss_pct=0.01,
            current_drawdown_pct=0.02,
            open_positions=[{"symbol": "TCS", "market_value": 150_000.0}],
        )
        self.assertEqual(report_ok.status, AuditComplianceStatus.COMPLIANT)
        self.assertEqual(len(report_ok.violations), 0)

        # Test Breached State (Excessive drawdown + concentration)
        report_breached = auditor.audit_portfolio(
            portfolio_equity=1_000_000.0,
            realized_daily_loss_pct=0.035,  # Breached 3%
            current_drawdown_pct=0.09,      # Breached 8%
            open_positions=[{"symbol": "RELIANCE", "market_value": 300_000.0}],  # 30% > 20%
        )
        self.assertEqual(report_breached.status, AuditComplianceStatus.BREACHED)
        self.assertGreaterEqual(len(report_breached.violations), 3)

    # -------------------------------------------------------------
    # 4. Pluggable Risk Signal Hooks Tests
    # -------------------------------------------------------------
    def test_var_and_expected_shortfall_hooks(self):
        var_filter = ValueAtRiskFilter(confidence_level=0.95, max_var_pct=0.03)
        cvar_filter = ExpectedShortfallFilter(confidence_level=0.95, max_cvar_pct=0.05)

        engine = RiskEngine(hooks=[var_filter, cvar_filter])

        # Mild historical returns: normal distribution with small variance
        np.random.seed(42)
        safe_returns = list(np.random.normal(0.001, 0.008, 100))

        approved_res = engine.evaluate(
            symbol="INFY",
            price=1500.0,
            proposed_quantity=10,
            stop_loss=1450.0,
            current_portfolio_value=1_000_000.0,
            current_daily_loss_pct=0.005,
            current_drawdown_pct=0.01,
            current_open_positions_count=1,
            context={"historical_returns": safe_returns},
        )
        self.assertTrue(approved_res.is_approved)

        # Severe negative tail returns (extreme left tail distribution)
        crash_returns = list(np.random.normal(-0.05, 0.08, 100))

        rejected_res = engine.evaluate(
            symbol="INFY",
            price=1500.0,
            proposed_quantity=100,  # 150k on 1m
            stop_loss=1450.0,
            current_portfolio_value=1_000_000.0,
            current_daily_loss_pct=0.005,
            current_drawdown_pct=0.01,
            current_open_positions_count=1,
            context={"historical_returns": crash_returns},
        )
        self.assertFalse(rejected_res.is_approved)
        self.assertEqual(rejected_res.rejection_code, RiskRejectionCode.EXCEEDS_MAX_CAPITAL)
        self.assertIn("exceeds", rejected_res.rejection_reason.lower())


    # -------------------------------------------------------------
    # 5. Zerodha Kite Connect 3.0 Adapter Tests
    # -------------------------------------------------------------
    def test_zerodha_kite_adapter(self):
        from services.paper_engine.adapters.zerodha import ZerodhaKiteAdapter
        from services.paper_engine.adapters.credentials import BrokerConnectionConfig, ExecutionEnvironment

        config = BrokerConnectionConfig(
            broker_name="zerodha",
            environment=ExecutionEnvironment.PAPER,
            api_key="kite_test_api_key_12345",
            api_secret="kite_test_secret_67890",
        )
        adapter = ZerodhaKiteAdapter(connection_config=config)

        # Connection health
        conn_res = adapter.test_connection()
        self.assertTrue(conn_res["connected"])
        self.assertEqual(conn_res["status"], "HEALTHY")
        self.assertEqual(conn_res["api_version"], "3.0")

        # Session checksum generation
        checksum = adapter.generate_session_checksum("req_tok_abc")
        self.assertEqual(len(checksum), 64)  # SHA-256 is 64 hex characters

        # Margins & positions
        margins = adapter.get_margins()
        self.assertIn("equity", margins)
        self.assertEqual(margins["equity"]["net"], 50000.0)

        positions = adapter.get_positions()
        self.assertIn("net", positions)

    # -------------------------------------------------------------
    # 6. Statistical Significance & Deflated Sharpe Tests
    # -------------------------------------------------------------
    def test_deflated_sharpe_and_psr(self):
        from services.evaluation_engine.stat_metrics import StatisticalMetricsEngine

        np.random.seed(42)
        # Synthetic daily returns with positive drift
        daily_returns = list(np.random.normal(0.0012, 0.015, 252))

        report_single = StatisticalMetricsEngine.evaluate_returns_series(
            daily_returns,
            periods_per_year=252,
            number_of_trials=1,
        )
        self.assertGreater(report_single.annualized_sharpe, 0.5)
        self.assertGreater(report_single.psr, 0.70)
        self.assertGreater(report_single.omega_ratio, 1.0)

        # Deflated Sharpe under 50 trials (multi-testing penalty)
        report_multi = StatisticalMetricsEngine.evaluate_returns_series(
            daily_returns,
            periods_per_year=252,
            number_of_trials=50,
            var_trials=0.15,
        )
        self.assertLess(report_multi.dsr, report_multi.psr)
        self.assertGreater(report_multi.expected_max_sharpe, 0.0)

    # -------------------------------------------------------------
    # 7. Factor Research & Rank IC Tests
    # -------------------------------------------------------------
    def test_factor_research_and_rank_ic(self):
        from services.evaluation_engine.factor_research import FactorResearchEngine

        # Panel of 5 symbols across 10 evaluation dates
        symbols = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "SBIN"]
        panel = []
        for d in range(10):
            # Perfect predictive synthetic factor (factor strongly predicts forward return)
            factors = {s: float(i + 1) for i, s in enumerate(symbols)}
            fwd_returns = {s: float((i + 1) * 0.01) for i, s in enumerate(symbols)}
            panel.append((f"2026-01-{d+1:02d}", factors, fwd_returns))

        report = FactorResearchEngine.evaluate_factor_panel(
            panel,
            factor_name="Test_Momentum_Factor",
            periods_per_year=252,
        )
        self.assertEqual(report.factor_name, "Test_Momentum_Factor")
        self.assertAlmostEqual(report.mean_rank_ic, 1.0, places=2)
        self.assertTrue(report.is_monotonic)
        self.assertGreater(report.long_short_spread, 0.0)

    # -------------------------------------------------------------
    # 8. Indian Exchange Microstructure & Statutory Costs Tests
    # -------------------------------------------------------------
    def test_indian_microstructure_and_costs(self):
        from datetime import datetime, time
        from services.market_data.indian_microstructure import (
            IndianMicrostructureEngine,
            IndianProductType,
            IndianExchange,
        )

        # Pre-open session rejection
        pre_open_dt = datetime(2026, 10, 12, 9, 10, 0)
        valid, reason = IndianMicrostructureEngine.validate_execution_time(pre_open_dt)
        self.assertFalse(valid)
        self.assertIn("Pre-open", reason)

        # Normal session approval
        normal_dt = datetime(2026, 10, 12, 10, 30, 0)
        valid_norm, _ = IndianMicrostructureEngine.validate_execution_time(normal_dt)
        self.assertTrue(valid_norm)

        # Circuit limit rejection
        circuit_status = IndianMicrostructureEngine.evaluate_circuit_limits(
            symbol="RELIANCE.NS",
            current_price=1200.0,
            previous_close=1000.0,
            circuit_band_pct=0.20,
            side="BUY",
        )
        self.assertTrue(circuit_status.is_at_upper_circuit)
        self.assertFalse(circuit_status.can_buy)
        self.assertIn("Upper Circuit", circuit_status.rejection_reason)

        # Statutory costs: CNC vs MIS
        cnc_cost = IndianMicrostructureEngine.calculate_statutory_costs(
            side="BUY", price=1000.0, quantity=100, product=IndianProductType.CNC
        )
        mis_cost = IndianMicrostructureEngine.calculate_statutory_costs(
            side="BUY", price=1000.0, quantity=100, product=IndianProductType.MIS
        )
        # CNC STT is higher than MIS buy (0 STT on intraday buy)
        self.assertGreater(cnc_cost.stt, mis_cost.stt)
        self.assertGreater(cnc_cost.total_cost, mis_cost.total_cost)

    # -------------------------------------------------------------
    # 9. Institutional Tearsheet Generator Tests
    # -------------------------------------------------------------
    def test_tearsheet_generator(self):
        from services.evaluation_engine.tearsheet import TearsheetGenerator

        # Simulated upward trending equity curve
        equity_curve = [10000.0 * (1.0 + (i * 0.005)) for i in range(50)]
        trades = [{"pnl": 150.0}, {"pnl": -50.0}, {"pnl": 200.0}]

        sheet = TearsheetGenerator.generate_tearsheet(
            strategy_id="strat_institutional_v1",
            equity_curve=equity_curve,
            trades=trades,
            number_of_trials=5,
            var_trials=0.08,
        )
        self.assertEqual(sheet.strategy_id, "strat_institutional_v1")
        self.assertGreater(sheet.total_return, 0.0)
        self.assertGreater(sheet.empirical_sharpe, 0.0)

        rendered_md = TearsheetGenerator.render_markdown_tearsheet(sheet)
        self.assertIn("Institutional Strategy Tearsheet", rendered_md)
        self.assertIn("Deflated Sharpe (DSR)", rendered_md)


if __name__ == "__main__":
    unittest.main()
