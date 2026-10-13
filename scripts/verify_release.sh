#!/usr/bin/env bash
# Algo Lab Release Verification Script
# Executes release gate checks and exits non-zero if any mandatory check fails.
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

echo "=========================================================="
echo "      ALGO LAB: COMPREHENSIVE RELEASE VERIFICATION       "
echo "=========================================================="

echo ">>> [1/7] Python syntax compilation..."
python3 -m compileall -q apps data database quant services
echo "[PASS] Python syntax clean."

echo ">>> [2/7] Safety-critical and Security test suites..."
python3 -m pytest -q \
  tests/unit/test_circuit_breaker_security.py \
  tests/unit/test_backtest_simulation.py \
  tests/unit/test_credentials_security.py \
  tests/unit/test_daemon_risk_state.py \
  tests/unit/test_vwap_research.py \
  tests/unit/test_backtest_step7.py \
  tests/unit/test_stage5_integrity.py \
  --disable-warnings
echo "[PASS] Security and regression test suites passed."

echo ">>> [3/7] Custom Security and Integrity verification scripts..."
python3 scripts/verify_no_plaintext_credentials.py
python3 scripts/verify_sqlite_backup_restore.py
python3 scripts/verify_restart_fail_closed.py
echo "[PASS] Persistence, encryption, and restart safety verified."

echo ">>> [4/7] Secret scanning check (asserting no hardcoded production secrets)..."
python3 -c "
import os, sys
banned = 'ADMIN_' + 'SECURE_' + 'REARM_' + 'SECRET_KEY_8899'
found = []
for root, dirs, files in os.walk('.'):
    if any(x in root for x in ['.git', '.venv', 'node_modules', '__pycache__']):
        continue
    for f in files:
        if f == 'verify_release.sh':
            continue
        p = os.path.join(root, f)
        try:
            with open(p, 'r', errors='ignore') as fp:
                if banned in fp.read():
                    found.append(p)
        except Exception:
            pass
if found:
    print('Found banned secret in:', found)
    sys.exit(1)
"
echo "[PASS] Zero committed secrets detected."
if grep -R --line-number --fixed-strings "algolab_secret" .env.production.example docker-compose.prod.yml 2>/dev/null; then
    echo "[FAIL] Insecure default secret found in production configs!"
    exit 1
fi
echo "[PASS] Zero committed secrets detected."

echo ">>> [5/7] Configuration syntax validation..."
python3 -m json.tool apps/web/package.json >/dev/null
python3 -c "import json; [json.load(open(f)) for f in ['apps/web/tsconfig.json']]"
echo "[PASS] Configuration syntax valid."

echo ">>> [6/7] Dependency locks validation..."
test -f requirements.lock && test -f .python-version && test -f .nvmrc
echo "[PASS] Runtime specifications and lockfiles present."

echo ">>> [7/7] Paper-trading safety lock invariance check..."
python3 -c "
from services.paper_engine.adapters.credentials import LIVE_TRADING_ENABLED, REAL_BROKER_EXECUTION_ENABLED
assert LIVE_TRADING_ENABLED is False, 'LIVE_TRADING_ENABLED must be False'
assert REAL_BROKER_EXECUTION_ENABLED is False, 'REAL_BROKER_EXECUTION_ENABLED must be False'
"
echo "[PASS] Strict paper-only trading locks confirmed."

echo "=========================================================="
echo "    VERIFIED: ALL AUTOMATED RELEASE CRITERIA PASSED      "
echo "=========================================================="
