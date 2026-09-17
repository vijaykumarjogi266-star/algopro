# Algo Lab — Stage 8 Specification & Implementation Plan

**Project:** Algo Lab  
**Stage:** 8 — Market Intelligence, Institutional Flows & Sector Rotation Engine  
**STATUS:** DRAFT — SPECIFICATION CORRECTED / NOT APPROVED  
**IMPLEMENTATION:** NOT STARTED / NOT APPROVED  
**BASELINE:** Tag `stage7-verified` | Commit `0903e530e2b27822c183421315506086024d3fe8`  
**BASELINE CERTIFICATION:** 216/216 tests passing ($100\%$ pass rate)  
**CODE CHANGES:** NONE (Specification Corrections Only)  

---

## 1. Executive Summary & Philosophy

Stage 8 introduces the **Market Intelligence, Institutional Flows & Sector Rotation Engine** atop the certified Stage 7 research evaluation baseline (`0903e53`).

Stage 8 extends Stage 7 single-asset walk-forward evaluation by integrating point-in-time macro intelligence:
1. **Point-in-Time Market Breadth Analysis:** Advance-Decline ratios, McClellan Oscillator metrics, and % stocks trading above 20/50/200 SMAs.
2. **Point-in-Time Institutional Flow Tracking:** FII (Foreign Institutional Investors) and DII (Domestic Institutional Investors) daily net cash and derivative turnover series with strict publication timestamp controls.
3. **Point-in-Time Sector Rotation:** Sector constituent membership, relative strength scoring, and momentum ranking strictly using constituent lists active on historical evaluation date $t$.

Stage 8 operates strictly under a **Fail-Closed Research Firewall**:
- **Zero Live Execution Pathways:** Zero live broker SDK imports, zero execution adapters, and zero order routing handles (verified via static AST inspection).
- **Point-in-Time Revision Isolation (INV-26):** Later-revised data published at $T_{\text{pub}} > t_{\text{sim}}$ is invisible to simulation clock $t_{\text{sim}}$.
- **Point-in-Time Sector Constituent Integrity (INV-27):** Eliminates survivorship bias by enforcing historical index constituent membership as it existed on date $t$.

---

## 2. Problem Statement

Evaluating quantitative strategies solely on single-stock histories introduces severe structural flaws:
1. **Point-in-Time Data Revision Leakage:** Exchanges frequently revise end-of-day FII/DII flow figures 1–3 days post-event. Standard backtests using revised dataset files inadvertently leak future information into earlier simulation decisions.
2. **Survivorship Bias in Sector Rotation:** Calculating historical sector relative strength using modern 2026 index constituents includes stocks that were added years later and excludes unlisted or delisted historical constituents.
3. **Macro Regime Blindness:** Trend-following strategies suffer drawdowns during institutional distribution phases (net FII selling) even when individual stock charts appear bullish.
4. **Execution Boundary Leakage:** Research modules risk introducing indirect imports of broker execution code or socket handlers if boundaries are not verified statically.

Stage 8 solves these gaps by introducing point-in-time data revision tracking, point-in-time sector membership versioning, and static AST execution isolation.

---

## 3. Explicit Objectives

1. **Point-in-Time Data Revision Control (INV-26):** Track $T_{\text{event}}$ (event date), $T_{\text{pub}}$ (publication timestamp), $T_{\text{ret}}$ (retrieval timestamp), and `revision_sequence_id`. Evaluation at simulation clock $t_{\text{sim}}$ accesses strictly observations where $T_{\text{pub}} \le t_{\text{sim}}$.
2. **Point-in-Time Sector Constituent Engine (INV-27):** Maintain versioned historical index membership records for all sector indices. Relative strength calculations at date $t$ use strictly constituent stocks active on date $t$.
3. **Institutional Flow Analysis:** Index FII/DII cash and derivative segment flows (Index Futures, Index Options, Stock Futures) with explicit publication guards.
4. **Market Breadth Engine:** Calculate Advance-Decline line, A/D ratio, and % Stocks Above SMA ($20, 50, 200$) across universe close prices $\le t_{\text{sim}}$.
5. **Static AST Execution Isolation (AT-109 / AT-135):** Statically parse AST of all modules in `services/market_intelligence/` to verify zero prohibited imports of broker adapters, live SDKs, or order routing gateways.

---

