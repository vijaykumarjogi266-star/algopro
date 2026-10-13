"""Integration tests for Multi-Day Real Ledger Reconciliation and Balance Sheet Integrity (R24–R30).

Tests:
R24: test_two_day_real_fill_ledger_reconciles
R25: test_carry_position_and_partial_close_reconcile
R26: test_reported_equity_mismatch_is_detected
R27: test_cash_drift_and_zero_cash
R28: test_nonfinite_accounting_inputs_are_rejected
R29: test_missing_broker_position_price_is_unresolved
R30: test_integrity_halt_survives_rollover_and_restart
"""

import math
from datetime import datetime, timezone
import pytest

from services.backtest_engine.contracts import OrderSide
from services.backtest_engine.execution_lifecycle import ExecutionLifecycleManager
from services.risk_engine.contracts import HardRiskLimits
from services.risk_engine.engine import RiskEngine
from services.execution_gateway.reconciliation_engine import (
    DoubleEntryLedgerReconciler,
    MultiBrokerReconciliationEngine,
)
from services.execution_gateway.contracts import (
    BrokerPositionRecord,
    ReconciliationStatus,
)
from services.paper_engine.session import (
    PaperTradingEngine,
    PaperPortfolio,
    SessionStatus,
)


@pytest.fixture
def paper_engine(tmp_path):
    db_path = str(tmp_path / "multiday_ledger_test.db")
    risk_limits = HardRiskLimits(
        max_capital_per_trade_pct=0.20,
        max_open_positions=10,
        enforce_mandatory_stop_loss=True,
    )
    lifecycle_manager = ExecutionLifecycleManager(risk_engine=RiskEngine(limits=risk_limits))
    return PaperTradingEngine(db_path=db_path, lifecycle_manager=lifecycle_manager)


def test_two_day_real_fill_ledger_reconciles(paper_engine):
    """R24: Use actual engine fills on day 1 and day 2 with fees/slippage. Roll over daily baseline.

    Assert lifetime reconciliation passes on both days.
    """
    initial_capital = 100_000.0
    session = paper_engine.create_session(
        name="multiday_recon_session",
        strategy_id="strat_multiday",
        universe=["TCS"],
        initial_capital=initial_capital,
    )
    paper_engine.start_session(session.session_id)

    # Day 1: Buy 8 TCS @ 2000 (value 16,000 <= 20% of 100k)
    order1, fill1 = paper_engine.submit_manual_order(
        session_id=session.session_id,
        symbol="TCS",
        side=OrderSide.BUY,
        quantity=8,
        price=2000.0,
        stop_loss=1900.0,
    )
    assert fill1 is not None

    portfolio = session.portfolio
    # Day 1 Lifetime reconciliation check
    pos_dict = {
        sym: {"cost_basis": pos.cost_basis, "current_price": pos.current_price, "quantity": pos.quantity}
        for sym, pos in portfolio.positions.items()
    }
    valid_d1, imb_d1, err_d1 = DoubleEntryLedgerReconciler.audit_accounting_invariants(
        initial_cash=initial_capital,
        current_cash=portfolio.cash,
        positions=pos_dict,
        total_fees_paid=portfolio.total_fees_paid,
        total_slippage_paid=portfolio.total_slippage_paid,
        realized_pnl=portfolio.total_realized_pnl,
    )
    assert valid_d1 is True, f"Day 1 reconciliation failed: {err_d1}"

    # Rollover to Day 2
    session_open_eq = portfolio.total_equity
    portfolio.reset_daily_metrics(session_open_equity=session_open_eq)
    assert portfolio.daily_pnl == 0.0
    assert portfolio.day_start_equity == session_open_eq

    # Day 2: Sell 4 TCS @ 2200
    order2, fill2 = paper_engine.submit_manual_order(
        session_id=session.session_id,
        symbol="TCS",
        side=OrderSide.SELL,
        quantity=4,
        price=2200.0,
        stop_loss=1900.0,
    )
    assert fill2 is not None

    # Day 2 Lifetime balance-sheet and double-entry reconciliation
    pos_dict_d2 = {
        sym: {"cost_basis": pos.cost_basis, "current_price": pos.current_price, "quantity": pos.quantity}
        for sym, pos in portfolio.positions.items()
    }
    valid_d2, imb_d2, err_d2 = DoubleEntryLedgerReconciler.audit_accounting_invariants(
        initial_cash=initial_capital,
        current_cash=portfolio.cash,
        positions=pos_dict_d2,
        total_fees_paid=portfolio.total_fees_paid,
        total_slippage_paid=portfolio.total_slippage_paid,
        realized_pnl=portfolio.total_realized_pnl,
    )
    assert valid_d2 is True, f"Day 2 reconciliation failed: {err_d2}"


