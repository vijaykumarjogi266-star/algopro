## Pull Request Overview

### Summary of Changes
<!-- Provide a clear, concise summary of the changes proposed in this PR. -->

### Workstream / Issue Reference
<!-- Reference the associated workstream (A-G) or GitHub issue number. -->
- Workstream:
- Fixes/Relates to:

---

## Safety Invariants Verification

Please check all that apply to confirm compliance with platform invariants:

- [ ] **Paper-Only Guarantee**: `LIVE_TRADING_ENABLED` remains `False` and `REAL_BROKER_EXECUTION_ENABLED` remains `False`.
- [ ] **No Live Routing**: No code introduces real-broker execution, live market routing, or order transmission.
- [ ] **Risk Engine Sovereignty**: The risk engine remains completely independent of strategies, AI models, and UI endpoints.
- [ ] **No Synthetic Data Fallback**: Missing or invalid data paths fail closed or emit `WAIT`; no synthetic prices are generated.
- [ ] **Secret Redaction**: No API keys, passwords, or credentials are hardcoded or logged.
- [ ] **Offline Determinism**: All new tests execute deterministically with offline fixtures.

---

## Testing & Quality Evidence

- [ ] Unit tests added / updated in `tests/unit/`
- [ ] Integration or contract tests added / updated
- [ ] `make release-check` passes cleanly locally
- [ ] Test coverage meets or exceeds required thresholds

---

## Breaking Changes & Documentation

- [ ] Does this PR introduce any breaking API or schema changes?
  - If YES, an Architecture Decision Record (ADR) has been added to `docs/adr/`.
- [ ] `CHANGELOG.md` updated with relevant entries.
