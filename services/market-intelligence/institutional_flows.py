"""
Algo Lab — Stage 8 Institutional Flow Processor
Ingests and indexes FII/DII net flows enforcing point-in-time publication timestamp isolation (INV-26).
"""

from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional
import warnings
from services.market_intelligence.contracts import (
    PointInTimeRecord,
    InstitutionalFlowRecord,
    MissingTimestampError,
    SourceConflictError,
    MarketIntelligenceError,
    StaleDataWarning,
)
from services.evaluation_engine.walk_forward import LookAheadBiasError


class InstitutionalFlowProcessor:
    """Processes FII/DII net flow records with point-in-time revision controls (INV-26)."""

    def __init__(
        self,
        flow_records: Optional[List[PointInTimeRecord]] = None,
    ):
        self._records: List[PointInTimeRecord] = []
        if flow_records:
            for r in flow_records:
                self.add_record(r)

    def add_record(self, record: PointInTimeRecord) -> None:
        """Adds a point-in-time flow record with validation."""
        if not record.publication_timestamp:
            raise MissingTimestampError(
                f"Record for event date {record.event_date} is missing publication timestamp (T_pub)."
            )

        payload = record.payload
        # Validate payload sanity (AT-133 malformed payload gate)
        if payload.get("fii_cash_buy", 0.0) < 0.0 or payload.get("dii_cash_buy", 0.0) < 0.0:
            raise MarketIntelligenceError("Institutional flow payload contains invalid negative transaction volume.")

        # Check for conflicting versions at identical (T_event, T_pub)
        for existing in self._records:
            if (
                existing.event_date == record.event_date
                and existing.publication_timestamp == record.publication_timestamp
                and existing.payload != record.payload
            ):
                raise SourceConflictError(
                    f"Conflicting datasets detected for event date {record.event_date} "
                    f"at publication timestamp {record.publication_timestamp}."
                )

        self._records.append(record)
        # Sort by event_date asc, publication_timestamp asc, revision_sequence_id asc
        self._records.sort(key=lambda r: (r.event_date, r.publication_timestamp, r.revision_sequence_id))

    def get_eligible_flow(
        self,
        event_date: date,
        simulation_time: datetime,
    ) -> Optional[InstitutionalFlowRecord]:
        """Gets eligible flow record for `event_date` as known at `simulation_time` (INV-26)."""

        # Filter records for given event_date published on or before simulation_time
        eligible = [
            r for r in self._records
            if r.event_date == event_date and r.publication_timestamp <= simulation_time
        ]

        if not eligible:
            # Check if requesting future date
            future = [r for r in self._records if r.event_date == event_date and r.publication_timestamp > simulation_time]
            if future:
                raise LookAheadBiasError(
                    f"Look-ahead access attempt: Flow for event date {event_date} "
                    f"is published at {future[0].publication_timestamp} > simulation_time {simulation_time}."
                )
            return None

        # Return latest revision published on or before simulation_time
        latest_rec = eligible[-1]
        p = latest_rec.payload

        return InstitutionalFlowRecord(
            event_date=latest_rec.event_date,
            publication_timestamp=latest_rec.publication_timestamp,
            fii_cash_net=float(p.get("fii_cash_net", 0.0)),
            dii_cash_net=float(p.get("dii_cash_net", 0.0)),
            fii_index_futures_net=float(p.get("fii_index_futures_net", 0.0)),
            fii_index_options_net=float(p.get("fii_index_options_net", 0.0)),
            fii_stock_futures_net=float(p.get("fii_stock_futures_net", 0.0)),
            fii_cash_buy=float(p.get("fii_cash_buy", 0.0)),
            fii_cash_sell=float(p.get("fii_cash_sell", 0.0)),
            dii_cash_buy=float(p.get("dii_cash_buy", 0.0)),
            dii_cash_sell=float(p.get("dii_cash_sell", 0.0)),
        )

    def check_stale_data_warning(self, simulation_time: datetime) -> bool:
        """Emits StaleDataWarning if no flow records have been published for >3 days."""
        sim_date = simulation_time.date()
        recent = [
            r for r in self._records
            if r.publication_timestamp <= simulation_time
        ]

        if recent:
            latest_pub_date = recent[-1].publication_timestamp.date()
            if (sim_date - latest_pub_date).days > 3:
                warnings.warn(
                    f"STALE_MACRO_DATA: Institutional flow data is stale by {(sim_date - latest_pub_date).days} days.",
                    category=StaleDataWarning,
                )
                return True
        return False
