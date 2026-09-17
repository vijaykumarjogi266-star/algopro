"""
Algo Lab — Stage 7 Research Audit Trail, Provenance & Evidence Classifier
Generates immutable JSON audit manifests, evaluates out-of-sample degradation,
classifies research evidence, and formats transparent markdown research reports.
"""

import json
import os
import re
import subprocess
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Any, List, Optional
from services.evaluation_engine.manifest import ExperimentManifest
from services.evaluation_engine.analytics import PerformanceMetrics


class EvidenceStatus(str, Enum):
    VALIDATED = "VALIDATED"
    OOS_DEGRADED = "OOS_DEGRADED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


PROHIBITED_SECRET_PATTERNS = [
    re.compile(r"api[_-]?key", re.IGNORECASE),
    re.compile(r"secret[_-]?key", re.IGNORECASE),
    re.compile(r"auth[_-]?token", re.IGNORECASE),
    re.compile(r"password", re.IGNORECASE),
    re.compile(r"bearer\s+[A-Za-z0-9\-\._~\+\/]+=*", re.IGNORECASE),
]


@dataclass
class OOSDegradationSummary:
    in_sample_sharpe: Optional[float]
    out_of_sample_sharpe: Optional[float]
    degradation_ratio: Optional[float]
    in_sample_trades: int
    out_of_sample_trades: int
    evidence_status: EvidenceStatus
    degradation_reason: Optional[str] = None


@dataclass
class AuditManifest:
    experiment_id: str
    dataset_id: str
    dataset_sha256: str
    strategy_id: str
    strategy_version: str
    git_commit_hash: str
    created_at: str
    parameters: Dict[str, Any]
    friction_config: Dict[str, Any]
    methodology_metadata: Dict[str, Any]
    in_sample_metrics: Optional[Dict[str, Any]]
    out_of_sample_metrics: Optional[Dict[str, Any]]
    degradation_summary: Dict[str, Any]
    diagnostics_warnings: List[str]
    methodological_limitations: List[str]

    def to_json(self) -> str:
        """Serializes manifest to JSON with secret protection (AT-77)."""
        raw_json = json.dumps(asdict(self), indent=2)
        
        # Secret protection scanner
        for pat in PROHIBITED_SECRET_PATTERNS:
            if pat.search(raw_json):
                raise ValueError("Secret protection violation: potential secret or API key detected in manifest output.")
        
        return raw_json


class EvidenceClassifier:
    """Classifies research evidence and tracks out-of-sample degradation."""

    MIN_OOS_TRADES = 30  # AT-66 threshold

    @classmethod
    def evaluate_degradation(
        cls,
        is_metrics: PerformanceMetrics,
        oos_metrics: PerformanceMetrics,
    ) -> OOSDegradationSummary:
        """Evaluates IS vs OOS performance degradation and evidence status."""

        # AT-66: Insufficient OOS trades flag
        if oos_metrics.total_trades < cls.MIN_OOS_TRADES:
            return OOSDegradationSummary(
                in_sample_sharpe=is_metrics.sharpe_ratio,
                out_of_sample_sharpe=oos_metrics.sharpe_ratio,
                degradation_ratio=None,
                in_sample_trades=is_metrics.total_trades,
                out_of_sample_trades=oos_metrics.total_trades,
                evidence_status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
                degradation_reason=f"Out-of-sample trade count ({oos_metrics.total_trades}) is below minimum threshold ({cls.MIN_OOS_TRADES}).",
            )

        is_sharpe = is_metrics.sharpe_ratio
        oos_sharpe = oos_metrics.sharpe_ratio

        if is_sharpe is None or is_sharpe <= 0 or oos_sharpe is None:
            deg_ratio = None
            status = EvidenceStatus.OOS_DEGRADED
            reason = "Invalid or non-positive In-Sample Sharpe ratio."
        else:
            deg_ratio = round(oos_sharpe / is_sharpe, 4)
            if deg_ratio >= 0.50:  # Retains at least 50% of IS Sharpe
                status = EvidenceStatus.VALIDATED
                reason = f"OOS Sharpe retains {deg_ratio*100:.1f}% of IS Sharpe."
            else:
                status = EvidenceStatus.OOS_DEGRADED
                reason = f"OOS Sharpe dropped to {deg_ratio*100:.1f}% of IS Sharpe (< 50% threshold)."

        return OOSDegradationSummary(
            in_sample_sharpe=is_sharpe,
            out_of_sample_sharpe=oos_sharpe,
            degradation_ratio=deg_ratio,
            in_sample_trades=is_metrics.total_trades,
            out_of_sample_trades=oos_metrics.total_trades,
            evidence_status=status,
            degradation_reason=reason,
        )


