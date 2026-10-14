"""Deployment tests for secret exclusion in build context and image layers.

Tests:
8. test_build_context_excludes_populated_secret_files
9. test_canary_secrets_absent_from_all_image_layers
10. test_production_env_is_git_ignored
"""

import os
import shutil
import subprocess
from pathlib import Path
import fnmatch
import pytest

from tests.deployment.test_image_canary_layers import scan_image_tar_layers


def test_build_context_excludes_populated_secret_files():
    """Test 8: Assert .dockerignore exists and excludes populated secret files."""
    dockerignore_path = Path(".dockerignore")
    assert dockerignore_path.exists(), ".dockerignore file must exist in repository root."

    with open(dockerignore_path, "r") as f:
        patterns = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    # Files that MUST be excluded from Docker build context
    sensitive_files = [
        ".env",
        ".env.production",
        ".env.local",
        "algo_lab_paper.db",
        "data/app.db",
        ".venv/bin/activate",
        "__pycache__/something.pyc",
    ]

    for sf in sensitive_files:
        matched = any(
            fnmatch.fnmatch(sf, p) or fnmatch.fnmatch(os.path.basename(sf), p) or sf.startswith(p.rstrip("/*"))
            for p in patterns
        )
        assert matched, f"Sensitive file '{sf}' is not excluded by .dockerignore patterns: {patterns}"


def test_canary_secrets_absent_from_all_image_layers(tmp_path):
    """Test 9: Build production API image with synthetic canaries and inspect all layers.

    Real image positive and negative controls run in CI.
    Positive control: Builds actual production image and inspects every saved layer/config/history.
    Negative control: Builds an image that copies then deletes a synthetic canary; scanner must detect earlier layer.
    """
    docker_bin = shutil.which("docker")
    if not docker_bin:
        pytest.skip(
            "BLOCKED: Docker daemon unavailable on this host (Docker CLI missing; validated in CI). "
            "Reproducible command: docker build -t algo-lab:test -f docker/Dockerfile.api . && docker save algo-lab:test -o image.tar"
        )

    try:
        info_res = subprocess.run([docker_bin, "info"], capture_output=True, text=True, timeout=10)
        if info_res.returncode != 0:
            pytest.skip(
                f"BLOCKED: Docker daemon unavailable on this host ({info_res.stderr.strip() or 'daemon not running'}; validated in CI)."
            )
    except Exception as exc:
        pytest.skip(f"BLOCKED: Docker daemon unavailable on this host ({exc}; validated in CI).")

    # In CI/environments with Docker, execute real positive and negative control image tests:
    prod_image_tag = "algo-lab-prod:canary-layer-audit"
    neg_image_tag = "algo-lab-neg-control:canary-layer-audit"
    prod_tar = str(tmp_path / "prod_image.tar")
    neg_tar = str(tmp_path / "neg_image.tar")
    synthetic_canary = "CANARY_SYNTHETIC_LIVE_SECRET_LEAK_TOKEN_998877"

    try:
        # 1. POSITIVE CONTROL: Build actual production image and inspect every saved layer/config/history
        build_cmd = [
            docker_bin, "build",
            "-t", prod_image_tag,
            "-f", "docker/Dockerfile.api",
            "."
        ]
        build_res = subprocess.run(build_cmd, capture_output=True, text=True, timeout=600)
        assert build_res.returncode == 0, f"Production image build failed:\n{build_res.stderr}\n{build_res.stdout}"

        save_cmd = [docker_bin, "save", "-o", prod_tar, prod_image_tag]
        save_res = subprocess.run(save_cmd, capture_output=True, text=True, timeout=120)
        assert save_res.returncode == 0, f"Production image save failed: {save_res.stderr}"

        # Inspect all layers, configs, and history for sensitive tokens
        canary_tokens = [
            "ALGO_LAB_API_KEY",
            "CIRCUIT_BREAKER_REARM_SECRET",
            "BROKER_CREDENTIAL_ENCRYPTION_KEY",
            "algo_lab_paper.db",
            "algo_lab.db",
            ".env.production",
            ".env.local",
            "private.key",
            "cert.pem",
        ]
        findings = scan_image_tar_layers(prod_tar, canary_tokens)
        assert len(findings) == 0, f"Production image leaked canary secrets in layers/config: {findings}"

        # 2. NEGATIVE CONTROL: Build image that copies then deletes a synthetic canary; scanner must detect earlier layer
        neg_dockerfile = tmp_path / "Dockerfile.negative_control"
        neg_dockerfile.write_text(f"""FROM python:3.12-slim
WORKDIR /app
RUN echo "SYNTHETIC_SECRET={synthetic_canary}" > /app/secret_canary.env
RUN rm -f /app/secret_canary.env
""")
        neg_build_cmd = [
            docker_bin, "build",
            "-t", neg_image_tag,
            "-f", str(neg_dockerfile),
            str(tmp_path)
        ]
        neg_build_res = subprocess.run(neg_build_cmd, capture_output=True, text=True, timeout=300)
        assert neg_build_res.returncode == 0, f"Negative control build failed:\n{neg_build_res.stderr}\n{neg_build_res.stdout}"

        neg_save_cmd = [docker_bin, "save", "-o", neg_tar, neg_image_tag]
        neg_save_res = subprocess.run(neg_save_cmd, capture_output=True, text=True, timeout=120)
        assert neg_save_res.returncode == 0, f"Negative control save failed: {neg_save_res.stderr}"

        neg_findings = scan_image_tar_layers(neg_tar, [synthetic_canary])
        assert len(neg_findings) > 0, "Layer scanner failed to detect synthetic canary leaked in intermediate layer of negative control image!"
        assert any(f["canary"] == synthetic_canary for f in neg_findings), f"Expected canary token {synthetic_canary} in findings: {neg_findings}"

    finally:
        subprocess.run([docker_bin, "rmi", "-f", prod_image_tag, neg_image_tag], capture_output=True)


def test_production_env_is_git_ignored():
    """Test 10: Assert git check-ignore succeeds for .env.production and templates remain trackable."""
    res = subprocess.run(
        ["git", "check-ignore", ".env.production"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, ".env.production must be ignored by git (.gitignore)."

    # Templates must remain trackable
    res_template = subprocess.run(
        ["git", "check-ignore", ".env.example"],
        capture_output=True,
        text=True,
    )
    assert res_template.returncode != 0, ".env.example must remain trackable in git."

    res_prod_example = subprocess.run(
        ["git", "check-ignore", ".env.production.example"],
        capture_output=True,
        text=True,
    )
    assert res_prod_example.returncode != 0, ".env.production.example must remain trackable in git."
