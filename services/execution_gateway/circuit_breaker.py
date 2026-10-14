"""
Autonomous Real-Time Risk Circuit Breaker Engine.

Enforces un-overrideable safety kill-switches (Max Drawdown >= 15%, Daily Loss >= 3%,
Monotonic Watchdog Heartbeat > 5.0s, 1.0s Monotonic Rate Limiter, Persistent Disk Backing).
"""

from collections import deque
from datetime import datetime, timezone, timedelta
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
from typing import Any, Dict, List, Optional, Tuple, Union

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
        rearm_secret: Optional[str] = None,
        state_integrity_key: Optional[Union[str, bytes]] = None,
        env: Optional[str] = None,
        require_established_state: Optional[bool] = None,
        allow_uninitialized: Optional[bool] = None,
    ):
        self.config = config or CircuitBreakerConfig()
        self.state_file_path = state_file_path
        self._lock = threading.Lock()

        # Secure rearm secret resolution (Fail-Closed in Production)
        config_env = self.config.env if self.config else None
        resolved_env = (
            env
            or config_env
            or os.environ.get("ENVIRONMENT", "development")
        ).lower()
        self.env = resolved_env

        secret = (
            rearm_secret
            or self.config.rearm_secret
            or os.environ.get("CIRCUIT_BREAKER_REARM_SECRET")
        )
        secret_hash = (
            self.config.rearm_secret_hash
            or os.environ.get("CIRCUIT_BREAKER_REARM_SECRET_HASH")
        )

        if not secret and not secret_hash:
            if resolved_env in ("production", "prod", "staging"):
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
        integrity_key = (
            state_integrity_key
            or self.config.state_integrity_key
            or os.environ.get("CIRCUIT_BREAKER_STATE_KEY")
        )
        if not integrity_key:
            if resolved_env in ("production", "prod", "staging") and self.state_file_path:
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
        self.allow_uninitialized = allow_uninitialized
        self.require_established_state = (
            require_established_state
            if require_established_state is not None
            else (self.config.require_established_state if self.config else None)
        )
        if self.require_established_state is None:
            self.require_established_state = bool(
                resolved_env in ("production", "prod", "staging")
                and self.state_file_path
                and not allow_uninitialized
            )

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
        self._sequence_id: int = 0

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

    def validate_rate_limit(self, allow_liquidation: bool = False) -> None:
        """Validate 1.0-second sliding-window monotonic order rate limit."""
        with self._lock:
            if self._state == GatewayState.EMERGENCY_HALT and not allow_liquidation:
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

    def validate_order(self, order: OrderPayload, allow_liquidation: bool = False) -> None:
        """Validate order submission against circuit breaker state, single order limit, and rate limit."""
        is_liq = bool(allow_liquidation and order.quantity < 0)
        with self._lock:
            if self._state == GatewayState.EMERGENCY_HALT:
                if not is_liq:
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
        self.validate_rate_limit(allow_liquidation=is_liq)

    def trigger_emergency_halt(self, reason: str = "MANUAL_EMERGENCY_HALT") -> None:
        """Explicitly trigger emergency halt."""
        with self._lock:
            self._trip_halt_locked(reason)

    def admin_rearm(self, auth_token: str, ledger_verifier: Optional[Any] = None) -> bool:
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

            # Verify clean ledger before allowing order flow (F09)
            if ledger_verifier is not None:
                try:
                    if callable(ledger_verifier):
                        is_clean = ledger_verifier()
                    else:
                        is_clean = bool(ledger_verifier)
                    if not is_clean:
                        logger.warning(
                            "Circuit breaker rearm rejected: ledger verification failed (unsettled state)",
                            extra={"audit_event": "CIRCUIT_BREAKER_REARM_FAILED"},
                        )
                        return False
                except Exception as e:
                    logger.error(
                        f"Circuit breaker rearm rejected: ledger verification exception: {e}",
                        extra={"audit_event": "CIRCUIT_BREAKER_REARM_FAILED"},
                    )
                    return False

            # Snapshot current state before attempting durable transition
            saved_state = self._state
            saved_reasons = list(self._trip_reasons)
            saved_hwm = self._high_water_mark
            saved_baseline = self._day_start_equity
            saved_persistence_error = self._persistence_error

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
                self._persistence_error = saved_persistence_error or str(e)
                return False

            # Clear stale persistence errors only after verified recovery
            self._persistence_error = None
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

    def _sync_dir(self, dir_name: str) -> None:
        """Fsync directory to guarantee durable entry changes across power loss.
        Propagates OSError on failure without swallowing."""
        if not dir_name:
            return
        dir_fd = os.open(dir_name, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    def sync_directory(self, dir_name: Optional[str] = None) -> None:
        """Public helper to fsync directory descriptor without swallowing errors."""
        target_dir = dir_name or (os.path.dirname(self.state_file_path) if self.state_file_path else "")
        self._sync_dir(target_dir)

    def _write_failure_marker(self, error_msg: str) -> None:
        """Write persistent failure marker so failed halt persistence blocks subsequent restart."""
        if not self.state_file_path:
            return
        marker_path = self.state_file_path + ".failed"
        try:
            dir_name = os.path.dirname(marker_path)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)
            with open(marker_path, "w") as mf:
                mf.write(f"PERSISTENCE_FAILURE: {error_msg}\n")
            if dir_name:
                self._sync_dir(dir_name)
        except Exception:
            pass

    def _trip_halt_locked(self, reason: str) -> None:
        """Internal helper to lock state to EMERGENCY_HALT and persist to disk."""
        if reason not in self._trip_reasons:
            self._trip_reasons.append(reason)
        self._state = GatewayState.EMERGENCY_HALT
        if self.state_file_path:
            self._persist_disk_state()

    def _persist_disk_state(self, raise_on_error: bool = False) -> None:
        """Write persistent EMERGENCY_HALT state to disk with file locking and keyed HMAC digest."""
        if not self.state_file_path:
            return
        try:
            self._sequence_id = self._sequence_id + 1
            payload = {
                "schema_version": 1,
                "sequence_id": self._sequence_id,
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
                self._sync_dir(dir_name)

            self._persistence_error = None
        except Exception as e:
            self._persistence_error = str(e)
            if f"PERSISTENCE_FAILURE: {str(e)}" not in self._trip_reasons:
                self._trip_reasons.append(f"PERSISTENCE_FAILURE: {str(e)}")
            self._write_failure_marker(str(e))
            logger.error(
                "Failed to persist circuit breaker state to disk",
                extra={"error": str(e), "state_path": self.state_file_path},
            )
            if raise_on_error:
                raise

    def _clear_disk_state(self) -> None:
        """Remove disk state file when re-armed. Raises if persistent clearance fails."""
        if not self.state_file_path:
            return
        dir_name = os.path.dirname(self.state_file_path)
        if os.path.exists(self.state_file_path):
            os.remove(self.state_file_path)
            if dir_name:
                self._sync_dir(dir_name)

        marker_path = self.state_file_path + ".failed"
        if os.path.exists(marker_path):
            os.remove(marker_path)
            if dir_name:
                self._sync_dir(dir_name)

    def _restore_disk_state(self) -> None:
        """Restore gateway state from persistent disk file on startup (Fail-Closed Startup)."""
        if not self.state_file_path:
            return

        marker_path = self.state_file_path + ".failed"
        if os.path.exists(marker_path):
            logger.error(
                "Detected failed halt persistence marker; failing closed to EMERGENCY_HALT",
                extra={"marker_path": marker_path},
            )
            self._state = GatewayState.EMERGENCY_HALT
            self._trip_reasons = ["FAILED_PERSISTENCE_RESTART_BLOCKED"]
            self._persistence_error = "Previous halt persistence failed on disk"
            return

        if not os.path.exists(self.state_file_path):
            if self.require_established_state:
                logger.error(
                    "Required established persistent state is missing; failing closed to EMERGENCY_HALT",
                    extra={"state_path": self.state_file_path},
                )
                self._state = GatewayState.EMERGENCY_HALT
                self._trip_reasons = ["MISSING_ESTABLISHED_STATE_FAIL_CLOSED"]
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

            # Validate finite positive equity and consistent HWM
            raw_hwm = data.get("high_water_mark")
            raw_day_start = data.get("day_start_equity")
            raw_current = data.get("current_equity")

            for name, val in [
                ("high_water_mark", raw_hwm),
                ("day_start_equity", raw_day_start),
                ("current_equity", raw_current),
            ]:
                if val is None or not isinstance(val, (int, float)) or math.isnan(val) or math.isinf(val) or val <= 0.0:
                    raise ValueError(f"Invalid non-finite or non-positive equity value for {name}: {val}")

            hwm = float(raw_hwm)
            day_start = float(raw_day_start)
            current = float(raw_current)

            if hwm < current:
                raise ValueError(
                    f"Inconsistent equity state: high_water_mark ({hwm}) cannot be less than current_equity ({current})"
                )

            # Timestamp and sequence validation (F06)
            ts_str = data.get("timestamp_utc")
            if not ts_str:
                raise ValueError("State file missing timestamp_utc")
            try:
                state_ts = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
            except Exception as e:
                raise ValueError(f"Invalid timestamp_utc in state file: {e}")

            now_utc = datetime.now(timezone.utc)
            if state_ts.tzinfo is None:
                state_ts = state_ts.replace(tzinfo=timezone.utc)

            # Future timestamp (> 60s) fails closed
            if state_ts > now_utc + timedelta(seconds=60):
                raise ValueError(f"State file timestamp is in the future: {state_ts}")

            raw_seq = data.get("sequence_id")
            if raw_seq is not None:
                if not isinstance(raw_seq, int) or raw_seq < 0:
                    raise ValueError(f"Invalid sequence_id in state file: {raw_seq}")
                self._sequence_id = max(self._sequence_id, raw_seq)

            # Replay of stale NORMAL state file check (F06)
            if raw_state == GatewayState.NORMAL.value:
                age_sec = (now_utc - state_ts).total_seconds()
                max_age = self.config.max_state_age_seconds
                if age_sec > max_age:
                    raise ValueError(f"Stale NORMAL state file detected (age {age_sec:.1f}s > {max_age}s). Replay rejected.")
                expected_min = self.config.expected_min_sequence
                if expected_min is not None and (raw_seq is None or raw_seq < expected_min):
                    raise ValueError(f"Replayed sequence {raw_seq} is older than expected minimum {expected_min}")

            if raw_state == GatewayState.EMERGENCY_HALT.value:
                self._state = GatewayState.EMERGENCY_HALT
                self._trip_reasons = list(reasons) or ["PERSISTED_DISK_HALT"]
                self._high_water_mark = hwm
                self._day_start_equity = day_start
                self._current_equity = current
        except Exception as e:
            logger.error(
                "Failed to restore circuit breaker disk state; failing closed to EMERGENCY_HALT",
                extra={"error": str(e), "state_path": self.state_file_path},
            )
            self._state = GatewayState.EMERGENCY_HALT
            if "stale normal" in str(e).lower() or "replayed sequence" in str(e).lower():
                self._trip_reasons = ["STALE_NORMAL_STATE_REPLAY_REJECTED"]
            else:
                self._trip_reasons = ["CORRUPTED_DISK_STATE_FAIL_CLOSED"]

    def __repr__(self) -> str:
        return f"<CircuitBreakerEngine state={self._state.value} is_halted={self.is_halted} trip_reasons={self._trip_reasons}>"

    def __str__(self) -> str:
        return self.__repr__()
