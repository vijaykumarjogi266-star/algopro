"""Algo Lab: Canonical Project State & Metadata (Single Source of Truth).

This module defines the single, authoritative source of truth for:
1. Semantic Version (SemVer 2.0.0)
2. Build / Git Revision Identifier
3. Platform Lifecycle State (prototype, research, forward-paper-validation, release-candidate)
4. Non-Negotiable Paper-Only Safety Policy
"""

from __future__ import annotations

import os
import subprocess
from enum import Enum
from typing import Any, Dict


class LifecycleState(str, Enum):
    """Authoritative lifecycle states for Algo Lab."""
    PROTOTYPE = "prototype"
    RESEARCH = "research"
    FORWARD_PAPER_VALIDATION = "forward-paper-validation"
    RELEASE_CANDIDATE = "release-candidate"


# 1. Authoritative Semantic Version
SEMANTIC_VERSION: str = "0.2.0"

# 2. Authoritative Lifecycle State
CURRENT_LIFECYCLE_STATE: LifecycleState = LifecycleState.FORWARD_PAPER_VALIDATION

# 3. Non-Negotiable Safety Invariants
LIVE_TRADING_ENABLED: bool = False
REAL_BROKER_EXECUTION_ENABLED: bool = False

PAPER_ONLY_POLICY_NOTICE: str = (
    "Algo Lab operates strictly as a paper-only quantitative investment research and "
    "forward-simulation platform for Indian markets (NSE/BSE/MCX). Live capital deployment "
    "and real-money broker order transmission are permanently disabled by architecture."
)

NON_INVESTMENT_ADVICE_NOTICE: str = (
    "Algo Lab is a quantitative engineering and research software platform. It does not provide "
    "investment advice, portfolio management services, or financial recommendations. Past "
    "performance and simulated backtest results do not guarantee future returns."
)


def get_build_revision() -> str:
    """Resolve build revision from environment or git metadata."""
    env_rev = os.getenv("ALGO_LAB_BUILD_REVISION") or os.getenv("GIT_COMMIT_SHA")
    if env_rev:
        return env_rev.strip()

    try:
        rev = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2.0,
        ).strip()
        if rev:
            return rev
    except Exception:
        pass

    return "v0.2.0-paper-hardened"


def get_canonical_project_status() -> Dict[str, Any]:
    """Return the authoritative project status dictionary."""
    return {
        "project_name": "Algo Lab Quantitative Research OS",
        "version": SEMANTIC_VERSION,
        "build_revision": get_build_revision(),
        "lifecycle_state": CURRENT_LIFECYCLE_STATE.value,
        "live_trading_enabled": LIVE_TRADING_ENABLED,
        "real_broker_execution_enabled": REAL_BROKER_EXECUTION_ENABLED,
        "execution_mode": "paper_only",
        "policy": PAPER_ONLY_POLICY_NOTICE,
        "legal_notice": NON_INVESTMENT_ADVICE_NOTICE,
    }
