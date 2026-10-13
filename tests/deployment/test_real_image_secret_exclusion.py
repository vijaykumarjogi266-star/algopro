"""Deployment tests for Docker secret exclusion and build context canary protection.

Tests:
- T24 test_dockerignore_rules_exclude_sensitive_artifacts
- T25 test_build_context_canary_exclusion
"""

import fnmatch
import os
from pathlib import Path
import pytest


def parse_dockerignore_rules(dockerignore_path: Path = Path(".dockerignore")) -> list[str]:
    """Parse .dockerignore rules, ignoring blank lines and comments."""
    assert dockerignore_path.exists(), f"{dockerignore_path} must exist"
    with open(dockerignore_path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]


def is_docker_ignored(rel_path: str, rules: list[str]) -> bool:
    """Evaluates whether a relative path is ignored based on standard Dockerignore semantics.
    
    Dockerignore behavior:
    - Rules are evaluated sequentially.
    - Patterns with '/' match against path relative to context root.
    - Patterns without '/' match against basename anywhere or path relative to context root.
    - Directory matches (like .git) match any descendant path.
    - '!' negates exclusion.
    """
    ignored = False
    norm_path = os.path.normpath(rel_path)
    base_name = os.path.basename(rel_path)
    parts = norm_path.split(os.sep)

    for rule in rules:
        rule = rule.strip()
        if not rule or rule.startswith("#"):
            continue
        negated = rule.startswith("!")
        if negated:
            rule = rule[1:].strip()

        matched = False
        if "/" in rule:
            clean_rule = rule.lstrip("/")
            matched = (
                fnmatch.fnmatch(norm_path, clean_rule)
                or fnmatch.fnmatch(norm_path, clean_rule + "/*")
                or norm_path.startswith(clean_rule.rstrip("/*") + "/")
            )
        else:
            # Matches basename, full path, or any directory prefix component
            matched = (
                fnmatch.fnmatch(base_name, rule)
                or fnmatch.fnmatch(norm_path, rule)
                or any(fnmatch.fnmatch(p, rule) for p in parts[:-1])
            )

        if matched:
            ignored = not negated

    return ignored


def test_dockerignore_rules_exclude_sensitive_artifacts():
    """T24: Assert .dockerignore explicitly contains strict exclusion patterns for sensitive artifacts."""
    rules = parse_dockerignore_rules()

    # Required patterns that MUST be present
    required_patterns = [
        "*.db",
        "*.sqlite",
        "*.sqlite3",
        "*-wal",
        "*-shm",
        "*.backup*",
        "*.bak",
        "data/*.db*",
        "data/*.json",
        "circuit_breaker_state.json",
        "data/circuit_breaker_state.json",
        ".env",
        ".env.*",
        "!.env.example",
        "*.pem",
        "*.key",
        ".git",
    ]

    for pattern in required_patterns:
        assert pattern in rules, f"Required pattern '{pattern}' missing from .dockerignore"


def test_build_context_canary_exclusion():
    """T25: Simulate Docker build context exclusion on sensitive canary files.
    
    Verifies that canary artifacts (e.g. test.db-wal, data/cb.json, credentials.backup)
    are strictly excluded, while allowable template files remain included.
    """
    rules = parse_dockerignore_rules()

    # Mandatory canary sensitive files that must be excluded
    canary_exclusions = [
        "test.db-wal",
        "data/cb.json",
        "credentials.backup",
        "test.db-shm",
        "algo_lab.db",
        "production.sqlite",
        "orders.sqlite3",
        "creds.backup_20261013",
        "old_state.bak",
        "data/live.db",
        "data/orders.db-wal",
        "circuit_breaker_state.json",
        "data/circuit_breaker_state.json",
        ".env",
        ".env.production",
        ".env.local",
        "tls_private.key",
        "server.pem",
        ".git/HEAD",
        ".git/config",
    ]

    for canary in canary_exclusions:
        assert is_docker_ignored(canary, rules), (
            f"Build context canary '{canary}' was NOT excluded by .dockerignore rules!"
        )

    # Allowed / non-sensitive files that must NOT be excluded
    canary_inclusions = [
        ".env.example",
        ".env.production.example",
        "README.md",
        "pyproject.toml",
        "services/paper-engine/adapters/credentials.py",
    ]

    for canary in canary_inclusions:
        assert not is_docker_ignored(canary, rules), (
            f"Legitimate file '{canary}' was incorrectly excluded by .dockerignore!"
        )