## 4. Explicit Non-Goals

Stage 8 explicitly excludes:
- **Live Trading & Order Execution:** Zero live order placement, zero production broker session handles.
- **Dynamic Web Scraping During Evaluation:** No unverified web scraping or external network requests during simulation runs.
- **Autonomous Strategy Promotion:** Market intelligence signals cannot autonomously deploy strategies or override risk gates.
- **Modification of Baseline Controls:** Stage 6 replay determinism, pre-trade cash solvency, Stage 7 walk-forward engines, and baseline test suites (216 tests) remain untouched.

---

## 5. Relationship to Certified Baseline (Stage 6 & Stage 7)

Stage 8 builds on top of:
- **Stage 6 Baseline (`2c09e57`):** Reuses `CanonicalMarketDataBar`, `IndianCostCalculator`, `SlippageCalculator`, and solvency checks.
- **Stage 7 Baseline (`0903e53`):** Reuses `ExperimentManifest`, `WalkForwardEngine`, `PerformanceAnalytics`, `SensitivityEngine`, `AuditManifest`, and AT-79.

---

## 6. Point-in-Time Data Revision Control Specification (INV-26)

Every market intelligence record adheres to the **Point-in-Time Provenance Schema**:

```python
@dataclass(frozen=True)
class PointInTimeRecord:
    event_date: date                   # Date the economic event occurred (T_event)
    publication_timestamp: datetime    # Exact UTC timestamp data became public (T_pub)
    retrieval_timestamp: datetime      # UTC timestamp dataset was ingested (T_ret)
    dataset_version_id: str            # Version identifier of the dataset
    revision_sequence_id: int          # Revision sequence number (0 = initial, 1 = revised)
    payload: Dict[str, Any]            # Metric payload (e.g. FII net flow, A/D ratio)

    def is_eligible_at(self, simulation_time: datetime) -> bool:
        """Eligibility rule: Available strictly if T_pub <= t_sim."""
        return self.publication_timestamp <= simulation_time
```

### Revision Eligibility Rules
1. **Unrevised Observation:** Initial publication at $T_{\text{pub}}$ becomes visible to simulation clock when $t_{\text{sim}} \ge T_{\text{pub}}$.
2. **Revised Observation:** A revision published at $T_{\text{pub, rev}} > T_{\text{pub}}$ is invisible to simulation clock $t_{\text{sim}} < T_{\text{pub, rev}}$. At $t_{\text{sim}} < T_{\text{pub, rev}}$, the simulation engine consumes the earlier unrevised observation.
3. **Missing Publication Timestamp:** If $T_{\text{pub}}$ cannot be established reliably, the record is flagged invalid and fails closed immediately.
4. **Conflicting Versions:** If two datasets report conflicting values for the same $(T_{\text{event}}, T_{\text{pub}})$, evaluation halts with `SourceConflictError`.

---

## 7. Point-in-Time Sector Constituent Specification (INV-27)

Sector relative strength and breadth computations require versioned historical membership records:

```python
@dataclass(frozen=True)
class SectorMembershipRecord:
    sector_id: str                      # e.g., "NIFTY_BANK"
    effective_date: date                # Date constituent change took effect
    added_symbols: List[str]            # Symbols added on effective_date
    removed_symbols: List[str]          # Symbols removed on effective_date
    active_constituents: List[str]      # Complete active list as of effective_date
```

### Constituent Integrity Rules
1. **Historical Membership Selection:** For simulation date $t$, the constituent list is resolved strictly as `active_constituents` of the latest record where `effective_date <= t`.
2. **Delisted Constituents:** Delisted or merged stocks remain included in historical sector indices up to their official delisting date.
3. **Survivorship Bias Prevention:** Retroactive application of current (2026) sector members to historical dates is strictly prohibited.
4. **Missing Membership Data:** If historical membership for date $t$ cannot be established, sector relative strength calculation fails closed with `MissingMembershipError`.

---

## 8. Proposed Architecture & Component Boundaries

Stage 8 introduces package `services/market_intelligence/` with symlink `services/evaluation_engine`:

```
services/market_intelligence/
├── __init__.py
├── contracts.py           # Dataclasses & Schemas (PointInTimeRecord, SectorMembershipRecord)
├── breadth.py             # Advance-Decline & Universe Breadth Calculator
├── institutional_flows.py # FII/DII Net Flow Processor & Point-in-Time Guard
├── sector_rotation.py     # Sector Index Relative Strength & Constituent Versioning
└── service.py             # Integrated Market Intelligence Provider Interface
```

