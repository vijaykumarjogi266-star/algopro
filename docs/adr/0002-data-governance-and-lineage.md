# ADR-0002: Typed Data Manifests and Explicit Lineage

## Context
Quantitative research and paper-trading simulations require point-in-time safety, complete reproducibility, and clear data provenance. Previously, data handling lacked formal lineage classification and allowed potential reliance on unverified or year-specific hardcoded calendar structures.

## Decision
1. Introduce typed `DatasetManifest` schemas containing dataset ID, version, provider, license classification, UTC/exchange timestamps, schema version, checksum (SHA-256), and quality metrics.
2. Formally define and enforce five dataset lineage stages:
   - `RAW`
   - `VALIDATED`
   - `ADJUSTED`
   - `FEATURE`
   - `EXPERIMENT_INPUT`
3. Prohibit synthetic data fallback in production and forward validation paths. Any missing or malformed market bar results in a `WAIT` decision or rejection.
4. Replace hardcoded holiday arrays with a versioned `CalendarProvider` providing point-in-time exchange schedules.

## Status
Accepted

## Consequences
- Every backtest and forward paper experiment is strictly bound to immutable dataset manifests.
- Prevents lookahead bias and silent data corruption.
- Eliminates hardcoded calendar obsolescence across years.
