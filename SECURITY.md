# Security Policy

## Reporting Security Vulnerabilities

Algo Lab takes security, algorithmic integrity, and secret isolation seriously. If you discover a security vulnerability or invariant breach, please report it privately.

**DO NOT create a public GitHub issue.**

### Contact
Please send vulnerability reports to:
- **Email**: `security@algolab.local` (or reach out to the project maintainers directly via private repository channels).
- Include the following details in your report:
  - Description of the vulnerability and its potential impact.
  - Minimal reproducible example or proof-of-concept steps.
  - Affected components, files, and commit hashes.
  - Mitigation suggestions, if known.

We will acknowledge receipt within 24 hours and provide an estimated remediation timeline.

---

## Core Security Invariants

Algo Lab is subject to strict architectural invariants:

1. **Paper-Only Execution**: The platform is strictly designed for quantitative research and forward paper simulation. Any code path that attempts to place live market orders with real broker capital is considered a critical security vulnerability.
2. **Independent Risk Sovereignty**: The risk engine must evaluate state authoritatively. Strategies, AI reasoning components, and UI endpoints must never possess execution authority without prior risk clearance.
3. **Cryptographic Protection of Secrets**: API keys must be hashed (SHA-256) at rest. Fernet encryption must protect broker credential stores. Constant-time comparisons (`hmac.compare_digest`) must be used for token authentication.
4. **No Secret Ingestion into Logs**: Sensitive environment variables, authorization headers, and broker passwords must be redacted from application logs and telemetry.
5. **No Synthetic Data Fallback**: The platform must fail closed or emit `WAIT` when data is missing or corrupted. Synthetic bar extrapolation in production paths is strictly prohibited.

---

## Supported Versions

| Version | Supported | Status |
| :--- | :---: | :--- |
| `0.2.x` | Yes | Active Forward Paper Validation |
| `< 0.2.0` | No | Prototype (Deprecated) |

---

## Security Scans in CI

Every pull request and build on `main` runs automated security gates:
- Static Application Security Testing (SAST) with `bandit`.
- Secret scanning with canary pattern detection.
- Dependency vulnerability analysis against pinned hashes.
- Fail-closed evaluation of live-trading flags (`LIVE_TRADING_ENABLED=False`).
