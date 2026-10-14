# ADR-002: Canonical Versioning and Lifecycle Status

## Context
Previously, conflicting version and stage identifiers existed across files (`pyproject.toml` had `0.1.0`, root endpoint returned "Stage 1: Foundation", while docs described Stage 14 capabilities). This ambiguity impaired auditability and compliance.

## Decision
1. Establish `apps.api.core.project_state` as the canonical single source of truth for:
   - `SEMANTIC_VERSION = "0.2.0"`
   - `CURRENT_LIFECYCLE_STATE = LifecycleState.FORWARD_PAPER_VALIDATION`
2. Synchronize version across `pyproject.toml`, `apps/web/package.json`, and API responses (`/`, `/api/v1/system/info`).
3. Classify all historical "Stage 1–14" nomenclature into formal lifecycle states (`prototype`, `research`, `forward-paper-validation`, `release-candidate`).

## Status
Accepted

## Consequences
- Every API endpoint, frontend view, and documentation page reflects the identical product state.
- Establishes a disciplined Semantic Versioning policy for all subsequent releases.
