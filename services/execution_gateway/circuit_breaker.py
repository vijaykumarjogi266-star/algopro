"""
Autonomous Real-Time Risk Circuit Breaker Engine.

Enforces un-overrideable safety kill-switches (Max Drawdown >= 15%, Daily Loss >= 3%,
Monotonic Watchdog Heartbeat > 5.0s, 1.0s Monotonic Rate Limiter, Persistent Disk Backing).
"""

from collections import deque
from datetime import datetime, timezone
import fcntl
import hashlib
import hmac
import json
import logging
import math
import os
import secrets
import tempfile
import threading
import time
from typing import Dict, List, Optional, Tuple

from services.execution_gateway.contracts import (
    GatewayState,
    CircuitBreakerConfig,
    CircuitBreakerTripped,
    WatchdogTimeoutError,
    RateLimitExceededError,
    OrderPayload,
)

logger = logging.getLogger(__name__)


class CircuitBreakerEngine:
    """
    Autonomous Risk Circuit Breaker Engine for Execution Gateway.
    Thread-safe and disk-backed for crash recovery.
    """

    def __init__(
        self,
        config: Optional[CircuitBreakerConfig] = None,
        state_file_path: Optional[str] = None,
        initial_equity: float = 100_000.0,
    ):
        self.config = config or CircuitBreakerConfig()
        self.state_file_path = state_file_path
        self._lock = threading.Lock()

        # Secure rearm secret resolution (Fail-Closed in Production)
        env = os.environ.get("ENVIRONMENT", "development").lower()
        secret = self.config.rearm_secret or os.environ.get("CIRCUIT_BREAKER_REARM_SECRET")
        secret_hash = self.config.rearm_secret_hash or os.environ.get("CIRCUIT_BREAKER_REARM_SECRET_HASH")

        if not secret and not secret_hash:
            if env in ("production", "prod", "staging"):
                raise RuntimeError(
                    "Production circuit breaker startup failed closed: "
                    "CIRCUIT_BREAKER_REARM_SECRET or CIRCUIT_BREAKER_REARM_SECRET_HASH must be configured."
                )
            self._rearm_secret_digest: Optional[bytes] = None
        elif secret_hash:
            self._rearm_secret_digest = bytes.fromhex(secret_hash) if isinstance(secret_hash, str) else secret_hash
        else:
            self._rearm_secret_digest = hashlib.sha256(secret.encode("utf-8")).digest()

        # Dedicated independent state integrity key (NEVER reuse rearm secret, NO static fallback)
        integrity_key = self.config.state_integrity_key or os.environ.get("CIRCUIT_BREAKER_STATE_KEY")
        if not integrity_key:
            if env in ("production", "prod", "staging") and self.state_file_path:
                raise RuntimeError(
                    "Production circuit breaker startup failed closed: "
                    "CIRCUIT_BREAKER_STATE_KEY must be configured for persistent state integrity."
                )
            # Use random ephemeral key in non-production (unique per process, never static)
            self._state_integrity_key: bytes = secrets.token_bytes(32)
        elif isinstance(integrity_key, str):
            self._state_integrity_key = integrity_key.encode("latin1")
        else:
            self._state_integrity_key = bytes(integrity_key)

        self._persistence_error: Optional[str] = None

        # Monotonic time tracking for watchdog & rate limiter
        self._last_heartbeat_monotonic = time.monotonic()
        self._rate_limiter_deque: deque[float] = deque()

        # Equity & Risk Tracking
        if not isinstance(initial_equity, (int, float)) or math.isnan(initial_equity) or math.isinf(initial_equity) or initial_equity <= 0.0:
            raise ValueError(f"Invalid initial_equity: {initial_equity}")

        self._initial_equity = float(initial_equity)
        self._high_water_mark = float(initial_equity)
        self._day_start_equity = float(initial_equity)
        self._current_equity = float(initial_equity)
        self._last_session_open_day: Optional[str] = None

        # Gateway state & trip reasons
        self._state = GatewayState.NORMAL
        self._trip_reasons: List[str] = []

        # Load disk state on startup if state_file_path is configured (Fail-Closed Recovery)
        if self.state_file_path:
            self._restore_disk_state()

    @property
    def state(self) -> GatewayState:
        with self._lock:
            return self._state

    @property
    def is_halted(self) -> bool:
        with self._lock:
            return self._state == GatewayState.EMERGENCY_HALT

    @property
    def trip_reasons(self) -> List[str]:
        with self._lock:
            return list(self._trip_reasons)

    def record_heartbeat(self) -> None:
        """Update monotonic watchdog heartbeat timer."""
        with self._lock:
            self._last_heartbeat_monotonic = time.monotonic()

    def update_session_open_equity(self, session_equity: float, session_day: Optional[str] = None) -> None:
        """Capture reference equity at session open boundary (09:15 IST / 03:45 UTC)."""
        with self._lock:
            if math.isnan(session_equity) or math.isinf(session_equity) or session_equity <= 0.0:
                raise ValueError(f"Invalid session_equity: {session_equity}")
            self._day_start_equity = float(session_equity)
            self._last_session_open_day = session_day or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def update_equity(self, current_equity: float) -> GatewayState:
        """Update portfolio equity and evaluate drawdown & daily loss circuit breakers."""
        with self._lock:
            if math.isnan(current_equity) or math.isinf(current_equity) or current_equity <= 0.0:
                self._trip_halt_locked("NON_FINITE_EQUITY_BREACH")
                return self._state

            self._current_equity = float(current_equity)

            # Update High Water Mark
            if self._current_equity > self._high_water_mark:
                self._high_water_mark = self._current_equity

            # Calculate Drawdown: (HWM - Current) / HWM
            drawdown_pct = (self._high_water_mark - self._current_equity) / self._high_water_mark
            if drawdown_pct >= self.config.max_portfolio_drawdown_pct:
                self._trip_halt_locked(f"DRAWDOWN_BREACH_{drawdown_pct*100:.2f}%")

            # Calculate Daily Loss: (DayStart - Current) / DayStart
            daily_loss_pct = (self._day_start_equity - self._current_equity) / self._day_start_equity
            if daily_loss_pct >= self.config.max_daily_loss_pct:
                self._trip_halt_locked(f"DAILY_LOSS_BREACH_{daily_loss_pct*100:.2f}%")

            return self._state

    def check_watchdog(self) -> None:
        """Check monotonic watchdog heartbeat timeout."""
        with self._lock:
            now_mono = time.monotonic()
            elapsed = now_mono - self._last_heartbeat_monotonic
            if elapsed > self.config.watchdog_heartbeat_timeout_sec:
                self._trip_halt_locked(f"WATCHDOG_TIMEOUT_EXCEEDED_{elapsed:.2f}s")
                raise WatchdogTimeoutError(f"Watchdog heartbeat timed out after {elapsed:.2f}s")

    def validate_rate_limit(self) -> None:
        """Validate 1.0-second sliding-window monotonic order rate limit."""
        with self._lock:
            if self._state == GatewayState.EMERGENCY_HALT:
                raise CircuitBreakerTripped("Gateway in EMERGENCY_HALT state")

            now_mono = time.monotonic()
            # Remove timestamps older than 1.0 second
            while self._rate_limiter_deque and (now_mono - self._rate_limiter_deque[0]) >= 1.0:
                self._rate_limiter_deque.popleft()

            if len(self._rate_limiter_deque) >= self.config.max_order_rate_per_sec:
                raise RateLimitExceededError(
                    f"Order rate burst limit exceeded: {len(self._rate_limiter_deque)} orders in 1.0s window"
                )

            self._rate_limiter_deque.append(now_mono)

    def evaluate_drawdown(self, current_equity: float) -> GatewayState:
        """Alias for update_equity to evaluate drawdown and daily loss."""
        return self.update_equity(current_equity)

    def validate_order(self, order: OrderPayload) -> None:
        """Validate order submission against circuit breaker state, single order limit, and rate limit."""
        with self._lock:
            if self._state == GatewayState.EMERGENCY_HALT:
                raise CircuitBreakerTripped(
                    f"Gateway in EMERGENCY_HALT: {', '.join(self._trip_reasons)}"
                )
            if self._persistence_error:
                raise CircuitBreakerTripped(
                    f"Gateway state persistence failed: {self._persistence_error}"
                )
            if abs(order.quantity) > self.config.max_single_order_qty:
                raise ValueError(
                    f"Order quantity {order.quantity} exceeds max_single_order_qty ({self.config.max_single_order_qty})"
                )
        self.validate_rate_limit()

    def trigger_emergency_halt(self, reason: str = "MANUAL_EMERGENCY_HALT") -> None:
        """Explicitly trigger emergency halt."""
        with self._lock:
            self._trip_halt_locked(reason)

    def admin_rearm(self, auth_token: str) -> bool:
        """Re-arm gateway from EMERGENCY_HALT back to NORMAL using admin key."""
        with self._lock:
            if not auth_token or not isinstance(auth_token, str):
                logger.warning(
                    "Circuit breaker rearm rejected: invalid token format",
                    extra={"audit_event": "CIRCUIT_BREAKER_REARM_FAILED"},
                )
                return False

            if self._rearm_secret_digest is None:
                logger.warning(
                    "Circuit breaker rearm rejected: no rearm secret configured",
                    extra={"audit_event": "CIRCUIT_BREAKER_REARM_FAILED"},
                )
                return False

            submitted_digest = hashlib.sha256(auth_token.encode("utf-8")).digest()
            if not hmac.compare_digest(submitted_digest, self._rearm_secret_digest):
                logger.warning(
                    "Circuit breaker rearm rejected: authentication token mismatch",
                    extra={"audit_event": "CIRCUIT_BREAKER_REARM_FAILED"},
                )
                return False

            # Snapshot current state before attempting durable transition
            saved_state = self._state
            saved_reasons = list(self._trip_reasons)
            saved_hwm = self._high_water_mark
            saved_baseline = self._day_start_equity

            # Attempt durable clearance first
            try:
                self._clear_disk_state()
            except Exception as e:
                logger.error(
                    "Circuit breaker rearm failed: durable state persistence failed",
                    extra={"audit_event": "CIRCUIT_BREAKER_REARM_FAILED", "error": str(e)},
                )
                # Keep engine halted and preserve existing reasons/snapshots
                self._state = saved_state
                self._trip_reasons = saved_reasons
                self._high_water_mark = saved_hwm
                self._day_start_equity = saved_baseline
                return False

            # Emit success audit ONLY after durable transition succeeds
            self._state = GatewayState.NORMAL
            self._trip_reasons.clear()
            self._high_water_mark = self._current_equity
            self._day_start_equity = self._current_equity
            self._last_heartbeat_monotonic = time.monotonic()
            logger.info(
                "Circuit breaker rearm accepted: Gateway restored to NORMAL",
                extra={"audit_event": "CIRCUIT_BREAKER_REARM_SUCCESS"},
            )
            return True

    def _trip_halt_locked(self, reason: str) -> None:
        """Internal helper to lock state to EMERGENCY_HALT and persist to disk."""
        if reason not in self._trip_reasons:
            self._trip_reasons.append(reason)
        self._state = GatewayState.EMERGENCY_HALT
        if self.state_file_path:
            self._persist_disk_state()

    def _persist_disk_state(self) -> None:
        """Write persistent EMERGENCY_HALT state to disk with file locking and keyed HMAC digest."""
        if not self.state_file_path:
            return
        try:
            payload = {
                "schema_version": 1,
                "gateway_state": self._state.value,
                "trip_reasons": list(self._trip_reasons),
                "high_water_mark": float(self._high_water_mark),
                "day_start_equity": float(self._day_start_equity),
                "current_equity": float(self._current_equity),
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }
            content = json.dumps(payload, sort_keys=True)
            digest = hmac.new(self._state_integrity_key, content.encode("utf-8"), hashlib.sha256).hexdigest()
            payload["hmac_digest"] = digest

            dir_name = os.path.dirname(self.state_file_path)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)

            with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False) as tf:
                fcntl.flock(tf.fileno(), fcntl.LOCK_EX)
                json.dump(payload, tf, indent=2)
                tf.flush()
                os.fsync(tf.fileno())
                fcntl.flock(tf.fileno(), fcntl.LOCK_UN)
                temp_name = tf.name

            os.replace(temp_name, self.state_file_path)

            # Fsync directory descriptor to guarantee durability across power failure
            if dir_name:
                try:
                    dir_fd = os.open(dir_name, os.O_RDONLY)
                    try:
                        os.fsync(dir_fd)
                    finally:
                        os.close(dir_fd)
                except Exception:
                    pass

            self._persistence_error = None
        except Exception as e:
            self._persistence_error = str(e)
            if "PERSISTENCE_FAILURE" not in self._trip_reasons:
                self._trip_reasons.append(f"PERSISTENCE_FAILURE: {str(e)}")
            logger.error(
                "Failed to persist circuit breaker state to disk",
                extra={"error": str(e), "state_path": self.state_file_path},
            )

    def _clear_disk_state(self) -> None:
        """Remove disk state file when re-armed. Raises if persistent clearance fails."""
        if not self.state_file_path:
            return
        if os.path.exists(self.state_file_path):
            os.remove(self.state_file_path)
            dir_name = os.path.dirname(self.state_file_path)
            if dir_name:
                try:
                    dir_fd = os.open(dir_name, os.O_RDONLY)
                    try:
                        os.fsync(dir_fd)
                    finally:
                        os.close(dir_fd)
                except Exception:
                    pass

    def _restore_disk_state(self) -> None:
        """Restore gateway state from persistent disk file on startup (Fail-Closed Startup)."""
        if not self.state_file_path or not os.path.exists(self.state_file_path):
            return

        try:
            with open(self.state_file_path, "r") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                data = json.load(f)
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

            if not isinstance(data, dict):
                raise ValueError("State file content is not a JSON object")

            # Validate HMAC digest existence
            if "hmac_digest" not in data:
                raise ValueError("Persisted state file is unsigned (tampering detected)")

            expected_hmac = data.pop("hmac_digest")
            content = json.dumps(data, sort_keys=True)
            computed = hmac.new(self._state_integrity_key, content.encode("utf-8"), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected_hmac, computed):
                raise ValueError("Keyed HMAC digest mismatch on persisted state file (tampering detected)")

            # Validate Schema
            if data.get("schema_version") != 1:
                raise ValueError(f"Unsupported schema_version: {data.get('schema_version')}")

            raw_state = data.get("gateway_state")
            if raw_state not in [e.value for e in GatewayState]:
                raise ValueError(f"Unknown gateway_state: {raw_state}")

            reasons = data.get("trip_reasons")
            if not isinstance(reasons, list) or not all(isinstance(r, str) for r in reasons):
                raise ValueError("trip_reasons must be a list of strings")

            if raw_state == GatewayState.EMERGENCY_HALT.value:
                self._state = GatewayState.EMERGENCY_HALT
                self._trip_reasons = list(reasons) or ["PERSISTED_DISK_HALT"]
                self._high_water_mark = float(data.get("high_water_mark", self._high_water_mark))
                self._day_start_equity = float(data.get("day_start_equity", self._day_start_equity))
                self._current_equity = float(data.get("current_equity", self._current_equity))
        except Exception as e:
            logger.error(
                "Failed to restore circuit breaker disk state; failing closed to EMERGENCY_HALT",
                extra={"error": str(e), "state_path": self.state_file_path},
            )
            self._state = GatewayState.EMERGENCY_HALT
            self._trip_reasons = ["CORRUPTED_DISK_STATE_FAIL_CLOSED"]

    def __repr__(self) -> str:
        return f"<CircuitBreakerEngine state={self._state.value} is_halted={self.is_halted} trip_reasons={self._trip_reasons}>"

    def __str__(self) -> str:
        return self.__repr__()