---

## 9. Determinism Requirements

1. **Bit-for-Bit Reproducibility:** Given identical market data, institutional flow dataset, and sector membership records, `MarketIntelligenceEngine` produces identical outputs across all runs.
2. **Canonical Tie-Breaking:** Sector relative strength ties sort by symbol alphabetical order.

---

## 10. Execution Isolation & Static AST Scanner (AT-109 / AT-135)

Stage 8 modules MUST NOT import live execution classes, broker SDKs, or socket modules:
- Prohibited: `services.paper_engine.adapters`, `kiteconnect`, `upstox_client`, `smartapi`, `services.execution_engine`, `socket`, `websockets`.
- Static AST inspection test **AT-109 / AT-135** inspects all `.py` files in `services/market_intelligence/`.

---

## 11. Security & Secret Protection

- Institutional flow datasets and breadth manifests contain zero API keys or secrets.
- All JSON and Markdown exports pass `PROHIBITED_SECRET_PATTERNS` regex scanning.

---

## 12. Audit & Provenance Requirements

Stage 7 audit manifests generated for Stage 8 runs include:
- `institutional_flow_dataset_sha256`: SHA-256 hash of flow dataset.
- `sector_membership_dataset_sha256`: SHA-256 hash of sector constituent history file.
- `point_in_time_provenance_summary`: Record count of initial vs revised observations consumed.

---

## 13. API / UI Implications

- Endpoint: `GET /api/v1/intelligence/breadth` (Read-only historical breadth).
- Endpoint: `GET /api/v1/intelligence/flows` (Read-only FII/DII flow series).
- Endpoint: `GET /api/v1/intelligence/sectors` (Read-only sector relative strength).

---

## 14. Failure & Fail-Closed Behavior

- SHA-256 mismatch $\rightarrow$ Raise `DatasetIntegrityError` and abort.
- Missing $T_{\text{pub}}$ $\rightarrow$ Raise `MissingTimestampError` and abort.
- Unestablished sector membership $\rightarrow$ Raise `MissingMembershipError` and abort.
- `ExecutionEnvironment.LIVE` request $\rightarrow$ Raise `PermissionError` immediately.

---

## 15. Dependency Policy

- Zero new external third-party package dependencies.
- Standard Python stdlib (`dataclasses`, `datetime`, `json`, `hashlib`, `ast`) + Stage 6/7 core.

---

## 16. Preservation of Baseline Stage 6 & Stage 7 Controls

The following certified controls MUST remain 100% untouched:
1. Stage 6 canonical market data schema, dataset integrity, and deterministic replay.
2. Stage 6 paper trading engine, cash solvency checks (`cash - proposed_cost >= 0`), and broker abstraction.
3. Stage 7 temporal partitioning, walk-forward engines, friction models, and OOS degradation analysis.
4. Stage 7 AT-79 AST structural scanner and fail-closed live execution lockout.
5. All 216 baseline tests must continue passing ($100\%$ pass rate).

---

## 17. Complete Acceptance-Test Matrix (AT-101 to AT-135)

### Initial Acceptance Tests (AT-101 to AT-120)

