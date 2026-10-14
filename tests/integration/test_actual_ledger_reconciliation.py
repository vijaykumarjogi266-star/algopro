import pytest
from services.paper_engine.autonomous_orchestrator import AutonomousSentinel
from services.execution_gateway.reconciliation_engine import DoubleEntryLedgerReconciler


def test_missing_cash_is_not_substituted_with_equity(tmp_path):
    """
    Test 47: Initial cash 10,000; actual cash 1; no positions, realized PnL, or costs.
    Assert imbalance 9,999, failed reconciliation, persistent entry freeze.
    """
    db_path = str(tmp_path / "paper.db")
    sentinel = AutonomousSentinel(db_path=db_path, initial_capital=10000.0)
    sentinel.daily_starting_equity = 10000.0
    sentinel.is_killswitch_tripped = False

    # Actual cash is 1.0, but portfolio equity is 10000.0 (simulating broken substitution if used)
    # Even if portfolio_equity is passed as 10000.0, cash must NOT be substituted with equity!
    is_reconciled, imbalance, error_reason = sentinel.execute_eod_reconciliation_and_tearsheet(
        portfolio_equity=10000.0,
        open_positions_count=0,
        cash=1.0,
        realized_pnl=0.0,
        total_fees=0.0,
        total_slippage=0.0,
        positions={},
    )

    assert is_reconciled is False
    assert pytest.approx(imbalance, abs=1e-2) == 9999.0
    assert sentinel.is_killswitch_tripped is True, "Discrepancy must trip killswitch (entry freeze)"


def test_explicit_zero_cash_is_preserved(tmp_path):
    """
    Test 48: Assert zero cash is audited as zero, not replaced using truthiness (cash or portfolio_equity).
    """
    db_path = str(tmp_path / "paper.db")
    sentinel = AutonomousSentinel(db_path=db_path, initial_capital=10000.0)
    sentinel.daily_starting_equity = 10000.0

    # With initial cash 10k, open position cost basis 10k, realized pnl 0, fees 0,
    # expected cash is exactly 0.0!
    positions = {
        "INFY": {
            "quantity": 10,
            "avg_price": 1000.0,
            "current_price": 1050.0,
            "cost_basis": 10000.0,
        }
    }
    # Explicit zero cash:
    # If the bug `cash or portfolio_equity` is present, `0.0 or 10500.0` evaluates to 10500.0,
    # which causes an imbalance of 10500.0!
    is_reconciled, imbalance, error_reason = sentinel.execute_eod_reconciliation_and_tearsheet(
        portfolio_equity=10500.0,
        open_positions_count=1,
        cash=0.0,
        realized_pnl=0.0,
        total_fees=0.0,
        total_slippage=0.0,
        positions=positions,
    )

    # When 0.0 is properly preserved, expected cash (0.0) == actual cash (0.0), so is_reconciled is True!
    assert is_reconciled is True, f"Reconciliation failed unexpectedly with error: {error_reason}"
    assert pytest.approx(imbalance, abs=1e-4) == 0.0


def test_valid_flat_and_open_position_ledgers_reconcile(tmp_path):
    """
    Test 49: Use hand-calculated cash, cost bases, realized PnL, and costs.
    Assert pass.
    Alter cash/cost basis beyond tolerance.
    Assert failure.
    Exercise the real daemon-to-reconciler call path.
    """
    db_path = str(tmp_path / "paper.db")
    sentinel = AutonomousSentinel(db_path=db_path, initial_capital=50000.0)
    sentinel.daily_starting_equity = 50000.0

    # Case A: Flat ledger (no open positions, realized trade with fees & slippage)
    # Initial: 50,000. Realized PnL: +1,200. Fees: 45.50. Slippage: 12.25.
    # Canonical Expected Cash: 50000 + 1200 - 45.50 = 51154.50 (slippage is attribution only)
    flat_cash = 51154.50
    is_rec, imb, err = sentinel.execute_eod_reconciliation_and_tearsheet(
        portfolio_equity=flat_cash,
        open_positions_count=0,
        cash=flat_cash,
        realized_pnl=1200.0,
        total_fees=45.50,
        total_slippage=12.25,
        positions={},
    )
    assert is_rec is True
    assert pytest.approx(imb, abs=1e-4) == 0.0

    # Case B: Open position ledger
    # Cost basis = 20,000 (10 shs RELIANCE @ 2000). Current price = 2100 (market val = 21,000)
    # Realized PnL = 500. Fees = 30. Slippage = 8.
    # Canonical Expected Cash = 50000 + 500 - 30 - 20000 = 30470.00
    # Portfolio Equity = 30470 + 21000 = 51470.00
    open_positions = {
        "RELIANCE": {
            "quantity": 10,
            "avg_price": 2000.0,
            "current_price": 2100.0,
            "cost_basis": 20000.0,
        }
    }
    open_cash = 30470.00
    is_rec, imb, err = sentinel.execute_eod_reconciliation_and_tearsheet(
        portfolio_equity=51470.00,
        open_positions_count=1,
        cash=open_cash,
        realized_pnl=500.0,
        total_fees=30.0,
        total_slippage=8.0,
        positions=open_positions,
    )
    assert is_rec is True
    assert pytest.approx(imb, abs=1e-4) == 0.0

    # Case C: Alter cash beyond tolerance (51154.50 -> 51158.00, drift of 3.50 > 0.05)
    sentinel.is_killswitch_tripped = False
    is_rec_drift, imb_drift, err_drift = sentinel.execute_eod_reconciliation_and_tearsheet(
        portfolio_equity=51158.00,
        open_positions_count=0,
        cash=51158.00,
        realized_pnl=1200.0,
        total_fees=45.50,
        total_slippage=12.25,
        positions={},
    )
    assert is_rec_drift is False
    assert imb_drift > 0.05
    assert sentinel.is_killswitch_tripped is True

    # Case D: Alter cost basis beyond tolerance
    sentinel.is_killswitch_tripped = False
    corrupted_positions = {
        "RELIANCE": {
            "quantity": 10,
            "avg_price": 2000.0,
            "current_price": 2100.0,
            "cost_basis": 20100.0,  # 100 INR discrepancy
        }
    }
    is_rec_cb, imb_cb, err_cb = sentinel.execute_eod_reconciliation_and_tearsheet(
        portfolio_equity=51470.00,
        open_positions_count=1,
        cash=open_cash,
        realized_pnl=500.0,
        total_fees=30.0,
        total_slippage=8.0,
        positions=corrupted_positions,
    )
    assert is_rec_cb is False
    assert pytest.approx(imb_cb, abs=1e-2) == 100.0
    assert sentinel.is_killswitch_tripped is True