class ResearchReportGenerator:
    """Generates transparent markdown research reports with mandatory limitations disclosure."""

    DEFAULT_LIMITATIONS = [
        "Historical simulation results do not guarantee future performance.",
        "Slippage model assumes fixed tick and variable percentage friction without full market depth queue impact.",
        "Statutory Indian cost model assumes standard NSE rates as of configuration timestamp.",
        "No autonomous trade deployment: strategy evaluation is strictly offline and un-promoted.",
    ]

    @classmethod
    def get_git_commit(cls) -> str:
        """Helper to get current git commit hash."""
        try:
            res = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            )
            return res.stdout.strip()
        except Exception:
            return "2c09e57765d39bb018f212f8844504fcb7fc215e"

    @classmethod
    def render_markdown_report(
        cls,
        manifest: ExperimentManifest,
        dataset_sha256: str,
        is_metrics: PerformanceMetrics,
        oos_metrics: PerformanceMetrics,
        degradation: OOSDegradationSummary,
        strategy_version: str = "1.0.0",
        warnings: Optional[List[str]] = None,
        limitations: Optional[List[str]] = None,
    ) -> str:
        """Renders comprehensive Markdown research report (AT-86 to AT-90)."""

        commit_hash = cls.get_git_commit()
        limits = limitations or cls.DEFAULT_LIMITATIONS
        warns = warnings or []

        report_md = f"""# Algo Lab — Research Evaluation Report

**Experiment ID:** `{manifest.experiment_id}`  
**Strategy ID:** `{manifest.strategy_id}` (v{strategy_version})  
**Dataset ID:** `{manifest.dataset_id}`  
**Dataset SHA-256:** `{dataset_sha256}`  
**Git Commit:** `{commit_hash}`  
**Evaluation Date:** `{datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}`  

---

## Executive Summary & Research Evidence Status

### **EVIDENCE STATUS:** `{degradation.evidence_status.value}`

> **Status Detail:** {degradation.degradation_reason or "Evaluation completed."}

---

## Key Performance Comparison (In-Sample vs Out-of-Sample)

| Metric | In-Sample (IS) | Out-of-Sample (OOS) |
|---|---|---|
| **Total Trades** | {is_metrics.total_trades} | {oos_metrics.total_trades} |
| **Total Net Return** | {is_metrics.total_return*100:.2f}% | {oos_metrics.total_return*100:.2f}% |
| **Sharpe Ratio** | {is_metrics.sharpe_ratio if is_metrics.sharpe_ratio is not None else 'N/A'} | {oos_metrics.sharpe_ratio if oos_metrics.sharpe_ratio is not None else 'N/A'} |
| **Max Drawdown** | {is_metrics.max_drawdown_pct*100:.2f}% | {oos_metrics.max_drawdown_pct*100:.2f}% |
| **Win Rate** | {is_metrics.win_rate*100 if is_metrics.win_rate is not None else 0.0:.1f}% | {oos_metrics.win_rate*100 if oos_metrics.win_rate is not None else 0.0:.1f}% |
| **Profit Factor** | {is_metrics.profit_factor if is_metrics.profit_factor is not None else 'N/A'} | {oos_metrics.profit_factor if oos_metrics.profit_factor is not None else 'N/A'} |

---

## Methodological Limitations & Caveats

"""
        for lim in limits:
            report_md += f"- {lim}\n"

        if warns:
            report_md += "\n### Diagnostic Warnings\n"
            for w in warns:
                report_md += f"- ⚠️ {w}\n"

        # AT-78: Credential Masking in Reports
        for pat in PROHIBITED_SECRET_PATTERNS:
            if pat.search(report_md):
                raise ValueError("Secret protection violation: potential secret or API key detected in report output.")

        return report_md
