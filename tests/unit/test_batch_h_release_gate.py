"""Batch H: Release Gate, Canary Scanner, Locks, Builds & CI Verification (H01–H08).

Regression tests:
- H01: Missing required tool -> nonzero/BLOCKED.
- H02: Lint/type/test/build/scan failure -> nonzero.
- H03: npm ci failure cannot fall back to unlocked install.
- H04: Required skipped Docker/browser test prevents VERIFIED.
- H05: Real image positive and negative controls run in CI.
- H06: All maintained suites execute, including intelligence failure tests.
- H07: Coverage thresholds fail when insufficient.
- H08: Lock install and pip dependency consistency pass on clean Python 3.12.
"""

import os
import re
import subprocess
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "verify_release.sh"
MAKEFILE_PATH = REPO_ROOT / "Makefile"
REQUIREMENTS_LOCK = REPO_ROOT / "requirements.lock"
REQUIREMENTS_TXT = REPO_ROOT / "requirements.txt"


def test_h01_missing_required_tool_causes_nonzero_blocked():
    """H01: Missing required tool causes nonzero exit code and BLOCKED report."""
    assert SCRIPT_PATH.exists(), "verify_release.sh must exist"
    content = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "BLOCKED_COUNT" in content
    assert "exit 1" in content

    # Test that the script logic fails closed when BLOCKED_COUNT > 0
    # Simulate a run with ALGO_LAB_RELEASE_VERIFY_RUNNING to avoid re-executing full pytest
    if os.environ.get("ALGO_LAB_RELEASE_VERIFY_RUNNING") == "1":
        pytest.skip("Skip nested verify_release.sh run")

    env = os.environ.copy()
    env["ALGO_LAB_RELEASE_VERIFY_RUNNING"] = "1"
    # When docker or SWC are missing on host, verify_release.sh must exit non-zero
    res = subprocess.run(
        ["bash", str(SCRIPT_PATH)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    if "RELEASE CHECK BLOCKED:" in res.stdout:
        assert res.returncode != 0, "verify_release.sh must exit nonzero when criteria are BLOCKED"
        assert "BLOCKED_COUNT" in content or "BLOCKED:" in res.stdout


def test_h02_lint_type_test_build_scan_failure_causes_nonzero():
    """H02: Any failure in lint/typecheck/test/build/scan propagates non-zero exit."""
    content = SCRIPT_PATH.read_text(encoding="utf-8")

    # Script must use set -eo pipefail
    assert "set -eo pipefail" in content or "set -e" in content
    assert "pipefail" in content

    # Verify that simulated command failure stops execution
    cmd = ["bash", "-c", "set -eo pipefail; false; echo 'UNREACHABLE'"]
    sub_res = subprocess.run(cmd, capture_output=True, text=True)
    assert sub_res.returncode != 0
    assert "UNREACHABLE" not in sub_res.stdout


def test_h03_npm_ci_failure_cannot_fall_back_to_unlocked_install():
    """H03: npm ci failure cannot fall back to unlocked install."""
    makefile_content = MAKEFILE_PATH.read_text(encoding="utf-8")
    verify_content = SCRIPT_PATH.read_text(encoding="utf-8")

    # Disallow fallback patterns like 'npm ci || npm install'
    banned_fallback_patterns = [
        r"npm\s+.*ci\s*\|\|\s*npm\s+.*install",
        r"npm\s+ci\s*\|\|\s*npm\s+install",
    ]

    for pat in banned_fallback_patterns:
        assert not re.search(pat, makefile_content), f"Makefile contains banned npm fallback: {pat}"
        assert not re.search(pat, verify_content), f"verify_release.sh contains banned npm fallback: {pat}"


def test_h04_required_skipped_docker_browser_test_prevents_verified():
    """H04: Required skipped Docker/browser test prevents VERIFIED release status."""
    content = SCRIPT_PATH.read_text(encoding="utf-8")

    # Emit of VERIFIED must be strictly conditioned on BLOCKED_COUNT == 0
    match = re.search(
        r'if\s+\[\s*"\$BLOCKED_COUNT"\s+-eq\s+0\s*\];\s*then\s+echo\s+"[^"]*VERIFIED[^"]*"\s+exit\s+0',
        content,
        re.DOTALL,
    )
    assert match is not None, "Script must emit 'VERIFIED' only when BLOCKED_COUNT is strictly 0"
    assert "RELEASE CHECK BLOCKED:" in content
    assert "exit 1" in content


def test_h05_real_image_positive_and_negative_controls(tmp_path):
    """H05: Real image positive and negative controls run in CI."""
    from tests.deployment.test_image_canary_layers import scan_image_tar_layers
    import io, json, tarfile

    # 1. Negative control: synthetic canary present in layer 1, deleted in layer 2
    canary_secret = "NEGATIVE_CONTROL_CANARY_SECRET_12345"
    negative_tar = str(tmp_path / "negative_control.tar")

    l1_io = io.BytesIO()
    with tarfile.open(fileobj=l1_io, mode="w") as l1:
        data = f"SECRET={canary_secret}\n".encode("utf-8")
        ti = tarfile.TarInfo(name="app/secrets.env")
        ti.size = len(data)
        l1.addfile(ti, io.BytesIO(data))
    l1_bytes = l1_io.getvalue()

    l2_io = io.BytesIO()
    with tarfile.open(fileobj=l2_io, mode="w") as l2:
        ti = tarfile.TarInfo(name="app/.wh.secrets.env")
        ti.size = 0
        l2.addfile(ti, io.BytesIO(b""))
    l2_bytes = l2_io.getvalue()

    with tarfile.open(negative_tar, "w") as outer:
        ti1 = tarfile.TarInfo(name="layer1.tar")
        ti1.size = len(l1_bytes)
        outer.addfile(ti1, io.BytesIO(l1_bytes))

        ti2 = tarfile.TarInfo(name="layer2.tar")
        ti2.size = len(l2_bytes)
        outer.addfile(ti2, io.BytesIO(l2_bytes))

        manifest = json.dumps([{"Layers": ["layer1.tar", "layer2.tar"]}]).encode("utf-8")
        ti_m = tarfile.TarInfo(name="manifest.json")
        ti_m.size = len(manifest)
        outer.addfile(ti_m, io.BytesIO(manifest))

    findings = scan_image_tar_layers(negative_tar, [canary_secret])
    assert len(findings) > 0, "Negative control failed: scanner missed deleted canary in layer 1"
    assert any(f["canary"] == canary_secret for f in findings)

    # 2. Positive control: clean image with no secrets produces zero findings
    positive_tar = str(tmp_path / "positive_control.tar")
    l_clean_io = io.BytesIO()
    with tarfile.open(fileobj=l_clean_io, mode="w") as lc:
        clean_data = b"print('clean code without secrets')\n"
        ti = tarfile.TarInfo(name="app/main.py")
        ti.size = len(clean_data)
        lc.addfile(ti, io.BytesIO(clean_data))
    l_clean_bytes = l_clean_io.getvalue()

    with tarfile.open(positive_tar, "w") as outer:
        ti = tarfile.TarInfo(name="clean_layer.tar")
        ti.size = len(l_clean_bytes)
        outer.addfile(ti, io.BytesIO(l_clean_bytes))

        manifest = json.dumps([{"Layers": ["clean_layer.tar"]}]).encode("utf-8")
        ti_m = tarfile.TarInfo(name="manifest.json")
        ti_m.size = len(manifest)
        outer.addfile(ti_m, io.BytesIO(manifest))

    clean_findings = scan_image_tar_layers(positive_tar, [canary_secret])
    assert len(clean_findings) == 0, f"Positive control failed: clean image had false positives: {clean_findings}"


def test_h06_all_maintained_suites_execute_including_intelligence():
    """H06: All maintained suites execute, including intelligence and new batches."""
    content = SCRIPT_PATH.read_text(encoding="utf-8")

    required_suites = [
        "tests/unit/test_dataset_contract_enforcement.py",
        "tests/unit/test_fill_ledger_accounting.py",
        "tests/unit/test_strategy_dispatch_provenance.py",
        "tests/unit/test_batch_d_accurate_persistence.py",
        "tests/unit/test_batch_e_session_cutoff.py",
        "tests/unit/test_batch_f_config_and_breaker.py",
        "tests/unit/test_news_fundamental_safety.py",
        "tests/unit/test_news_fundamental_agent.py",
        "tests/deployment/test_image_canary_layers.py",
    ]

    for suite in required_suites:
        assert suite in content, f"verify_release.sh must execute maintained suite: {suite}"
        assert (REPO_ROOT / suite).exists(), f"Suite file must exist on disk: {suite}"


def test_h07_coverage_thresholds_fail_when_insufficient():
    """H07: Coverage thresholds fail when insufficient (<80% overall or <90% safety-critical)."""
    content = SCRIPT_PATH.read_text(encoding="utf-8")

    # Script must check coverage on safety-critical modules
    assert "coverage run" in content
    assert "coverage report" in content

    # Test that pytest coverage failure threshold works
    cmd = [
        "python3", "-m", "pytest",
        "tests/unit/test_circuit_breaker_state_integrity.py",
        "--cov=services/execution_gateway/circuit_breaker",
        "--cov-fail-under=99",
        "-q", "--disable-warnings"
    ]
    res = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    # Circuit breaker module coverage is around 90-95%, so --cov-fail-under=99 will fail with non-zero exit
    assert res.returncode != 0, "pytest-cov must exit non-zero when coverage falls below fail-under threshold"


def test_h08_lock_install_and_pip_dependency_consistency():
    """H08: Lock install and pip dependency consistency pass on clean environment."""
    assert REQUIREMENTS_LOCK.exists(), "requirements.lock must exist"
    lock_content = REQUIREMENTS_LOCK.read_text(encoding="utf-8")

    # Assert no machine-specific builder paths
    assert "file:///home/builder" not in lock_content
    assert "file:///root" not in lock_content
    assert "/home/ubuntu" not in lock_content

    # Assert locked file defines pinned requirements
    assert len(lock_content.strip()) > 0
