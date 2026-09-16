"""Algo Lab Reproducibility & Run Fingerprint Generator.

Adheres to Non-Negotiable Principles:
- Principle 7: Every backtest must be reproducible.
- Principle 8: Every strategy must be versioned.
- Principle 9: Every dataset must be versioned.
- Principle 10: Every experiment must be auditable.
"""

import hashlib
import json
from typing import Any, Dict


def canonicalize(obj: Any) -> Any:
    """Recursively normalizes objects for deterministic hashing."""
    if isinstance(obj, dict):
        return {str(k): canonicalize(v) for k, v in sorted(obj.items())}
    elif isinstance(obj, (list, tuple, set)):
        return [canonicalize(x) for x in obj]
    elif isinstance(obj, float):
        return round(obj, 8)
    elif isinstance(obj, (int, str, bool)) or obj is None:
        return obj
    elif hasattr(obj, "value"):
        return obj.value
    elif hasattr(obj, "model_dump"):  # Pydantic v2
        return canonicalize(obj.model_dump())
    elif hasattr(obj, "dict"):  # Pydantic v1
        return canonicalize(obj.dict())
    else:
        return str(obj)


def compute_reproducibility_hash(config: Dict[str, Any]) -> str:
    """Computes a canonical SHA-256 fingerprint for backtesting reproducibility."""
    volatile_keys = {
        "experiment_id", "run_id", "created_at", "reproducibility_hash",
        "metrics", "trades", "equity_curve", "timestamp"
    }
    filtered = {k: v for k, v in config.items() if k not in volatile_keys}
    normalized = canonicalize(filtered)
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
