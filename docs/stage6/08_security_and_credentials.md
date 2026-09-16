# Algo Lab Stage 6 — Security, Credentials & Secret Management

## 1. Overview
Stage 6 enforces strict operational security for broker API credentials and maintains a fail-closed lockout against unauthorized live trading.

---

## 2. Secret Masking Invariant

Broker credentials (API keys, secrets, access tokens) are subject to automated redaction:

1. **Masking Algorithm (`mask_secret`)**:
   - Empty/None ──▶ `""`
   - Length $\le 6$ ──▶ `******`
   - Length $> 6$ ──▶ First 2 chars + `****` + Last 4 chars (e.g., `ak****8877`).

2. **Safe Serialization (`to_safe_dict`)**:
   - The plain text `api_key` and `api_secret` are never returned in JSON payloads.
   - Replaced by `api_key_masked`, `api_key_configured: bool`, and `api_secret_configured: bool`.
   - Any sensitive dictionary keys (containing "key", "secret", "token", "password") in `extra_params` are masked recursively.

3. **String Representations**:
   - `BrokerConnectionConfig.__repr__` and `__str__` mask all credentials.
   - Raw credentials are never dumped to stdout, application logs, or audit events.

---

## 3. Fail-Closed Live Trading Lockout

To protect users against accidental capital deployment:
- `LIVE_TRADING_ENABLED: bool = False` is permanently hardcoded.
- `REAL_BROKER_EXECUTION_ENABLED: bool = False` is permanently hardcoded.
- Any API call or adapter configuration requesting `ExecutionEnvironment.LIVE` is rejected fail-closed with an HTTP 403 Forbidden error and raises a `PermissionError`.
