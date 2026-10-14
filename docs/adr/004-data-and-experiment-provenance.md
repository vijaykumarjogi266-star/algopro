# ADR-004: Data and Experiment Provenance Standard

## Context
Quantitative research integrity mandates point-in-time safety, zero lookahead bias, and deterministic replayability. Market datasets must be versioned and manifest-driven, with no synthetic bar substitution in forward paper validation.

## Decision
1. Implement `DatasetManifest` with SHA-256 checksums, quality metrics, and license classification in `services/market-data/manifest.py`.
2. Define five formal lineage stages: `RAW -> VALIDATED -> ADJUSTED -> FEATURE -> EXPERIMENT_INPUT`.
3. Capture immutable `ExperimentManifest` schemas linking strategy code source hashes, parameter locks, dataset manifest IDs, and output tearsheet checksums.
4. Replace hardcoded holiday arrays with a versioned `CalendarProvider` (`services/market-data/calendar_provider.py`).

## Status
Accepted

## Consequences
- Every backtest and forward paper experiment is 100% reproducible by replaying the exact strategy code and dataset snapshots.
- Guarantees zero synthetic data contamination in forward paper validation.
