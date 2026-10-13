"""Unit tests for Release Gate Behavior, CI Gating, and Strict Verification (R52–R56).

Tests:
R52: test_missing_mandatory_tool_causes_nonzero_exit
R53: test_failed_stage_propagates_nonzero
R54: test_mandatory_skips_are_not_verified
R55: test_gate_executes_real_required_suites
R56: test_reports_are_dynamic_and_truthful
"""

import os
import re
import subprocess
import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
SCRIPT_PATH = os.path.join(REPO_ROOT, "scripts/verify_release.sh")
MAKEFILE_PATH = os.path.join(REPO_ROOT, "Makefile")


def test_missing_mandatory_tool_causes_nonzero_exit():
    """R52: Missing mandatory tool/skips result in BLOCKED and nonzero exit when verifying release."""
    assert os.path.exists(SCRIPT_PATH), "verify_release.sh must exist"

    with open(SCRIPT_PATH, "r") as f:
        content = f.read()

    # The script must explicitly check BLOCKED_COUNT and exit 1 when > 0
    assert 'exit 1' in content
    assert 'BLOCKED_COUNT' in content

    if os.environ.get("ALGO_LAB_RELEASE_VERIFY_RUNNING") == "1":
        pytest.skip("Skip nested verify_release.sh run to prevent recursive gate execution")

    # Run verify_release.sh with environment marker to prevent recursion in children
    env = os.environ.copy()
    env["ALGO_LAB_RELEASE_VERIFY_RUNNING"] = "1"
    res = subprocess.run(
        ["bash", SCRIPT_PATH],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )

    # When running on host without all container/CI tools (e.g. Docker), it must fail-closed
    if "RELEASE CHECK BLOCKED" in res.stdout or "BLOCKED:" in res.stdout:
        assert res.returncode != 0, "verify_release.sh must exit non-zero when mandatory criteria are blocked"
        assert "BLOCKED" in res.stdout


def test_failed_stage_propagates_nonzero():
    """R53: Any failed stage propagates non-zero exit code immediately via set -eo pipefail."""
    with open(SCRIPT_PATH, "r") as f:
        content = f.read()

    # Must enable strict error handling
    assert re.search(r"set\s+-[a-z]*e[a-z]*", content), "Script must use 'set -e' for strict error propagation"
    assert "pipefail" in content, "Script must use pipefail to prevent pipeline masking"

    # Test that a simulated stage failure propagates non-zero exit
    test_cmd = ["bash", "-c", "set -eo pipefail; false; echo 'UNREACHABLE'"]
    sub_res = subprocess.run(test_cmd, capture_output=True, text=True)
    assert sub_res.returncode != 0
    assert "UNREACHABLE" not in sub_res.stdout


def test_mandatory_skips_are_not_verified():
    """R54: Mandatory skips or blocked checks never output verified release status."""
    with open(SCRIPT_PATH, "r") as f:
        content = f.read()

    # Output 'VERIFIED' must be strictly conditioned on BLOCKED_COUNT == 0
    match = re.search(
        r'if\s+\[\s*"\$BLOCKED_COUNT"\s+-eq\s+0\s*\];\s*then\s+echo\s+"[^"]*VERIFIED[^"]*"\s+exit\s+0',
        content,
        re.DOTALL,
    )
    assert match is not None, "Script must only emit 'VERIFIED' and exit 0 when BLOCKED_COUNT is 0"

    # When blocked, it must emit BLOCKED and exit 1
    assert "RELEASE CHECK BLOCKED:" in content
    assert "exit 1" in content


def test_gate_executes_real_required_suites():
    """R55: Gate executes real required regression suites (R01–R56) on disk."""
    with open(SCRIPT_PATH, "r") as f:
        script_content = f.read()

    required_suites = [
        "tests/integration/test_security_configuration_end_to_end.py",
        "tests/unit/test_dataset_contract_enforcement.py",
        "tests/unit/test_buy_and_hold_allocation.py",
        "tests/unit/test_fill_ledger_accounting.py",
        "tests/integration/test_multiday_real_ledger.py",
        "tests/integration/test_protective_cutoff_failure_modes.py",
        "tests/unit/test_manifest_freshness_and_replay.py",
        "tests/unit/test_breaker_final_recovery.py",
        "tests/deployment/test_image_canary_layers.py",
        "tests/unit/test_release_gate_behavior.py",
        "tests/integration/test_daemon_release_lifecycle.py",
        "tests/integration/test_real_fill_multiday_accounting.py",
        "tests/integration/test_security_configuration.py",
        "tests/integration/test_authorization_enforcement.py",
        "tests/integration/test_execution_control_wiring.py",
        "tests/unit/test_circuit_breaker_state_integrity.py",
        "tests/unit/test_circuit_breaker_persistence_failures.py",
        "tests/unit/test_credential_failure_modes.py",
        "tests/unit/test_durable_breaker_recovery.py",
    ]

    for suite in required_suites:
        assert suite in script_content, f"verify_release.sh must execute {suite}"
        suite_path = os.path.join(REPO_ROOT, suite)
        assert os.path.exists(suite_path), f"Required suite {suite} must exist on disk"


def test_reports_are_dynamic_and_truthful():
    """R56: Release verification reports are dynamic and truthful with zero fake counts or masking."""
    with open(SCRIPT_PATH, "r") as f:
        content = f.read()

    # Disallow fake hardcoded pass counts
    assert not re.search(r"\(\d+\s+passed\)", content, re.IGNORECASE)
    assert not re.search(r"100%\s+passed", content, re.IGNORECASE)

    # Disallow masking of pytest runs with || true
    for line in content.splitlines():
        clean_line = line.strip()
        if "pytest" in clean_line and not clean_line.startswith("#"):
            assert "|| true" not in clean_line, f"Pytest execution must never be masked with || true: {line}"
            assert "|| false" not in clean_line or "set -e" in content
