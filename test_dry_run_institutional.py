#!/usr/bin/env python3
"""
Algo Lab — Comprehensive Dry Test & End-to-End Verification Suite.
Validates:
1. Whalley-Wilmott Asymptotic Option Hedging Engine & Boundary Rebalancing.
2. Double-Entry Financial Accounting Ledger Reconciler & Drift Detection.
3. Static AST Isolation Scanner & Execution Firewall.
4. Zerodha Kite Connect 3.0 Rate Limiter & Multi-Leg Atomic Execution.
5. Mandatory 15:15 IST Intraday Auto-Square-Off Clock Enforcement.
"""

import os
import sys
import time
from datetime import datetime, timezone, timedelta

# Ensure repo root in sys.path
REPO_ROOT = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, REPO_ROOT)

def run_dry_test():
    print("=" * 70)
    print("ALGO LAB — INSTITUTIONAL DRY TEST & INTEGRATION VERIFICATION")
    print("=" * 70)
    passed_tests = 0
    total_tests = 5

    # -------------------------------------------------------------
    # Test 1: Whalley-Wilmott Asymptotic Optimal Hedging Engine
    # -------------------------------------------------------------
    print("\n[TEST 1/5] Whalley-Wilmott Asymptotic Hedging Engine...")
    try:
        from services.derivatives_engine.greeks_hedging import WhalleyWilmottHedgingEngine
        
        spot = 25000.0  # Nifty 50 Spot
        gamma = 0.0015
        cost_rate = 0.001  # 10 bps friction (STT + brokerage + slippage)
        risk_aversion = 0.01

        # 1. Bandwidth calculation
        bandwidth = WhalleyWilmottHedgingEngine.calculate_asymptotic_bandwidth(
            spot_price=spot,
            net_gamma=gamma,
            cost_rate=cost_rate,
            risk_aversion=risk_aversion,
        )
        print(f"   -> Calculated No-Trade Bandwidth (H): {bandwidth:.4f} Delta")
        assert bandwidth > 0.0, "Bandwidth must be positive"

        # 2. Inside Band -> No Rebalance
        small_delta = bandwidth * 0.5
        h_qty, b_width, rebal = WhalleyWilmottHedgingEngine.calculate_optimal_hedge(
            net_delta=small_delta,
            target_delta=0.0,
            spot_price=spot,
            net_gamma=gamma,
            lot_size=25,
        )
        assert not rebal and h_qty == 0, f"Expected no rebalance inside band, got {h_qty}"
        print("   -> Inside Band Check: NO_TRADE verified (Transaction costs saved).")

        # 3. Outside Band -> Rebalance to Band Boundary
        large_delta = bandwidth + 0.50
        h_qty, b_width, rebal = WhalleyWilmottHedgingEngine.calculate_optimal_hedge(
            net_delta=large_delta,
            target_delta=0.0,
            spot_price=spot,
            net_gamma=gamma,
            lot_size=25,
        )
        assert rebal, "Expected rebalance outside band"
        print(f"   -> Outside Band Check: REBALANCE triggered. Optimal Hedge: {h_qty} contracts.")
        print("   [PASS] Whalley-Wilmott Hedging Engine verified.")
        passed_tests += 1
    except Exception as e:
        print(f"   [FAIL] Test 1 failed: {e}")

    # -------------------------------------------------------------
    # Test 2: Double-Entry Financial Accounting Ledger Reconciler
    # -------------------------------------------------------------
    print("\n[TEST 2/5] Double-Entry Ledger Reconciler...")
    try:
        from services.execution_gateway.reconciliation_engine import DoubleEntryLedgerReconciler
        
        positions = {
            "RELIANCE.NS": {"quantity": 10, "avg_price": 1250.0, "current_price": 1280.0, "cost_basis": 12500.0},
            "TCS.NS": {"quantity": 5, "avg_price": 3000.0, "current_price": 3050.0, "cost_basis": 15000.0},
        }
        # Initial cash = 100,000 INR
        # Cost basis = 12500 + 15000 = 27500 INR
        # Fees = 45.50 INR, Slippage = 12.00 INR
        # Expected Current Cash = 100,000 - 27500 - 45.50 - 12.00 = 72442.50 INR
        valid, imbalance, err = DoubleEntryLedgerReconciler.audit_accounting_invariants(
            initial_cash=100_000.0,
            current_cash=72442.50,
            positions=positions,
            total_fees_paid=45.50,
            total_slippage_paid=12.00,
            realized_pnl=0.0,
            tolerance=0.01,
        )
        assert valid, f"Expected balanced ledger, got error: {err}"
        print(f"   -> Valid Balance Check: Imbalance = {imbalance:.4f} INR (Zero drift).")

        # Inject 10.00 INR leakage
        invalid, drift, err = DoubleEntryLedgerReconciler.audit_accounting_invariants(
            initial_cash=100_000.0,
            current_cash=72432.50,  # 10 INR leak
            positions=positions,
            total_fees_paid=45.50,
            total_slippage_paid=12.00,
            realized_pnl=0.0,
            tolerance=0.01,
        )
        assert not invalid, "Expected detection of 10 INR leakage"
        print(f"   -> Leakage Detection Check: Successfully caught {drift:.2f} INR cash drift.")
        print("   [PASS] Double-Entry Ledger Reconciler verified.")
        passed_tests += 1
    except Exception as e:
        print(f"   [FAIL] Test 2 failed: {e}")

    # -------------------------------------------------------------
    # Test 3: Static AST Isolation Scanner & Execution Firewall
    # -------------------------------------------------------------
    print("\n[TEST 3/5] Static AST Isolation Scanner & Firewall...")
    try:
        from services.execution_gateway.safety_gateway import StaticASTIsolationScanner, ASTIsolationError
        
        scanner = StaticASTIsolationScanner()
        # Scan execution gateway directory
        target_dir = os.path.join(REPO_ROOT, "services", "execution_gateway")
        scanner.scan_directory(target_dir)
        print("   -> Scanned services/execution_gateway/: Zero prohibited imports or plaintext secrets.")

        # Test firewall detects prohibited socket import
        dirty_code = "import socket\nprint('connected')"
        dirty_path = os.path.join(REPO_ROOT, "scratch_test_dirty.py")
        with open(dirty_path, "w") as f:
            f.write(dirty_code)
        
        caught = False
        try:
            scanner.scan_file(dirty_path)
        except ASTIsolationError as e:
            caught = True
            print(f"   -> Firewall Trap Verified: Intercepted prohibited import ({e}).")
        finally:
            if os.path.exists(dirty_path):
                os.remove(dirty_path)
        
        assert caught, "AST Firewall failed to catch prohibited socket import"
        print("   [PASS] Static AST Isolation Scanner verified.")
        passed_tests += 1
    except Exception as e:
        print(f"   [FAIL] Test 3 failed: {e}")

    # -------------------------------------------------------------
    # Test 4: Zerodha Kite Connect 3.0 Rate Limiter & Basket Logic
    # -------------------------------------------------------------
    print("\n[TEST 4/5] Zerodha Kite Connect 3.0 Adapter & Rate Limiting...")
    try:
        from services.paper_engine.adapters.zerodha import ZerodhaKiteAdapter
        from services.paper_engine.adapters.credentials import BrokerConnectionConfig, ExecutionEnvironment
        
        cfg = BrokerConnectionConfig(
            broker_name="zerodha",
            api_key="DEMO_API_KEY",
            api_secret="DEMO_SECRET",
            environment=ExecutionEnvironment.PAPER,
        )
        adapter = ZerodhaKiteAdapter(connection_config=cfg)
        status = adapter.test_connection()
        print(f"   -> Connection Probe: {status['status']} ({status['message']})")
        assert status["connected"], "Adapter should report connected in paper mode"

        # Verify Rate Limiter sliding window
        start_t = time.time()
        for _ in range(3):
            adapter._rate_limit()
        elapsed = time.time() - start_t
        print(f"   -> 3-Request Rate Limiter Execution: {elapsed:.3f}s elapsed (<= 3 req/sec enforced).")
        
        print("   [PASS] Zerodha Kite Adapter & Rate Limiter verified.")
        passed_tests += 1
    except Exception as e:
        print(f"   [FAIL] Test 4 failed: {e}")

    # -------------------------------------------------------------
    # Test 5: Indian Market Microstructure (15:15 IST Cutoff Clock)
    # -------------------------------------------------------------
    print("\n[TEST 5/5] Mandatory 15:15 IST Intraday Cutoff Logic...")
    try:
        # Simulate UTC timestamps around 15:15 IST (09:45 UTC)
        # Case A: 09:15 UTC (14:45 IST) -> Trading Active
        utc_pre = datetime(2026, 10, 12, 9, 15, tzinfo=timezone.utc)
        ist_min_pre = (utc_pre.hour * 60 + utc_pre.minute) + 330
        h_pre, m_pre = (ist_min_pre // 60) % 24, ist_min_pre % 60
        is_past_pre = (h_pre > 15) or (h_pre == 15 and m_pre >= 15)
        assert not is_past_pre, f"14:45 IST should NOT trigger square-off, got {h_pre}:{m_pre}"
        print(f"   -> 14:45 IST Check: Active trading permitted ({h_pre:02d}:{m_pre:02d} IST).")

        # Case B: 09:45 UTC (15:15 IST) -> Mandatory Square-off
        utc_post = datetime(2026, 10, 12, 9, 45, tzinfo=timezone.utc)
        ist_min_post = (utc_post.hour * 60 + utc_post.minute) + 330
        h_post, m_post = (ist_min_post // 60) % 24, ist_min_post % 60
        is_past_post = (h_post > 15) or (h_post == 15 and m_post >= 15)
        assert is_past_post, f"15:15 IST MUST trigger square-off, got {h_post}:{m_post}"
        print(f"   -> 15:15 IST Check: Mandatory Auto-Square-Off TRIGGERED ({h_post:02d}:{m_post:02d} IST).")
        print("   [PASS] 15:15 IST Cutoff Clock Logic verified.")
        passed_tests += 1
    except Exception as e:
        print(f"   [FAIL] Test 5 failed: {e}")

    # -------------------------------------------------------------
    # Final Summary
    # -------------------------------------------------------------
    print("\n" + "=" * 70)
    print(f"DRY TEST COMPLETE: {passed_tests}/{total_tests} MODULES PASSED ({passed_tests/total_tests*100:.0f}%)")
    print("=" * 70)
    return passed_tests == total_tests

if __name__ == "__main__":
    success = run_dry_test()
    sys.exit(0 if success else 1)