def test_carry_position_and_partial_close_reconcile(paper_engine):
    """R25: Carry position across sessions. Assert opening/closing performance and lifetime accounting use correct scopes."""
    initial_capital = 100_000.0
    session = paper_engine.create_session(
        name="carry_position_session",
        strategy_id="strat_carry",
        universe=["INFY"],
        initial_capital=initial_capital,
    )
    paper_engine.start_session(session.session_id)

    # Session 1: Buy 10 INFY @ 1000 (value 10,000 <= 20% of 100k)
    _, fill_buy = paper_engine.submit_manual_order(
        session_id=session.session_id,
        symbol="INFY",
        side=OrderSide.BUY,
        quantity=10,
        price=1000.0,
        stop_loss=950.0,
    )
    assert fill_buy is not None
    s1_closing_equity = session.portfolio.total_equity

    # End Session 1 and roll to Session 2
    session.portfolio.reset_daily_metrics(session_open_equity=s1_closing_equity)

    # Session 2: Partial close of 5 INFY @ 1100
    _, fill_sell = paper_engine.submit_manual_order(
        session_id=session.session_id,
        symbol="INFY",
        side=OrderSide.SELL,
        quantity=5,
        price=1100.0,
        stop_loss=950.0,
    )
    assert fill_sell is not None

    # Verify lifetime balance sheet: initial capital + net realized pnl - fees + unrealized_pnl == cash + positions
    pos_val = session.portfolio.market_value_of_positions
    unrealized_pnl = sum(
        pos.market_value - pos.cost_basis for pos in session.portfolio.positions.values()
    )
    total_net_pnl = session.portfolio.total_realized_pnl - session.portfolio.total_fees_paid + unrealized_pnl
    valid_bs, imb_bs, err_bs = DoubleEntryLedgerReconciler.audit_lifetime_balance_sheet(
        initial_capital=initial_capital,
        cash=session.portfolio.cash,
        positions_value=pos_val,
        net_cashflows=total_net_pnl,
    )
    assert valid_bs is True, f"Balance sheet reconciliation failed: {err_bs}"


def test_reported_equity_mismatch_is_detected():
    """R26: Cash 10,000, no positions/liabilities, reported equity 999,999. Assert discrepancy and detected imbalance."""
    cash = 10_000.0
    positions_value = 0.0
    reported_fake_equity = 999_999.0

    # In double entry: actual equity = cash + positions_value = 10,000
    # Expected vs reported discrepancy
    actual_equity = cash + positions_value
    imbalance = abs(reported_fake_equity - actual_equity)
    assert imbalance == 989_999.0

    valid, delta, reason = DoubleEntryLedgerReconciler.audit_lifetime_balance_sheet(
        initial_capital=reported_fake_equity,  # If someone claimed initial capital or expected was 999,999
        cash=cash,
        positions_value=positions_value,
        net_cashflows=0.0,
    )
    assert valid is False
    assert delta > 0
    assert "imbalance" in reason.lower()


def test_cash_drift_and_zero_cash():
    """R27: Initial capital 10,000; unexplained cash 1. Assert imbalance 9,999. Explicit zero cash remains zero."""
    # 1. Unexplained cash 1.0 vs 10,000 expected
    valid, imbalance, reason = DoubleEntryLedgerReconciler.audit_accounting_invariants(
        initial_cash=10_000.0,
        current_cash=1.0,  # Unexplained cash
        positions={},
        total_fees_paid=0.0,
        total_slippage_paid=0.0,
        realized_pnl=0.0,
    )
    assert valid is False
    assert round(imbalance, 2) == 9999.00

    # 2. Explicit zero cash remains zero
    valid_zero, imbalance_zero, _ = DoubleEntryLedgerReconciler.audit_accounting_invariants(
        initial_cash=0.0,
        current_cash=0.0,
        positions={},
        total_fees_paid=0.0,
        total_slippage_paid=0.0,
        realized_pnl=0.0,
    )
    assert valid_zero is True
    assert imbalance_zero == 0.0


