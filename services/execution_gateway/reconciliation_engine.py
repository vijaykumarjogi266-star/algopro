"""
Deterministic Multi-Broker Position Reconciliation Engine.

Synchronizes internal tracked positions against external broker account states, detects state drift,
and generates deterministic corrective delta orders sorted alphabetically with ISO-8601 SHA-256 hashes.
"""

from datetime import datetime, timezone
import hashlib
import math
import unicodedata
from typing import Dict, List, Optional, Tuple

from services.execution_gateway.contracts import (
    BrokerPositionRecord,
    ReconciliationReport,
    ReconciliationStatus,
    StaleSnapshotError,
    GatewayValidationError,
)


class MultiBrokerReconciliationEngine:
    """
    Multi-Broker Position Reconciliation Engine enforcing INV-47, INV-49, and INV-50.
    """

    def generate_canonical_order_id(
        self,
        account_id: str,
        symbol: str,
        quantity: int,
        price: float,
        timestamp: datetime,
    ) -> str:
        """
        Generate deterministic 64-character SHA-256 hex string Order ID.
        Uses NFKC normalization and ISO-8601 UTC timestamp format (INV-49).
        """
        if not account_id or not isinstance(account_id, str):
            raise GatewayValidationError("account_id must be a non-empty string")
        if not symbol or not isinstance(symbol, str):
            raise GatewayValidationError("symbol must be a non-empty string")
        if not isinstance(quantity, int) or quantity == 0:
            raise GatewayValidationError("quantity must be a non-zero integer")
        if not isinstance(price, (int, float)) or price <= 0.0:
            raise GatewayValidationError("price must be a positive float")
        if not isinstance(timestamp, datetime):
            raise GatewayValidationError("timestamp must be a datetime object")

        # Convert timestamp to UTC ISO-8601 string
        if timestamp.tzinfo is None:
            ts_utc = timestamp.replace(tzinfo=timezone.utc)
        else:
            ts_utc = timestamp.astimezone(timezone.utc)

        ts_str = ts_utc.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        raw_str = f"{account_id.strip()}:{symbol.upper().strip()}:{quantity}:{price:.6f}:{ts_str}"
        normalized_str = unicodedata.normalize("NFKC", raw_str)
        return hashlib.sha256(normalized_str.encode("utf-8")).hexdigest()

    def reconcile_account(
        self,
        account_id: str,
        tracked_positions: Dict[str, int],
        broker_records: List[BrokerPositionRecord],
        recon_timestamp: datetime,
    ) -> ReconciliationReport:
        """
        Reconcile internal tracked positions against external broker snapshots.
        Enforces Point-in-Time snapshot isolation published <= recon_timestamp.
        """
        if not account_id or not isinstance(account_id, str):
            raise GatewayValidationError("account_id must be a non-empty string")
        if not isinstance(recon_timestamp, datetime):
            raise GatewayValidationError("recon_timestamp must be a datetime object")

        if recon_timestamp.tzinfo is None:
            t_recon_utc = recon_timestamp.replace(tzinfo=timezone.utc)
        else:
            t_recon_utc = recon_timestamp.astimezone(timezone.utc)

        broker_positions: Dict[str, int] = {}
        broker_prices: Dict[str, float] = {}

        # Aggregate and validate Point-in-Time broker records
        for record in broker_records:
            if record.account_id != account_id:
                continue

            # PIT Check: publication_timestamp <= t_recon_utc
            pub_ts = record.publication_timestamp
            if pub_ts.tzinfo is None:
                pub_ts = pub_ts.replace(tzinfo=timezone.utc)
            else:
                pub_ts = pub_ts.astimezone(timezone.utc)

            if pub_ts > t_recon_utc:
                raise StaleSnapshotError(
                    f"Broker record publication timestamp {pub_ts.isoformat()} > recon timestamp {t_recon_utc.isoformat()}"
                )

            sym = record.symbol.upper().strip()
            broker_positions[sym] = record.quantity
            broker_prices[sym] = record.average_price

        # Collect all unique symbols
        all_symbols = sorted(set(list(tracked_positions.keys()) + list(broker_positions.keys())))

        position_drift: Dict[str, int] = {}
        corrective_order_ids: List[str] = []
        residual_drift_count = 0

        # Compute position drift and generate corrective orders alphabetically
        for sym in all_symbols:
            p_tracked = tracked_positions.get(sym, 0)
            p_broker = broker_positions.get(sym, 0)
            delta_p = p_broker - p_tracked  # ΔP = P_broker - P_tracked (INV-47)

            position_drift[sym] = delta_p

            if delta_p != 0:
                residual_drift_count += 1
                avg_price = broker_prices.get(sym)
                # Broker-only position without valid price yields unresolved drift, not fabricated price or correction orders
                if avg_price is None or not isinstance(avg_price, (int, float)) or not math.isfinite(avg_price) or avg_price <= 0.0:
                    continue
                order_id = self.generate_canonical_order_id(
                    account_id=account_id,
                    symbol=sym,
                    quantity=delta_p,
                    price=avg_price,
                    timestamp=t_recon_utc,
                )
                corrective_order_ids.append(order_id)

        status = (
            ReconciliationStatus.SYNCHRONIZED.value
            if residual_drift_count == 0
            else ReconciliationStatus.DRIFT_DETECTED.value
        )

        return ReconciliationReport(
            timestamp=t_recon_utc,
            account_id=account_id,
            tracked_positions=dict(tracked_positions),
            broker_positions=broker_positions,
            position_drift=position_drift,
            corrective_orders_generated=corrective_order_ids,
            reconciliation_status=status,
            residual_drift_count=residual_drift_count,
        )