| AT-ID | Requirement Title | Precondition | Input | Expected Result | Pass/Fail Condition | Related Invariant |
|---|---|---|---|---|---|---|
| **AT-101** | Valid Breadth Calculation | Universe OHLCV series | Universe price slice | Accurate Advance/Decline ratio | Ratio matches exact count ratio | INV-19 |
| **AT-102** | % Above SMA Calculation | Universe OHLCV series | 50 SMA threshold | Accurate % of stocks above 50 SMA | Return value in $[0.0, 1.0]$ | INV-19 |
| **AT-103** | FII/DII Record Ingestion | Valid flow JSON series | Load dataset | Record list populated cleanly | Rejects valid JSON payload | INV-20 |
| **AT-104** | Flow SHA-256 Validation | Registered flow file | Compute hash | Hash matches manifest | Rejects matching hash | INV-23 |
| **AT-105** | Flow Checksum Drift Rejection | Modified flow file | Load dataset | Raises `DatasetIntegrityError` | Loads corrupted file | INV-23 |
| **AT-106** | Flow Publication Guard (Pre-18:00) | Day $T$ flow record | Query at $T$ 10:00 IST | Returns $T-1$ flow or hides $T$ | Returns Day $T$ summary before 18:00 | INV-20 |
| **AT-107** | Post-Publication Access | Day $T$ flow record | Query at $T+1$ 09:15 IST | Returns Day $T$ flow summary | Fails to return Day $T$ summary | INV-20 |
| **AT-108** | Future Flow Access Lockout | Day $T$ simulation | Query Day $T+2$ flows | Raises `LookAheadBiasError` | Returns future flow record | INV-20 |
| **AT-109** | **Structural AST Isolation Scanner** | Market intelligence module | AST module parse | Zero prohibited imports found | Prohibited import detected | INV-22 |
| **AT-110** | Live Environment Lockout | Intelligence manifest | Environment = LIVE | Raises `PermissionError` | Accepts LIVE environment | INV-22 |
| **AT-111** | Sector Relative Strength Rank | Sector index OHLCV | Index price series | Sectors ranked by RS score descending | Incorrect rank order | INV-21 |
| **AT-112** | Deterministic RS Sorting | Equal RS scores | Tied sector scores | Alphabetical symbol tie-breaker | Non-deterministic sort order | INV-19 |
| **AT-113** | Intelligence Filter Integration | Manifest + Signals | Run evaluation | Signals filtered by flow/breadth | Intelligence filter ignored | INV-24 |
| **AT-114** | Hard Risk Limit Precedence | Bullish flow + High Drawdown | Trade signal | Risk engine rejects trade | Risk engine bypassed | INV-24 |
| **AT-115** | Flow Dataset SHA-256 Audit | Completed run | Inspect manifest | Flow dataset hash persisted | Missing flow dataset hash | INV-25 |
| **AT-116** | Sector Universe ID Audit | Completed run | Inspect manifest | Sector universe ID persisted | Missing sector universe ID | INV-25 |
| **AT-117** | Secret Protection in Flow Audit | Manifest JSON | Export `to_json()` | Zero credentials in output | Credential leaked in JSON | INV-25 |
| **AT-118** | Stage 6 Regression Gate | Stage 6 test suite | Run `pytest` | 192 Stage 6 tests PASS | Baseline test failure | INV-14 |
| **AT-119** | Stage 7 Regression Gate | Stage 7 test suite | Run `pytest` | 24 Stage 7 tests PASS | Acceptance test failure | INV-14 |
| **AT-120** | Full Suite Pass Gate | Combined test suite | Run `pytest` | All 246+ tests PASS ($100\%$) | Pass rate $< 100\%$ | INV-14 |

---

### Detailed Specification of Additional Acceptance Tests (AT-121 to AT-135)

#### AT-121 — Point-in-Time Historical Revision Isolation
- **Requirement:** A historical data revision published at $T_{\text{pub, rev}} > t_{\text{sim}}$ must be invisible to simulation clock at $t_{\text{sim}}$.
- **Preconditions:** Dataset contains initial flow record (published June 10 18:00) and revised flow record (published June 13 18:00).
- **Input:** Query net flow for date June 10 at simulation time $t_{\text{sim}} = \text{June 11 09:15:00}$.
- **Expected Result:** Returns the unrevised initial observation published on June 10.
- **Pass/Fail Condition:** Pass if initial record is returned; Fail if revised June 13 observation is returned.
- **Failure Case:** Returning June 13 revision at $t_{\text{sim}} = \text{June 11}$.
- **Evidence Produced:** Assertion verifying `record.revision_sequence_id == 0`.
- **Related Invariant:** INV-26.

#### AT-122 — Point-in-Time Sector Constituent Membership
- **Requirement:** Sector relative strength at historical date $t$ must use the exact constituent stock list active on date $t$.
- **Preconditions:** Sector membership history shows Stock A was added to Nifty Bank on 2022-03-31, replacing Stock B.
- **Input:** Calculate Nifty Bank relative strength at simulation date $t = \text{2021-12-15}$.
- **Expected Result:** Calculation includes Stock B and excludes Stock A.
- **Pass/Fail Condition:** Pass if constituent list matches 2021-12-15 active list; Fail if 2026 constituent list is used.
- **Failure Case:** Including Stock A in 2021 calculation.
- **Evidence Produced:** Assertion verifying `active_constituents` list matching historical effective date.
- **Related Invariant:** INV-27.