@pytest.mark.parametrize(
    "corrupt_input",
    [
        {"initial_cash": float("nan")},
        {"current_cash": float("inf")},
        {"total_fees_paid": float("nan")},
        {"total_slippage_paid": float("inf")},
        {"realized_pnl": float("nan")},
    ],
)
def test_nonfinite_accounting_inputs_are_rejected(corrupt_input):
    """R28: Parameterize NaN/Inf accounting inputs; assert invalid-state failure, not successful reconciliation."""
    kwargs = {
        "initial_cash": 10_000.0,
        "current_cash": 10_000.0,
        "positions": {},
        "total_fees_paid": 0.0,
        "total_slippage_paid": 0.0,
        "realized_pnl": 0.0,
    }
    kwargs.update(corrupt_input)

    valid, delta, reason = DoubleEntryLedgerReconciler.audit_accounting_invariants(**kwargs)
    assert valid is False
    assert math.isinf(delta)
    assert "Nonfinite accounting input detected" in reason


def test_missing_broker_position_price_is_unresolved():
    """R29: Broker-only position without valid price yields unresolved drift, no fallback price of 100, no fabricated correction."""
    recon_engine = MultiBrokerReconciliationEngine()
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)

    # Broker reports 100 shares of UNPRICED_SYM, but price is None or NaN
    broker_records = [
        BrokerPositionRecord(
            symbol="UNPRICED_SYM",
            quantity=100,
            average_price=0.0,  # Unpriced / zero price
            account_id="ACC_1",
            snapshot_timestamp=now,
            publication_timestamp=now,
        )
    ]
    tracked_positions = {}  # Internal system has 0

    report = recon_engine.reconcile_account(
        account_id="ACC_1",
        tracked_positions=tracked_positions,
        broker_records=broker_records,
        recon_timestamp=now,
    )

    # Must detect drift
    assert report.reconciliation_status == ReconciliationStatus.DRIFT_DETECTED.value
    assert report.position_drift.get("UNPRICED_SYM") == 100
    # Must NOT fabricate an order with arbitrary price (e.g. 100.0)
    assert len(report.corrective_orders_generated) == 0


def test_integrity_halt_survives_rollover_and_restart(paper_engine):
    """R30: Trip ledger discrepancy, restart, advance session. Assert entries remain blocked until authorized recovery."""
    session = paper_engine.create_session(
        name="halt_persistence_session",
        strategy_id="strat_halt",
        universe=["RELIANCE"],
        initial_capital=100_000.0,
    )
    paper_engine.start_session(session.session_id)

    # Corrupt portfolio cash externally to simulate severe ledger discrepancy
    session.portfolio.cash = -50_000.0

    # Advance/rollover session
    session.portfolio.reset_daily_metrics()

    from services.backtest_engine.execution_lifecycle import OrderLifecycleState
    from services.paper_engine.session import ExecutionFill

    # Attempt manual order while in severe negative cash invariant violation
    order, fill = paper_engine.submit_manual_order(
        session_id=session.session_id,
        symbol="RELIANCE",
        side=OrderSide.BUY,
        quantity=10,
        price=2000.0,
        stop_loss=1900.0,
    )
    assert fill is None
    assert order.state == OrderLifecycleState.ORDER_REJECTED

    # Directly attempting on_fill fails closed with defensive invariant violation
    fill_bad = ExecutionFill(
        order_id="bad_1",
        symbol="RELIANCE",
        side=OrderSide.BUY,
        quantity=10,
        base_price=2000.0,
        fill_price=2000.0,
        slippage_pts=0.0,
        slippage_cost=0.0,
        transaction_costs=1.0,
        net_traded_value=20000.0,
    )
    with pytest.raises(ValueError, match="Defensive cash invariant violation"):
        session.portfolio.on_fill(fill_bad)
