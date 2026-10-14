# ADR-003: Release Gate Authority & Fail-Closed CI Policy

## Context
Documentation and release evidence claimed extensive security and container testing, while the legacy CI workflow ran a narrower subset of checks. To ensure institutional integrity, CI must strictly enforce all claimed release checks and fail closed.

## Decision
1. Establish `make release-check` and `scripts/verify_release.sh` as the authoritative canonical release gate.
2. Enforce a fail-closed policy:
   - Missing security tools or scanners must exit non-zero.
   - Skipped required tests fail the build.
   - Unlocked dependencies or lockfile mismatches fail immediately.
   - Code coverage below thresholds (<60% global, <90% safety modules) aborts the release.
3. Generate and archive CycloneDX 1.5 JSON SBOMs and coverage reports on every release build.

## Status
Accepted

## Consequences
- No pull request can merge without passing the complete canonical gate.
- Complete audit traceability for every deployed artifact.
