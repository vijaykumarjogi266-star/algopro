# Contributing to Algo Lab

Thank you for your interest in contributing to **Algo Lab**. We maintain institutional standards for quantitative research integrity, code testability, and software security.

## Non-Negotiable Invariants

Before writing or submitting any code, review our core architectural invariants:

1. **`LIVE_TRADING_ENABLED` must remain `False` permanently.**
2. **`REAL_BROKER_EXECUTION_ENABLED` must remain `False` permanently.**
3. **The Risk Engine is sovereign.** It evaluates independently of all strategies, AI models, news/NLP pipelines, and user interface actions. No component may bypass risk checks.
4. **No synthetic data fallback.** Missing, stale, or malformed data in production/backtest runs must produce a `WAIT` decision or rejection.
5. **No secret leakage.** Never hardcode secrets, API keys, or private identifiers in code, tests, documentation, or commit messages.

Any PR violating these invariants will be closed immediately.

---

## Development Workflow

### 1. Branching Model
- Branch from `main`.
- Name your branch descriptively:
  - `feat/<topic>` (e.g., `feat/calendar-provider`)
  - `fix/<issue>` (e.g., `fix/slippage-calculation`)
  - `refactor/<module>` (e.g., `refactor/key-store`)
  - `docs/<subject>` (e.g., `docs/adr-lineage`)

### 2. Local Environment Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

### 3. Code Standards & Static Analysis
All submissions must pass static analysis and formatting:
```bash
# Run Python linter & type checks
flake8 apps/ services/ quant/ tests/
mypy apps/ services/ quant/

# Run security static scanning
bandit -r apps/ services/ quant/ -x tests/
```

### 4. Testing Requirements
- Every new feature, strategy, or fix must include automated tests in `tests/`.
- Ensure tests execute deterministically with offline fixtures. No external network calls are permitted in unit or contract tests.
- Run the test suite:
  ```bash
  pytest tests/ -v
  ```

### 5. Canonical Release Gate
Before opening a pull request, run the canonical verification command:
```bash
make release-check
```
All checks must pass. Skipped or suppressed security checks will fail in CI.

---

## Architecture Decision Records (ADRs)

If your contribution introduces an architectural change, new dependency, or breaking interface change:
1. Create an ADR in `docs/adr/` using the template at `docs/adr/ADR_TEMPLATE.md`.
2. Link the ADR in your pull request description.

---

## Submitting Pull Requests

1. Fill out the pull request template in full.
2. Confirm that all CI checks pass.
3. Ensure no uncommitted debug logs, scratch files, or credentials are included.
