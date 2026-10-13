"""Unit tests for release gate script and Makefile validation (T53–T56).

Tests:
T53: test_verify_release_fails_on_missing_tool_when_enforced
T54: test_verify_release_runs_all_required_suites
T55: test_makefile_targets_exist_and_executable
T56: test_no_hardcoded_pass_counts_or_masking_in_release_scripts
"""

import os
import re
import subprocess
import pytest


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
SCRIPT_PATH = os.path.join(REPO_ROOT, "scripts/verify_release.sh")
MAKEFILE_PATH = os.path.join(REPO_ROOT, "Makefile")


def test_verify_release_fails_on_missing_tool_when_enforced():
    """T53: verify_release.sh exits non-zero or reports BLOCKED when mandatory tools fail."""
    assert os.path.exists(SCRIPT_PATH), "verify_release.sh must exist"
    with open(SCRIPT_PATH, "r") as f:
        content = f.read()

    # Script must track blocked checks and exit with non-zero if mandatory checks fail in strict mode
    assert "BLOCKED_COUNT" in content
    assert "set -eo pipefail" in content or "set -e" in content


def test_verify_release_runs_all_required_suites():
    """T54: verify_release.sh includes all mandatory security, integration, and unit suites."""
    with open(SCRIPT_PATH, "r") as f:
        content = f.read()

    required_suites = [
        "test_security_configuration.py",
        "test_authorization_enforcement.py",
        "test_execution_control_wiring.py",
        "test_durable_breaker_recovery.py",
    ]

    for suite in required_suites:
        assert suite in content, f"verify_release.sh must execute {suite}"


def test_makefile_targets_exist_and_executable():
    """T55: Makefile defines all mandatory release targets."""
    assert os.path.exists(MAKEFILE_PATH), "Makefile must exist"
    with open(MAKEFILE_PATH, "r") as f:
        content = f.read()

    required_targets = [
        "install",
        "import-check",
        "lint",
        "typecheck",
        "test",
        "test-security",
        "test-browser",
        "build",
        "test-deployment",
        "security-scan",
        "release-check",
    ]

    for target in required_targets:
        # Match target definition at start of line
        pattern = rf"^{re.escape(target)}:"
        assert re.search(pattern, content, re.MULTILINE), f"Makefile must define target '{target}:'"


def test_no_hardcoded_pass_counts_or_masking_in_release_scripts():
    """T56: verify_release.sh contains zero hardcoded pass counts and zero '|| true' on mandatory tests."""
    with open(SCRIPT_PATH, "r") as f:
        content = f.read()

    # Disallow fake hardcoded pass counts like "(86 passed)"
    assert not re.search(r"\(\d+\s+passed\)", content, re.IGNORECASE), (
        "verify_release.sh must not contain hardcoded test pass counts like '(86 passed)'"
    )

    # Disallow masking of pytest runs with || true
    for line in content.splitlines():
        if "pytest" in line and not line.strip().startswith("#"):
            assert "|| true" not in line, f"Pytest execution must not be masked with || true: {line}"
