# Changelog

All notable changes to **Algo Lab** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.2.0] - 2026-10-14 - *Forward Paper Validation & Platform Hardening*

### Added
- **Canonical Project State**: Single source of truth in `apps.api.core.project_state` defining version `0.2.0`, lifecycle state `forward-paper-validation`, and permanent paper-only execution policy.
- **5-Tier Scoped RBAC**: Formalized role hierarchy (`viewer`, `researcher`, `operator`, `risk_admin`, `system_admin`) in `apps.api.core.auth`.
- **KeyStore Cryptography**: In-memory and persistent API key management with SHA-256 key hashing at rest, constant-time `hmac.compare_digest` verification, key rotation, and audit event recording.
- **API Runtime Protections**: Cryptographic nonce-based Content Security Policy (eliminating `unsafe-inline`), 2MB body limit, in-memory sliding window rate limiter, HSTS, and structured audit logs.
- **Typed Data Manifests & Lineage**: Implemented `DatasetManifest` schemas, dataset lineage transitions (`RAW -> VALIDATED -> ADJUSTED -> FEATURE -> EXPERIMENT_INPUT`), and versioned `CalendarProvider`.
- **Execution Simulator Contract**: Formalized fill lifecycle, statutory transaction costs (STT, SEBI turnover, GST, stamp duty), and AST architecture firewall tests.
- **Container Hardening & Encrypted Backups**: Non-root container configuration, drop-all capabilities, AES-256 automated database backup/restore scripts with HMAC integrity verification.
- **Canonical Release Gate**: Defined `make release-check` running locked dependency verification, SAST, secret scanning, tests, and SBOM generation.

### Changed
- Synchronized semantic version `0.2.0` across `pyproject.toml`, `apps/web/package.json`, and API responses.
- Replaced hardcoded single-year market holiday calendars with dynamic, versioned calendar provider.
- Restructured `README.md` into 12 canonical sections with comprehensive safety invariants.

### Security
- Locked `LIVE_TRADING_ENABLED=False` and `REAL_BROKER_EXECUTION_ENABLED=False` with fail-closed bootstrap verification.
- Enforced sovereign risk engine independence: direct order routing by strategies, AI agents, or UI actions is strictly prohibited.
- Banned synthetic data extrapolation in production and forward validation paths.

---

## [0.1.0] - 2026-10-12 - *Initial Research Prototype*

### Added
- Initial project layout for Algo Lab research operating system.
- Basic FastAPI service, Next.js web shell, and standalone backtest scripts.
- Double-entry paper trading ledger and circuit breaker prototype.
