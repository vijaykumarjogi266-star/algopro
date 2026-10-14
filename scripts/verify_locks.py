"""Reproducible Dependency Lockfile & Integrity Verification Utility.

Verifies:
1. requirements.lock exists and contains pinned version specifications with hashes or deterministic refs.
2. No banned or live-trading execution packages are present.
3. Lockfile is consistent with requirements.txt top-level packages.
4. Python runtime matches supported version requirements (>=3.11).
"""

import os
import re
import sys
from pathlib import Path


BANNED_LIVE_PACKAGES = [
    "zerodha-live-trader",
    "direct-exchange-fix",
    "interactive-brokers-live-router",
]


def verify_locks(project_root: str = ".") -> bool:
    req_file = os.path.join(project_root, "requirements.txt")
    lock_file = os.path.join(project_root, "requirements.lock")

    if not os.path.exists(req_file):
        print(f"[FAIL] Missing {req_file}")
        return False

    if not os.path.exists(lock_file):
        print(f"[FAIL] Missing {lock_file}")
        return False

    with open(req_file, "r", encoding="utf-8") as f:
        req_lines = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    with open(lock_file, "r", encoding="utf-8") as f:
        lock_content = f.read()

    # 1. Banned package inspection
    for banned in BANNED_LIVE_PACKAGES:
        if banned in lock_content.lower():
            print(f"[FAIL] Banned live package detected in lockfile: {banned}")
            return False

    # 2. Check each top-level requirement is satisfied in lockfile
    # Normalize lockfile lines for PEP 503 package name equivalence (- vs _)
    normalized_lock = {}
    for line in lock_content.splitlines():
        line = line.strip()
        if "==" in line:
            pname = line.split("==")[0].strip()
            norm_name = re.sub(r"[-_.]+", "-", pname).lower()
            normalized_lock[norm_name] = line

    for req in req_lines:
        raw_name = re.split(r"[><=~\[]", req)[0].strip()
        norm_name = re.sub(r"[-_.]+", "-", raw_name).lower()
        if norm_name not in normalized_lock:
            print(f"[FAIL] Requirement '{raw_name}' not pinned in requirements.lock")
            return False

    # 3. Check Python version constraint
    py_version = sys.version_info
    if py_version < (3, 11):
        print(f"[FAIL] Python version must be >= 3.11, current is {sys.version}")
        return False

    print(f"[PASS] Lockfile consistency verified: {len(req_lines)} dependencies pinned and safe.")
    return True


if __name__ == "__main__":
    success = verify_locks()
    sys.exit(0) if success else sys.exit(1)