class DoubleEntryLedgerReconciler:
    """
    Double-Entry Financial Accounting Ledger Reconciler.
    Enforces strict mathematical conservation of capital across all portfolio transactions:
    Equity == Cash + Market Value of Open Positions
    Current Cash == Initial Cash + Sum(Realized PnL) - Sum(Fees) - Sum(Open Position Cost Basis)
    """

    @staticmethod
    def audit_accounting_invariants(
        initial_cash: float,
        current_cash: float,
        positions: Dict[str, Dict[str, float]],  # {symbol: {quantity, avg_price, current_price, cost_basis}}
        total_fees_paid: float,
        total_slippage_paid: float,
        realized_pnl: float,
        tolerance: float = 0.01,
    ) -> Tuple[bool, float, Optional[str]]:
        """
        Audits double-entry invariants against floating-point drift and rejects nonfinite inputs.
        Returns: (is_valid, imbalance_amount, failure_reason).
        """
        import math

        # Reject nonfinite accounting inputs
        for name, val in [
            ("initial_cash", initial_cash),
            ("current_cash", current_cash),
            ("total_fees_paid", total_fees_paid),
            ("total_slippage_paid", total_slippage_paid),
            ("realized_pnl", realized_pnl),
            ("tolerance", tolerance),
        ]:
            if not isinstance(val, (int, float)) or math.isnan(val) or math.isinf(val):
                return False, float("inf"), f"Nonfinite accounting input detected: {name}={val}"

        for sym, pos in positions.items():
            for k, v in pos.items():
                if not isinstance(v, (int, float)) or math.isnan(v) or math.isinf(v):
                    return False, float("inf"), f"Nonfinite position attribute detected: {sym}.{k}={v}"

        total_cost_basis = sum(pos.get("cost_basis", pos.get("quantity", 0) * pos.get("avg_price", 0.0)) for pos in positions.values())
        total_market_val = sum(pos.get("quantity", 0) * pos.get("current_price", 0.0) for pos in positions.values())

        # Single Canonical Accounting Model (INV-47/INV-50):
        # Fill-price consistent accounting: cost_basis incorporates executed fill_price.
        # Slippage is an attribution metric, NOT a secondary deduction from cash.
        expected_cash = initial_cash + realized_pnl - total_fees_paid - total_cost_basis
        imbalance = abs(current_cash - expected_cash)

        if imbalance <= tolerance:
            return True, 0.0, None

        return (
            False,
            imbalance,
            f"Double-entry cash imbalance detected: Expected INR {expected_cash:.2f}, Actual INR {current_cash:.2f} (Delta: {imbalance:.4f})"
        )

    @staticmethod
    def audit_lifetime_balance_sheet(
        initial_capital: float,
        cash: float,
        positions_value: float,
        net_cashflows: float = 0.0,
        tolerance: float = 0.01,
    ) -> Tuple[bool, float, Optional[str]]:
        """
        Lifetime balance-sheet reconciliation: initial_capital + net_cashflows = cash + positions_value.
        Rejects nonfinite inputs.
        """
        import math
        for name, val in [
            ("initial_capital", initial_capital),
            ("cash", cash),
            ("positions_value", positions_value),
            ("net_cashflows", net_cashflows),
            ("tolerance", tolerance),
        ]:
            if not isinstance(val, (int, float)) or math.isnan(val) or math.isinf(val):
                return False, float("inf"), f"Nonfinite balance-sheet input detected: {name}={val}"

        expected_equity = initial_capital + net_cashflows
        actual_equity = cash + positions_value
        imbalance = abs(actual_equity - expected_equity)
        if imbalance > tolerance:
            return (
                False,
                imbalance,
                f"Lifetime balance-sheet imbalance: expected INR {expected_equity:.2f}, actual INR {actual_equity:.2f} (Delta: {imbalance:.4f})"
            )
        return True, 0.0, None

