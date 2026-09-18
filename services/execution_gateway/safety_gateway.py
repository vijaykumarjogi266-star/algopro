"""
Single-Point Execution Safety Gateway, Payload Validator, Duplicate Lockout, and Static AST Scanner.
"""

import ast
from datetime import datetime, timezone
import math
import os
import re
import threading
from typing import Dict, List, Optional, Set

from services.execution_gateway.contracts import (
    OrderPayload,
    CircuitBreakerConfig,
    GatewayValidationError,
    DuplicateOrderError,
    ASTIsolationError,
    CircuitBreakerTripped,
    RateLimitExceededError,
)
from services.execution_gateway.circuit_breaker import CircuitBreakerEngine

PROHIBITED_IMPORT_NAMES = {
    "kiteconnect",
    "upstox_client",
    "smartapi",
    "socket",
    "websockets",
    "urllib",
    "requests",
    "httpx",
    "aiohttp",
    "subprocess",
    "importlib",
}

PROHIBITED_DIRECT_BUILTINS = {
    "import_module",
    "__import__",
    "eval",
    "exec",
    "compile",
    "getattr",
    "popen",
    "system",
}

PROHIBITED_ATTR_CALLS = {
    "import_module",
    "__import__",
    "eval",
    "exec",
    "getattr",
    "popen",
    "system",
}

# Dynamically construct secret patterns to prevent scanner self-matching
_PATTERN_STRINGS = [
    r"AKIA[0-9A-Z]{16}",
    r"eyJ" + r"[A-Za-z0-9-_=]+\." + r"eyJ[A-Za-z0-9-_=]+",
    r"-----BEGIN " + r"PRIVATE KEY-----",
    r"bearer\s+[A-Za-z0-9-\._~\+\/]+=*",
]

PROHIBITED_SECRET_PATTERNS = [re.compile(p, re.I if "bearer" in p else 0) for p in _PATTERN_STRINGS]


class StaticASTIsolationScanner:
    """
    Statically inspects Python code in services/execution_gateway/ to guarantee zero prohibited imports,
    zero dynamic execution calls, zero socket modules, and zero plain-text secrets.
    """

    PROHIBITED_SECRET_PATTERNS = PROHIBITED_SECRET_PATTERNS

    def scan_directory(self, target_dir: str) -> bool:
        """Scan all .py files in target_dir for prohibited AST nodes or secret patterns."""
        if not os.path.exists(target_dir) or not os.path.isdir(target_dir):
            raise ASTIsolationError(f"Target directory does not exist: {target_dir}")

        for root, _, files in os.walk(target_dir):
            for f in files:
                if f.endswith(".py"):
                    full_path = os.path.join(root, f)
                    self.scan_file(full_path)
        return True

    def scan_file(self, file_path: str) -> bool:
        """Scan a single Python file for security isolation breaches."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            raise ASTIsolationError(f"Failed to read file {file_path}: {e}")

        # 1. Regex Secret Scanning
        for pattern in PROHIBITED_SECRET_PATTERNS:
            if pattern.search(content):
                raise ASTIsolationError(f"Secret credential pattern detected in file: {file_path}")

        # 2. AST Parse & Node Walk
        try:
            tree = ast.parse(content, filename=file_path)
        except Exception as e:
            raise ASTIsolationError(f"Failed to parse AST for {file_path}: {e}")

        for node in ast.walk(tree):
            # Check Imports: import xyz
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name_base = alias.name.split(".")[0]
                    if name_base in PROHIBITED_IMPORT_NAMES:
                        raise ASTIsolationError(f"Prohibited import '{alias.name}' detected in {file_path}")

            # Check From Imports: from xyz import abc
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    name_base = node.module.split(".")[0]
                    if name_base in PROHIBITED_IMPORT_NAMES:
                        raise ASTIsolationError(f"Prohibited import from '{node.module}' detected in {file_path}")

            # Check Dynamic Function Calls: importlib.import_module, eval(), exec(), getattr()
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if node.func.id in PROHIBITED_DIRECT_BUILTINS:
                        raise ASTIsolationError(
                            f"Prohibited dynamic builtin function call '{node.func.id}' detected in {file_path}"
                        )
                elif isinstance(node.func, ast.Attribute):
                    if node.func.attr in PROHIBITED_ATTR_CALLS:
                        raise ASTIsolationError(
                            f"Prohibited dynamic attribute function call '{node.func.attr}' detected in {file_path}"
                        )

        return True


class ExecutionSafetyGateway:
    """
    Single-point execution safety gateway enforcing payload validation, rate limiting,
    duplicate order lockout, and pre-submission solvency checks.
    """

    def __init__(
        self,
        circuit_breaker: Optional[CircuitBreakerEngine] = None,
        environment: str = "PAPER",
        available_cash: float = 1_000_000.0,
    ):
        if environment.upper() == "LIVE":
            raise PermissionError("Direct LIVE execution environment is strictly prohibited in Stage 11")

        self.environment = environment.upper()
        self.circuit_breaker = circuit_breaker or CircuitBreakerEngine()
        self._available_cash = float(available_cash)
        self._processed_order_ids: Set[str] = set()
        self._lock = threading.Lock()

    @property
    def available_cash(self) -> float:
        with self._lock:
            return self._available_cash

    def update_cash_balance(self, new_balance: float) -> None:
        with self._lock:
            if math.isnan(new_balance) or math.isinf(new_balance) or new_balance < 0.0:
                raise GatewayValidationError(f"Invalid cash balance: {new_balance}")
            self._available_cash = float(new_balance)

    def validate_and_process_order(self, payload: OrderPayload) -> bool:
        """
        Validate order payload, check solvency, check rate limits, and enforce duplicate lockout.
        """
        with self._lock:
            # 1. Circuit Breaker Check
            if self.circuit_breaker.is_halted:
                raise CircuitBreakerTripped("Gateway is in EMERGENCY_HALT state")

            # 2. Watchdog Check
            self.circuit_breaker.check_watchdog()

            # 3. Duplicate Order Lockout Check (INV-49 / AT-209)
            if payload.order_id in self._processed_order_ids:
                raise DuplicateOrderError(f"Duplicate order ID detected: {payload.order_id}")

            # 4. Monotonic Rate Limit Check (INV-51 / AT-200)
            self.circuit_breaker.validate_rate_limit()

            # 5. Pre-Submission Cash Solvency Check (AT-211)
            order_cost = payload.price * abs(payload.quantity)
            if order_cost > self._available_cash:
                raise GatewayValidationError(
                    f"Order cost ({order_cost:.2f}) exceeds available cash balance ({self._available_cash:.2f})"
                )

            # Record processed order ID
            self._processed_order_ids.add(payload.order_id)
            return True