#### AT-123 — Revision Cannot Leak Future Information
- **Requirement:** Attempting to query a revised observation before its publication timestamp $T_{\text{pub, rev}}$ raises error or returns unrevised record.
- **Preconditions:** Revision published at $T_{\text{pub, rev}} = \text{2024-06-13 18:00:00}$.
- **Input:** Request latest observation for June 10 at $t_{\text{sim}} = \text{2024-06-12 12:00:00}$.
- **Expected Result:** Returns unrevised record published on June 10.
- **Pass/Fail Condition:** Pass if unrevised record returned; Fail if revision returned.
- **Failure Case:** Revision leaked to simulation clock before June 13 18:00:00.
- **Evidence Produced:** Assertion verifying timestamp constraints.
- **Related Invariant:** INV-26.

#### AT-124 — Missing T_pub Fail-Closed Behavior
- **Requirement:** Loading a PointInTimeRecord with missing or unparseable `publication_timestamp` fails closed immediately.
- **Preconditions:** Point-in-time flow JSON contains record with `publication_timestamp: null`.
- **Input:** Instantiate `InstitutionalFlowProcessor` with missing timestamp record.
- **Expected Result:** Raises `MissingTimestampError`.
- **Pass/Fail Condition:** Pass if exception raised; Fail if invalid record loaded.
- **Failure Case:** Accepting null publication timestamp.
- **Evidence Produced:** Exception type and message check.
- **Related Invariant:** INV-20, INV-26.

#### AT-125 — Conflicting Dataset/Version Handling
- **Requirement:** Loading two datasets with conflicting values for identical $(T_{\text{event}}, T_{\text{pub}})$ fails closed.
- **Preconditions:** Dataset A reports FII net flow +500 Cr; Dataset B reports -200 Cr for same timestamp.
- **Input:** Pass conflicting datasets to market intelligence provider constructor.
- **Expected Result:** Raises `SourceConflictError`.
- **Pass/Fail Condition:** Pass if `SourceConflictError` raised; Fail if one dataset silently overwrites the other.
- **Failure Case:** Silent conflict resolution.
- **Evidence Produced:** Assertion checking `SourceConflictError`.
- **Related Invariant:** INV-23.

#### AT-126 — Sector EOD Publication Guard (15:30 IST)
- **Requirement:** Sector index close prices for trading date $T$ are invisible to simulation clock $t < T \text{ 15:30:00 IST}$.
- **Preconditions:** Sector index EOD price file registered.
- **Input:** Query sector close price for date $T$ at simulation clock $t = T \text{ 14:00:00 IST}$.
- **Expected Result:** Raises `LookAheadBiasError` or returns Day $T-1$ close.
- **Pass/Fail Condition:** Pass if Day $T$ close is inaccessible at 14:00 IST; Fail if Day $T$ close returned intraday.
- **Failure Case:** Returning Day $T$ close price at 14:00 IST.
- **Evidence Produced:** Assertion verifying `LookAheadBiasError`.
- **Related Invariant:** INV-20, INV-26.

#### AT-127 — Survivorship-Bias Protection for Delisted Constituents
- **Requirement:** Delisted stocks remain included in historical sector breadth metrics up to their official delisting date.
- **Preconditions:** Stock XYZ was delisted on 2023-06-30.
- **Input:** Compute sector breadth for date 2022-06-30.
- **Expected Result:** Stock XYZ is included in Advance-Decline calculation for 2022-06-30.
- **Pass/Fail Condition:** Pass if XYZ included in 2022 calculation; Fail if XYZ omitted due to current unlisted status.
- **Failure Case:** Omitting historical delisted stock XYZ.
- **Evidence Produced:** Assertion checking XYZ presence in 2022 constituent list.
- **Related Invariant:** INV-27.

#### AT-128 — Delisted Constituent Post-Delisting Removal
- **Requirement:** Delisted stocks are excluded from sector relative strength calculations for dates after their delisting date.
- **Preconditions:** Stock XYZ delisted on 2023-06-30.
- **Input:** Compute sector breadth for date 2023-12-31.
- **Expected Result:** Stock XYZ is excluded from 2023-12-31 constituent list.
- **Pass/Fail Condition:** Pass if XYZ excluded on 2023-12-31; Fail if XYZ included post-delisting.
- **Failure Case:** Including delisted stock after delisting date.
- **Evidence Produced:** Assertion verifying XYZ absence post-delisting.
- **Related Invariant:** INV-27.

