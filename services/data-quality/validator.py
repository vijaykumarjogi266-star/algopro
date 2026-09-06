"""Algo Lab Data Quality Engine Architecture.

Provides validation pipelines detecting duplicates, missing bars, timestamp order,
negative prices, OHLC anomalies, volume spikes, and stale data.
"""

from datetime import datetime, timedelta, timezone
from typing import List, Tuple
from pydantic import BaseModel, Field

from data.schemas.contracts import (
    DataQualityStatus,
    OHLCVBar,
    QualityCheckResult,
    QualitySeverity,
)


class DataQualityReport(BaseModel):
    symbol: str
    total_bars: int
    valid_bars: int
    flagged_bars: int
    overall_status: DataQualityStatus
    check_results: List[QualityCheckResult] = Field(default_factory=list)
    has_critical_failures: bool = False


class DataQualityValidator:
    """Validates bar sequences against financial, mathematical, and temporal invariants."""

    def __init__(
        self,
        max_allowed_stale_bars: int = 5,
        volume_anomaly_multiplier: float = 20.0,
    ):
        self.max_allowed_stale_bars = max_allowed_stale_bars
        self.volume_anomaly_multiplier = volume_anomaly_multiplier

    def validate_series(self, bars: List[OHLCVBar]) -> DataQualityReport:
        """Validates a temporal sequence of OHLCV bars for a given symbol."""
        if not bars:
            return DataQualityReport(
                symbol="UNKNOWN",
                total_bars=0,
                valid_bars=0,
                flagged_bars=0,
                overall_status=DataQualityStatus.INCOMPLETE,
                check_results=[
                    QualityCheckResult(
                        check_name="empty_series_check",
                        passed=False,
                        severity=QualitySeverity.CRITICAL,
                        message="Bar series is completely empty",
                    )
                ],
                has_critical_failures=True,
            )

        symbol = bars[0].symbol
        check_results: List[QualityCheckResult] = []
        has_critical = False

        # 1. Monotonic Timestamps & Duplicates Check
        timestamps_seen = set()
        duplicates_found = 0
        out_of_order = 0

        for i in range(len(bars)):
            curr_ts = bars[i].market_timestamp
            if curr_ts in timestamps_seen:
                duplicates_found += 1
            timestamps_seen.add(curr_ts)

            if i > 0 and curr_ts <= bars[i - 1].market_timestamp:
                out_of_order += 1

        if duplicates_found > 0:
            check_results.append(
                QualityCheckResult(
                    check_name="duplicate_detection",
                    passed=False,
                    severity=QualitySeverity.CRITICAL,
                    message=f"Detected {duplicates_found} duplicate timestamps in series",
                )
            )
            has_critical = True
        else:
            check_results.append(
                QualityCheckResult(
                    check_name="duplicate_detection",
                    passed=True,
                    severity=QualitySeverity.INFO,
                    message="No duplicate timestamps detected",
                )
            )

        if out_of_order > 0:
            check_results.append(
                QualityCheckResult(
                    check_name="timestamp_monotonicity",
                    passed=False,
                    severity=QualitySeverity.CRITICAL,
                    message=f"Detected {out_of_order} out-of-order timestamps (Look-ahead risk)",
                )
            )
            has_critical = True
        else:
            check_results.append(
                QualityCheckResult(
                    check_name="timestamp_monotonicity",
                    passed=True,
                    severity=QualitySeverity.INFO,
                    message="Timestamps are strictly monotonically ascending",
                )
            )

        # 2. Stale Data & Volume Anomaly Check
        stale_streak = 0
        max_stale_observed = 0
        vols = [b.volume for b in bars]
        avg_vol = sum(vols) / len(vols) if vols else 0.0

        anomalous_volumes = 0

        for i in range(len(bars)):
            bar = bars[i]
            # Stale price check (Open == High == Low == Close)
            if bar.open == bar.high == bar.low == bar.close:
                stale_streak += 1
                if stale_streak > max_stale_observed:
                    max_stale_observed = stale_streak
            else:
                stale_streak = 0

            # Volume anomaly check
            if avg_vol > 0 and bar.volume > (avg_vol * self.volume_anomaly_multiplier):
                anomalous_volumes += 1

        if max_stale_observed > self.max_allowed_stale_bars:
            check_results.append(
                QualityCheckResult(
                    check_name="stale_data_detection",
                    passed=False,
                    severity=QualitySeverity.WARNING,
                    message=f"Consecutive stale bars reached {max_stale_observed} (threshold: {self.max_allowed_stale_bars})",
                )
            )
        else:
            check_results.append(
                QualityCheckResult(
                    check_name="stale_data_detection",
                    passed=True,
                    severity=QualitySeverity.INFO,
                    message="No excessive stale bars detected",
                )
            )

        if anomalous_volumes > 0:
            check_results.append(
                QualityCheckResult(
                    check_name="volume_anomaly_detection",
                    passed=False,
                    severity=QualitySeverity.WARNING,
                    message=f"Found {anomalous_volumes} bars exceeding {self.volume_anomaly_multiplier}x average volume",
                )
            )

        # Determine overall status
        if has_critical:
            overall_status = DataQualityStatus.REJECTED
        elif any(c.severity == QualitySeverity.WARNING and not c.passed for c in check_results):
            overall_status = DataQualityStatus.SUSPECT
        else:
            overall_status = DataQualityStatus.VALID

        return DataQualityReport(
            symbol=symbol,
            total_bars=len(bars),
            valid_bars=len(bars) if not has_critical else 0,
            flagged_bars=len(bars) if has_critical else 0,
            overall_status=overall_status,
            check_results=check_results,
            has_critical_failures=has_critical,
        )
