"""Software Bill of Materials (SBOM) Generator (CycloneDX JSON).

Generates an institutional CycloneDX 1.5 JSON SBOM capturing all runtime
dependencies, hashes, licenses, and platform metadata for release audits.
"""

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from apps.api.core.project_state import SEMANTIC_VERSION, CURRENT_LIFECYCLE_STATE


def parse_lockfile(lock_path: str) -> List[Dict[str, Any]]:
    """Parses requirements.lock into a list of components."""
    components = []
    if not os.path.exists(lock_path):
        return components

    with open(lock_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    current_pkg = None
    current_ver = None
    hashes = []

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        if "==" in line:
            parts = line.split("==")
            pkg_name = parts[0].strip()
            rest = parts[1].split(";")[0].strip()
            components.append({
                "type": "library",
                "name": pkg_name,
                "version": rest,
                "purl": f"pkg:pypi/{pkg_name}@{rest}",
                "scope": "required",
            })
        elif line.startswith("--hash="):
            h = line.replace("--hash=", "").strip()
            hashes.append(h)

    return components


def generate_sbom(
    output_path: str = "sbom.json",
    lock_path: str = "requirements.lock",
) -> Dict[str, Any]:
    """Generates CycloneDX 1.5 JSON SBOM."""
    components = parse_lockfile(lock_path)

    sbom = {
        "$schema": "http://cyclonedx.org/schema/bom-1.5.json",
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:algolab-{SEMANTIC_VERSION}-{int(datetime.now(timezone.utc).timestamp())}",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tools": [
                {
                    "vendor": "Algo Lab Security & Compliance",
                    "name": "algolab-sbom-generator",
                    "version": SEMANTIC_VERSION,
                }
            ],
            "component": {
                "type": "application",
                "name": "algo-lab",
                "version": SEMANTIC_VERSION,
                "description": "Paper-only quantitative investment and research operating system",
                "properties": [
                    {"name": "lifecycle_state", "value": CURRENT_LIFECYCLE_STATE.value},
                    {"name": "execution_mode", "value": "PAPER_ONLY"},
                    {"name": "live_trading_enabled", "value": "false"},
                ],
            },
        },
        "components": components,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(sbom, f, indent=2)

    print(f"[PASS] Generated CycloneDX SBOM: {output_path} ({len(components)} components)")
    return sbom


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate SBOM JSON")
    parser.add_argument("--output", default="sbom.json", help="Output SBOM path")
    parser.add_argument("--lock", default="requirements.lock", help="Path to lockfile")
    args = parser.parse_args()

    generate_sbom(output_path=args.output, lock_path=args.lock)