#### AT-129 — Sector Reclassification Handling
- **Requirement:** A stock reclassified from Sector A to Sector B update takes effect strictly on its official effective date.
- **Preconditions:** Stock ABC reclassified from Nifty IT to Nifty Financials on 2023-01-01.
- **Input:** Compute relative strength for Nifty IT on 2022-12-15 and 2023-01-15.
- **Expected Result:** Stock ABC included in Nifty IT on 2022-12-15; excluded on 2023-01-15.
- **Pass/Fail Condition:** Pass if transition respects effective date; Fail if transition applies retroactively.
- **Failure Case:** Misapplying reclassification date.
- **Evidence Produced:** Assertion verifying constituent list transition.
- **Related Invariant:** INV-27.

#### AT-130 — Deterministic Intelligence Output
- **Requirement:** Running `MarketIntelligenceEngine` twice on identical flow/breadth inputs produces bit-for-bit identical output records.
- **Preconditions:** Flow dataset + sector index dataset loaded.
- **Input:** Execute intelligence calculations twice.
- **Expected Result:** Output records match bit-for-bit.
- **Pass/Fail Condition:** Pass if output records are identical; Fail if metrics diverge.
- **Failure Case:** Metric divergence between identical runs.
- **Evidence Produced:** Assertion checking output equality.
- **Related Invariant:** INV-19.

#### AT-131 — Complete Audit Trail Provenance
- **Requirement:** Generated audit manifest contains SHA-256 hashes of flow dataset, sector membership file, and point-in-time provenance summary.
- **Preconditions:** Stage 8 evaluation run completed.
- **Input:** Inspect `AuditManifest`.
- **Expected Result:** Manifest contains `institutional_flow_dataset_sha256` and `sector_membership_dataset_sha256`.
- **Pass/Fail Condition:** Pass if hashes present; Fail if provenance metadata missing.
- **Failure Case:** Missing flow or membership hash in audit manifest.
- **Evidence Produced:** JSON dictionary key verification.
- **Related Invariant:** INV-25.

#### AT-132 — Stale Source Warning Flag
- **Requirement:** If institutional flow statistics remain un-updated for $>3$ consecutive trading days, flag `STALE_MACRO_DATA` warning in audit manifest.
- **Preconditions:** Flow dataset contains 5-day gap during active trading days.
- **Input:** Run evaluation across flow gap.
- **Expected Result:** Manifest diagnostics list includes `STALE_MACRO_DATA` warning.
- **Pass/Fail Condition:** Pass if warning present; Fail if stale data ignored silently.
- **Failure Case:** Missing warning for stale macro data.
- **Evidence Produced:** Assertion checking diagnostic warnings list.
- **Related Invariant:** INV-23.

#### AT-133 — Malformed Payload Fail-Closed Gate
- **Requirement:** Ingesting malformed flow JSON containing negative trading volumes or unparseable fields fails closed immediately.
- **Preconditions:** Flow JSON contains `fii_buy_volume: -5000`.
- **Input:** Load malformed flow dataset.
- **Expected Result:** Raises `ValidationError`.
- **Pass/Fail Condition:** Pass if `ValidationError` raised; Fail if malformed payload accepted.
- **Failure Case:** Ingesting negative volume.
- **Evidence Produced:** Exception assertion.
- **Related Invariant:** INV-23.

#### AT-134 — Stage 8 Execution Isolation (AST)
- **Requirement:** Static AST parser verifies zero imports of `kiteconnect`, `upstox_client`, `smartapi`, `services.paper_engine.adapters`, or socket modules in `services/market_intelligence/`.
- **Preconditions:** All `.py` files in `services/market_intelligence/` parsed into AST.
- **Input:** Walk AST nodes for `Import` and `ImportFrom`.
- **Expected Result:** Zero prohibited import pattern matches.
- **Pass/Fail Condition:** Pass if 0 prohibited imports found; Fail if prohibited import detected.
- **Failure Case:** Detecting prohibited import in AST scan.
- **Evidence Produced:** AST walker assertion pass.
- **Related Invariant:** INV-22.

