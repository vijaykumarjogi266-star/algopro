"""Algo Lab Observability & Prometheus Telemetry Module.

Tracks pipeline lag, order execution latency, slippage variance, and risk rejections.
"""

from typing import Any, Dict, Optional
import time
from prometheus_client import Counter, Gauge, Histogram

# Prometheus Metrics Definitions
PIPELINE_LAG_SECONDS = Gauge(
    "algolab_pipeline_lag_seconds",
    "Time delta between market data event timestamp and processing timestamp in seconds",
    ["feed_name"],
)

ORDER_EXECUTION_LATENCY_SECONDS = Histogram(
    "algolab_order_execution_latency_seconds",
    "Time taken from order generation to broker receipt confirmation in seconds",
    ["broker_name", "order_type"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

RISK_REJECTIONS_TOTAL = Counter(
    "algolab_risk_rejections_total",
    "Cumulative count of trade proposals rejected by the Risk Engine",
    ["rejection_code", "symbol"],
)

SLIPPAGE_VARIANCE_BPS = Histogram(
    "algolab_slippage_variance_bps",
    "Realized slippage versus expected cost model slippage in basis points",
    ["symbol", "exchange"],
    buckets=(1.0, 2.0, 5.0, 10.0, 25.0, 50.0, 100.0),
)


class MetricsCollector:
    """Helper service for recording observability telemetry metrics."""

    @staticmethod
    def record_pipeline_lag(feed_name: str, lag_seconds: float) -> None:
        PIPELINE_LAG_SECONDS.labels(feed_name=feed_name).set(max(0.0, lag_seconds))

    @staticmethod
    def record_order_latency(broker_name: str, order_type: str, latency_seconds: float) -> None:
        ORDER_EXECUTION_LATENCY_SECONDS.labels(
            broker_name=broker_name, order_type=order_type
        ).observe(latency_seconds)

    @staticmethod
    def record_risk_rejection(rejection_code: str, symbol: str) -> None:
        RISK_REJECTIONS_TOTAL.labels(
            rejection_code=rejection_code, symbol=symbol
        ).inc()

    @staticmethod
    def record_slippage_variance(symbol: str, exchange: str, variance_bps: float) -> None:
        SLIPPAGE_VARIANCE_BPS.labels(symbol=symbol, exchange=exchange).observe(variance_bps)