#### AT-135 — AI Authority Boundary Enforcement
- **Requirement:** AI report generator class cannot inject or modify intelligence filtering parameters in `ExperimentManifest`.
- **Preconditions:** Manifest instantiated with fixed market intelligence parameters.
- **Input:** Pass manifest to AI summary generator method.
- **Expected Result:** Manifest parameters remain unchanged.
- **Pass/Fail Condition:** Pass if manifest fingerprint is identical before and after summary generation; Fail if manifest mutated.
- **Failure Case:** Manifest parameter mutation by summary generator.
- **Evidence Produced:** Assertion checking `compute_fingerprint()` equality.
- **Related Invariant:** INV-24, INV-25.

---

## 18. Complete Architectural Invariants Matrix (INV-19 to INV-27)

| Invariant ID | Invariant Name | Architectural Definition | Enforcement Mechanism | Verification Test |
|---|---|---|---|---|
| **INV-19** | **Deterministic Breadth Score** | Same universe + same price series = bit-for-bit identical breadth scores. | Pure math + alphabetical tie-breaker | AT-101, AT-112, AT-130 |
| **INV-20** | **Publication Timestamp Guard** | Day $T$ flow/index statistics unavailable before $T_{\text{pub}}$. | Simulation clock comparison ($T_{\text{pub}} \le t_{\text{sim}}$) | AT-106, AT-108, AT-126 |
| **INV-21** | **Sector Relative Strength Monotonicity** | Sectors ranked strictly by relative score descending with symbol tie-breaker. | Sorted float comparison + fallback | AT-111, AT-112 |
| **INV-22** | **Zero Live Execution Access** | Market intelligence package has 0 broker imports and fails closed on LIVE environment. | Static AST parser + `PermissionError` | AT-109, AT-110, AT-134 |
| **INV-23** | **Fail-Closed Macro Data Integrity** | Corrupted or missing flow datasets fail closed immediately. | SHA-256 manifest hash check | AT-104, AT-105, AT-125, AT-132, AT-133 |
| **INV-24** | **Risk Engine Precedence** | Hard portfolio risk limits override market intelligence signals under all conditions. | Independent risk gate check | AT-114, AT-135 |
| **INV-25** | **Immutable Intelligence Audit Hash** | Flow dataset SHA-256 hash and sector universe identity persisted in audit trails. | Audit manifest metadata serialization | AT-115, AT-116, AT-117, AT-131 |
| **INV-26** | **Point-in-Time Revision Isolation** | Simulation clock at $t_{\text{sim}}$ accesses strictly data observations published $\le t_{\text{sim}}$. | Point-in-time record filter | AT-121, AT-123, AT-124 |
| **INV-27** | **Point-in-Time Constituent Integrity** | Sector calculations at date $t$ use strictly the constituent list active on date $t$. | Versioned historical membership lookup | AT-122, AT-127, AT-128, AT-129 |

---

## 19. Document Consistency Audit Findings

1. **Point-in-Time Revisions:** Resolved via INV-26 and AT-121/AT-123/AT-124.
2. **Point-in-Time Sector Membership:** Resolved via INV-27 and AT-122/AT-127/AT-128/AT-129.
3. **Execution Isolation:** Reinforced via AT-109 / AT-134 AST scanner.
4. **Acceptance Test Matrix:** Expanded from 20 to 35 tests (AT-101 to AT-135), each with explicit preconditions, inputs, expected results, pass/fail conditions, and related invariants.
5. **Stage 6 & Stage 7 Controls:** 100% preserved.

---

## STAGE 8 SPECIFICATION CORRECTIONS COMPLETE

```
===============================================================================
                    STAGE 8 SPECIFICATION CORRECTIONS COMPLETE
===============================================================================
Baseline Commit:    0903e530e2b27822c183421315506086024d3fe8 (stage7-verified)
Baseline Test Suite:  216/216 PASSED (100%)
Specification:      UPDATED & CORRECTED (algo_lab_stage8_specification.md)
Production Code:    UNTOUCHED (0 code changes)
Working Tree:       CLEAN (except untracked updated spec)

VERDICT: SPECIFICATION COMPLETE & CONSISTENT

IMPLEMENTATION APPROVAL: NOT GRANTED
===============================================================================
```
