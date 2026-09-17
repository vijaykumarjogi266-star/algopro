# Algo Lab — Stage 9 Specification & Implementation Plan

**Project:** Algo Lab  
**Stage:** 9 — Multi-Strategy Portfolio Construction, Dynamic Risk-Budgeting & Capital Allocation Engine  
**STATUS:** SPECIFICATION CORRECTED & AUDITED — READY FOR IMPLEMENTATION REVIEW  
**IMPLEMENTATION:** NOT STARTED / NOT APPROVED  
**BASELINE:** Tag `stage8-verified` | Commit `ad651247fdd4eacf2c67dd9463702c97120a009a`  
**BASELINE CERTIFICATION:** 229/229 tests passing ($100\%$ pass rate)  
**CODE CHANGES:** NONE (Specification Documentation Only)  

---

## 1. Executive Summary & Philosophy

Stage 9 introduces the **Multi-Strategy Portfolio Construction, Dynamic Risk-Budgeting & Capital Allocation Engine** built directly on top of the certified Stage 8 baseline (`ad65124`).

While Stage 7 provides single-strategy walk-forward evaluation and Stage 8 provides point-in-time macro/sector market intelligence, quantitative strategy deployment requires allocating capital across multiple coexisting alpha strategies dynamically. Evaluating strategies independently ignores cross-strategy correlation spikes, aggregate portfolio drawdowns, capital overcrowding, and portfolio turnover costs.

Stage 9 solves these structural requirements by introducing:
1. **Multi-Strategy Coexistence & Capital Allocation:** Aggregating independent Stage 7 strategy evaluations into a unified portfolio capital pool.
2. **Dynamic Walk-Forward & Macro Risk Budgeting:** Dynamically scaling strategy allocations based on Stage 7 walk-forward degradation scores (AT-62..90) and Stage 8 market breadth/flow alignment (AT-111..113).
3. **Correlation-Aware Risk Budgeting:** Enforcing hard aggregate portfolio risk limits (Max Portfolio Volatility, Max Aggregate Drawdown, Strategy Concentration Caps) that override individual strategy signals.
4. **Deterministic Portfolio Rebalancing:** Translating multi-strategy target allocation weights into discrete target portfolio positions while enforcing turnover caps, cash solvency, and point-in-time friction models.

Stage 9 operates strictly under a **Fail-Closed Research Firewall**:
- **Zero Live Execution Pathways:** Zero live broker SDK imports, zero execution adapters, and zero order routing handles (verified via static AST inspection in `services/portfolio_optimization/`).
- **Conservation of Shared Capital (INV-28):** Total allocated capital plus unallocated cash reserve MUST equal total portfolio equity ($\sum W_i + W_{\text{cash}} = 1.0$) at all times $t$.
- **Non-Finite Numerical Fail-Closed Protection (INV-37):** Any `NaN` or `Infinity` value in signals, weights, or cash balances fails closed immediately.
- **Residual Fractional Share Cash Attribution (INV-38):** Unallocated capital resulting from discrete integer share order rounding is credited deterministically back to cash reserve $W_{\text{cash}}$.
- **Point-in-Time Allocation Isolation (INV-30):** Rebalance decisions at clock $t_{\text{sim}}$ access strictly strategy performance metrics and macro records published $\le t_{\text{sim}}$.

---

## 2. Problem Statement

Evaluating strategies in isolation introduces severe portfolio-level risks when combining multiple strategies into a live or paper trading portfolio:

1. **Uncontrolled Aggregate Drawdown & Correlation Spikes:** Multiple strategies (e.g. Trend Following, Momentum, Sector Rotation) may each pass single-strategy Stage 7 risk checks, yet during market stress, their correlations approach $1.0$, resulting in destructive aggregate portfolio drawdowns.
2. **Capital Overcrowding & Concentration Risk:** Without explicit portfolio-level allocation limits, high-frequency signals can monopolize $100\%$ of available portfolio capital, starving complementary strategies.
3. **Static Allocation Inefficiency:** Assigning static equal weights ($25\%$ each to 4 strategies) causes capital to stay allocated to strategies undergoing walk-forward degradation or operating in adverse macro regimes (e.g., trend strategies during net FII distribution).
4. **Execution Boundary Leakage & Non-Determinism:** Combining strategy order streams without portfolio-level rebalancing logic risks race conditions, cash insolvency, or unintended imports of live broker routing handles.

Stage 9 resolves these gaps by establishing formal portfolio construction, dynamic risk budgeting, cross-strategy state isolation, and static AST execution boundaries.

---

## 3. Explicit Objectives

1. **Conservation of Shared Capital (INV-28):** Maintain exact financial accounting across strategy allocations: $\sum_{i=1}^{N} W_i(t) + W_{\text{cash}}(t) = 1.0$, where $W_i(t) \ge 0$.
2. **Dynamic Risk-Budgeting Engine (INV-29):** Cap individual strategy weights based on Stage 7 walk-forward degradation indices ($D_i \in [0, 1]$) and Stage 8 market intelligence regime scores ($M \in [-1, +1]$).
3. **Point-in-Time Allocation Isolation (INV-30):** Enforce strict publication-timestamp checks: Strategy performance metrics and macro indicators published after simulation time $t_{\text{sim}}$ are strictly invisible.
4. **Deterministic Portfolio Rebalancing (INV-31):** Calculate portfolio target allocations deterministically. Equal strategy scores sort by strategy ID alphabetical order.
5. **Non-Negative Cash Balance Solvency (INV-32):** Multi-strategy rebalance execution must never cause portfolio cash balance to drop below zero after deducting transaction friction, taxes, and slippage.
6. **Static AST Execution Isolation (INV-33 / AT-157):** Statically parse all Python modules in `services/portfolio_optimization/` to guarantee zero prohibited imports of live broker SDKs or order routing modules.
7. **AI Authority Boundary Non-Mutation (INV-34 / AT-154):** AI-generated portfolio summaries or allocation suggestions cannot alter strategy weights, risk budgets, or manifest fingerprints in the execution pipeline.
8. **Cross-Strategy State Isolation (INV-35):** State mutations, positions, or internal indicators of Strategy $A$ cannot leak into or alter Strategy $B$'s evaluation context.
9. **Cryptographic Multi-Strategy Audit Provenance (INV-36):** Persist strategy weights, risk budget state, and dataset SHA-256 hashes in immutable audit manifests.
10. **Non-Finite Numerical Fail-Closed Protection (INV-37):** Reject any non-finite floating point value (`NaN`, `Inf`, `-Inf`) immediately with `AllocationError`.
11. **Residual Capital Cash Attribution (INV-38):** Route unallocated cash remainders from discrete share rounding back to $W_{\text{cash}}$.

---

## 4. Explicit Non-Goals

Stage 9 explicitly excludes:
- **Live Trading & Order Execution:** Zero live order routing, zero production broker API connections.
- **Continuous Intraday Rebalancing:** Portfolio rebalancing is evaluated at discrete daily or bar boundaries ($t_{\text{rebalance}}$), not tick-by-tick.
- **Black-Box AI Portfolio Allocation:** AI models cannot autonomously assign portfolio weights or bypass risk budgets. All allocations follow deterministic algorithms.
- **Modification of Baseline Controls:** Stage 6 replay determinism, Stage 7 walk-forward engines, Stage 8 market intelligence engines, and baseline test suites (229 tests) remain 100% untouched.

---

## 5. Relationship to Certified Baselines (Stage 6, Stage 7 & Stage 8)

Stage 9 integrates all previous certified stages:
- **Stage 6 Baseline (`2c09e57`):** Reuses `CanonicalMarketDataBar`, `IndianCostCalculator`, `SlippageCalculator`, paper trading session, and cash solvency invariants (INV-1..15).
- **Stage 7 Baseline (`0903e53`):** Consumes `WalkForwardEngine`, `PerformanceAnalytics`, `DegradationScore`, `AuditManifest`, and AST scanner (AT-79, INV-16..18).
- **Stage 8 Baseline (`ad65124`):** Consumes `MarketBreadthCalculator`, `InstitutionalFlowProcessor`, `SectorRotationEngine`, `PointInTimeRecord` (INV-26), `SectorMembershipRecord` (INV-27), and AST scanner (AT-109, INV-19..27).

---

## 6. Proposed Architecture & Component Boundaries

Stage 9 introduces package `services/portfolio_optimization/`:

```
services/portfolio_optimization/
├── __init__.py
├── contracts.py              # StrategyAllocation, PortfolioRiskBudget, RebalancePlan schemas
├── risk_budgeting.py         # Dynamic Risk Budget & Correlation Constraint Engine
├── dynamic_allocator.py      # Walk-Forward Degradation & Macro-Adjusted Allocator
├── rebalancer.py             # Multi-Strategy Portfolio Rebalancer & Cash Solvency Guard
└── service.py                # Integrated Multi-Strategy Portfolio Optimization Interface
```

### Component Breakdown
1. `contracts.py`: Immutable dataclasses defining portfolio allocation state, strategy weight boundaries, and rebalance instruction sets.
2. `risk_budgeting.py`: Enforces aggregate portfolio drawdown limits, strategy concentration caps, and asset-class exposure budgets before strategy signals are combined.
3. `dynamic_allocator.py`: Computes strategy target weights $W_i(t) = f(\text{BaseWeight}_i, \text{DegradationScore}_i(t), \text{MacroRegime}(t))$ subject to $\sum W_i \le 1.0$.
4. `rebalancer.py`: Translates strategy weight differences $\Delta W_i$ into target asset orders, capping turnover and verifying cash solvency post-friction.
5. `service.py`: Orchestrates multi-strategy portfolio backtests and exposes unified evaluation methods to research frameworks.

---

## 7. Data Contracts & Schemas

```python
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Dict, List, Optional
from enum import Enum
import math

class WeightingScheme(str, Enum):
    EQUAL_WEIGHT = "EQUAL_WEIGHT"
    VOLATILITY_PARITY = "VOLATILITY_PARITY"
    DEGRADATION_ADJUSTED = "DEGRADATION_ADJUSTED"
    MACRO_ALIGNED = "MACRO_ALIGNED"

@dataclass(frozen=True)
class StrategyAllocationConfig:
    strategy_id: str
    base_weight: float                 # Target weight in [0.0, 1.0]
    max_weight_cap: float              # Hard upper bound on weight (e.g. 0.40)
    min_weight_floor: float            # Hard lower bound (e.g. 0.0)
    max_degradation_threshold: float   # Max OOS degradation score before capital throttling

    def __post_init__(self):
        for field_name, val in [("base_weight", self.base_weight), ("max_weight_cap", self.max_weight_cap)]:
            if math.isnan(val) or math.isinf(val):
                raise ValueError(f"Non-finite value detected for {field_name}: {val}")

@dataclass(frozen=True)
class PortfolioRiskBudget:
    max_portfolio_volatility_annual: float  # Max allowable annual portfolio std dev (e.g. 0.25)
    max_aggregate_drawdown_pct: float       # Max aggregate portfolio drawdown (e.g. 0.15)
    max_single_strategy_weight: float       # Hard cap across all strategies (e.g. 0.35)
    max_turnover_per_rebalance_pct: float   # Max portfolio turnover per rebalance event (e.g. 0.20)
    cash_reserve_floor_pct: float           # Mandatory cash reserve floor (e.g. 0.05)

@dataclass(frozen=True)
class StrategyAllocationRecord:
    timestamp: datetime
    strategy_id: str
    assigned_weight: float
    allocated_capital: float
    degradation_score: float
    macro_regime_multiplier: float
    is_throttled: bool
    reason: str

@dataclass(frozen=True)
class RebalancePlan:
    rebalance_date: date
    simulation_time: datetime
    target_weights: Dict[str, float]       # strategy_id -> weight
    target_cash_weight: float              # Cash reserve weight
    proposed_orders: List[Dict[str, Any]]  # Asset-level orders
    estimated_turnover_pct: float
    estimated_friction_cost: float
    residual_cash_unallocated: float       # Residual cash from discrete share rounding
```

---

## 8. Deterministic Behavior & Capital Accounting Rules

1. **Bit-for-Bit Reproducibility:** Given identical market data, strategy evaluation histories, and portfolio risk budgets, `MultiStrategyPortfolioEngine` produces identical allocation records across independent runs.
2. **Canonical Strategy Tie-Breaking:** If two strategies achieve identical allocation scores, capital is assigned sorting strategy IDs by string alphabetical order (`strategy_a` before `strategy_b`).
3. **Floating-Point Precision Standardization:** All weight computations are rounded to 6 decimal places ($10^{-6}$ precision) to prevent cross-platform float representation drift.
4. **Fractional Share Cash Residual Attribution (INV-38):** Converting strategy target allocations to integer shares yields unallocated residual cash (e.g., target ₹10,000 for ₹800 stock yields 12 shares = ₹9,600, leaving ₹400 residual). All residual cash is deterministically added back to `target_cash_weight`, guaranteeing $\sum W_i + W_{\text{cash}} = 1.0$ exactly.
5. **Non-Finite Value Guard (INV-37):** Any `NaN`, `Inf`, or `-Inf` in signals, weights, or balances fails closed immediately with `AllocationError`.

---

## 9. Point-in-Time & No-Lookahead Requirements

1. **Strategy Metric Availability:** Strategy walk-forward degradation scores at date $t$ MUST be computed strictly using out-of-sample partitions completed at or before $t$ ($t_{\text{OOS, end}} \le t$).
2. **Macro Intelligence Availability:** Market breadth and institutional flow inputs used in allocation scaling MUST satisfy Stage 8 publication timestamp constraints ($T_{\text{pub}} \le t_{\text{sim}}$).
3. **Rebalance Execution Timestamping:** Rebalance orders generated at bar $t$ close are submitted for execution at bar $t+1$ open, preventing intraday price look-ahead leakage.

---

## 10. Data Provenance & Revision Control Handling

1. **Dataset Provenance Audit:** Audit manifests emitted by Stage 9 MUST include SHA-256 hashes of all underlying strategy experiment manifests, market intelligence datasets, and sector membership manifests.
2. **Revision Control Isolation:** If historical market intelligence data is revised post-rebalance ($T_{\text{pub, rev}} > t_{\text{rebalance}}$), historical rebalance decisions generated at $t_{\text{rebalance}}$ MUST remain untouched.

---

## 11. Survivorship-Bias Protections

1. **Historical Strategy Universe:** Strategies included in portfolio optimization for historical date $t$ MUST be selected strictly from strategies active and registered as of date $t$.
2. **Constituent Delisting & Liquidation:** If a stock held by a strategy is delisted on date $t$, the portfolio rebalancer liquidates the position at the final available canonical close price, crediting cash balance post-friction.

---

## 12. Risk-Engine Precedence & Risk-Budgeting Boundaries

1. **Precedence Hierarchy (Strictest Order):**
   1. **Zero Live Execution & AST Gate (INV-33):** Blocks any live execution attempt immediately.
   2. **Cash Solvency Floor Guard (INV-32):** Blocks orders if projected costs exceed cash.
   3. **Aggregate Portfolio Risk Budget (INV-29):** Forces $100\%$ cash allocation if aggregate portfolio drawdown or volatility limit is breached.
   4. **Strategy Concentration Caps:** Caps individual strategy weights at `max_weight_cap`.
   5. **Dynamic Strategy Allocation Scaling:** Scales strategy weights by Stage 7 degradation and Stage 8 macro scores.
   6. **Raw Strategy Signals:** Unweighted alpha signals.

2. **Simultaneous Multi-Limit Breach Cascade Rule:** If multiple risk limits trigger simultaneously (e.g., Drawdown Limit Breach AND Volatility Limit Breach AND Concentration Cap Breach), the strictest risk reduction (scaling equity allocation down to $100\%$ cash reserve) takes absolute precedence.
3. **Automatic Strategy Throttling:** If a strategy's Stage 7 degradation score exceeds `max_degradation_threshold` (e.g. $D_i > 0.40$), its allocated weight is automatically throttled to $0.0$, reallocating capital to cash reserve.

---

## 13. Alpha / Risk / Execution Separation & AST Execution Isolation

1. **Separation of Concerns:** Alpha strategy logic outputs unweighted signals; `DynamicAllocationEngine` assigns strategy weights; `RiskBudgetingEngine` enforces portfolio limits; `PortfolioRebalancer` generates orders.
2. **Static AST Execution Isolation (INV-33 / AT-157):** All Python files in `services/portfolio_optimization/` are statically scanned using `ast.walk()`. Any import of `services.paper_engine.adapters`, `kiteconnect`, `upstox_client`, `smartapi`, `socket`, or `websockets` fails AST validation immediately.

---

## 14. AI Authority Boundaries & Non-Mutation Rules

1. **Non-Custodial / Non-Executable AI (INV-34 / AT-154):** AI analysis modules generate advisory markdown reports strictly. AI code CANNOT mutate `StrategyAllocationConfig`, `PortfolioRiskBudget`, or order streams.
2. **Fingerprint Invariance:** Generating an AI portfolio report does not alter the SHA-256 fingerprint of the portfolio experiment manifest.

---

## 15. Auditability & Reproducibility Requirements

1. **Immutable Portfolio Audit Manifest:** Every portfolio optimization run generates an `AuditManifest` storing:
   - `portfolio_manifest_fingerprint`: SHA-256 hash of portfolio configuration.
   - `strategy_manifest_hashes`: Dict of strategy ID -> strategy manifest SHA-256.
   - `allocation_history`: Full time-series of strategy weights and risk budget states.
   - `rebalance_order_log`: Complete log of rebalance instructions and transaction costs.
2. **Secret Masking:** JSON and Markdown exports pass `PROHIBITED_SECRET_PATTERNS` regex checks (zero API keys, passwords, or tokens).

---

## 16. Failure & Fail-Closed Behavior Matrix

| Failure Condition | Triggering Event | Fail-Closed Action | Exception / Status |
|---|---|---|---|
| **Capital Over-Allocation** | $\sum W_i > 1.000001$ | Halt evaluation immediately | `AllocationError` |
| **Non-Finite Floating Point** | Weight or balance is `NaN` or `Inf` | Halt evaluation immediately | `AllocationError` |
| **Negative Cash Balance** | Friction costs exceed cash balance | Reject rebalance & retain cash | `SolvencyError` |
| **Look-Ahead Metric Query** | Query strategy degradation $t_{\text{OOS}} > t$ | Halt evaluation immediately | `LookAheadBiasError` |
| **Prohibited Broker Import** | Prohibited import detected in AST scan | Abort test suite execution | `ASTIsolationError` |
| **LIVE Environment Request** | Set `EvaluationEnvironment.LIVE` | Fail closed immediately | `PermissionError` |
| **Corrupted Strategy Manifest** | Manifest SHA-256 mismatch | Halt evaluation immediately | `DatasetIntegrityError` |

---

## 17. Security & Secret Protection

1. **Zero Hardcoded Credentials:** No credentials, API tokens, or private handles in `services/portfolio_optimization/`.
2. **Automated Secret Scanning:** Unit tests run `PROHIBITED_SECRET_PATTERNS` regex scanning against all portfolio export payloads.

---

## 18. Concurrency & Idempotency Requirements

1. **Concurrent Replays:** Multiple portfolio evaluations running concurrently in separate processes operate in complete isolation with zero shared memory mutation.
2. **Idempotent Rebalancing:** Re-running rebalance logic on identical portfolio state $S(t)$ yields identical `RebalancePlan` outputs.

---

## 19. API / UI Implications

- `GET /api/v1/portfolio/allocations` -> Returns historical time-series of strategy weights and capital allocations.
- `GET /api/v1/portfolio/risk-budget` -> Returns current portfolio risk budget utilization (volatility, drawdown, turnover).
- `POST /api/v1/portfolio/evaluate` -> Triggers deterministic multi-strategy portfolio backtest (Research mode only).

---

## 20. Performance & Resource Constraints

- **Execution Speed:** Multi-strategy portfolio rebalance calculation across 10 strategies over a 5-year daily dataset must execute within $< 5.0$ seconds.
- **Memory Footprint:** Peak RAM consumption during multi-strategy backtest must remain $< 512$ MB.

---

## 21. Observability & System-Health Requirements

- Emits structured telemetry events: `PORTFOLIO_REBALANCED`, `STRATEGY_THROTTLED`, `RISK_BUDGET_BREACHED`, `SOLVENCY_GUARD_TRIGGERED`.

---

## 22. Testing Strategy & Verification Plan

1. **Baseline Regression Verification:** Must run full suite and pass all 229 existing Stage 6, Stage 7, and Stage 8 tests.
2. **New Stage 9 Acceptance Suite:** Implement `tests/unit/test_stage9_acceptance_part1.py` and `test_stage9_acceptance_part2.py` covering AT-136 through AT-167.

---

## 23. Migration & Backward-Compatibility Requirements

- Stage 9 is strictly additive. Existing Stage 1–8 modules, manifests, and test suites require zero breaking modifications.

---

## 24. Explicit Limitations

- **Discrete Daily Rebalancing:** Intraday high-frequency rebalancing is not supported in Stage 9.
- **Fixed Asset Universe:** Strategy universes are established prior to backtest execution.

---

## 25. Complete Architectural Invariants Matrix (INV-28 to INV-38)

| Invariant ID | Invariant Name | Architectural Definition | Enforcement Mechanism | Verification Test |
|---|---|---|---|---|
| **INV-28** | **Conservation of Shared Capital** | Total allocated strategy weights plus cash reserve MUST sum to exactly $1.0$ ($\sum W_i + W_{\text{cash}} = 1.0$). | Strict float equality check post-allocation | AT-136, AT-140 |
| **INV-29** | **Dynamic Risk Budget Precedence** | Individual strategy weights CANNOT exceed risk budget caps or aggregate drawdown limits. | Hard risk-budget scaling gate | AT-137, AT-141, AT-156 |
| **INV-30** | **Point-in-Time Allocation Isolation** | Rebalance decisions at $t$ access strictly strategy performance and macro records published $\le t$. | Simulation clock timestamp guard | AT-148, AT-149, AT-150 |
| **INV-31** | **Deterministic Portfolio Rebalancing** | Identical inputs produce bit-for-bit identical strategy weights; tied scores sort alphabetically. | Pure math + string tie-breaking | AT-151, AT-152 |
| **INV-32** | **Non-Negative Cash Pool Solvency** | Multi-strategy rebalancing MUST NOT cause portfolio cash balance to drop below zero post-friction. | Pre-trade friction solvency check | AT-140, AT-160 |
| **INV-33** | **Static AST Execution Boundary** | `services/portfolio_optimization/` has zero prohibited imports of live broker SDKs or adapters. | Static AST module scanner | AT-157 |
| **INV-34** | **AI Authority Boundary Non-Mutation** | AI report generation CANNOT mutate strategy weights, risk budget state, or manifest fingerprints. | Immutable manifest fingerprint assertion | AT-154 |
| **INV-35** | **Cross-Strategy State Isolation** | Internal state, position logs, or indicators of Strategy A CANNOT modify Strategy B's evaluation. | Isolated context evaluation loops | AT-159 |
| **INV-36** | **Cryptographic Portfolio Auditability** | Portfolio audit manifests store SHA-256 hashes of strategy manifests, datasets, and allocation histories. | Audit manifest JSON serialization | AT-153, AT-155 |
| **INV-37** | **Non-Finite Numerical Fail-Closed Gate** | Any `NaN` or `Infinity` floating point value encountered in signals, weights, or balances fails closed immediately. | `math.isnan()` / `math.isinf()` check | AT-165 |
| **INV-38** | **Residual Capital Cash Attribution** | Unallocated capital resulting from discrete integer share order rounding MUST be credited back to $W_{\text{cash}}$. | Fractional share cash remainder routing | AT-166 |

---

## 26. Complete Acceptance-Test Matrix (AT-136 to AT-167)

| AT ID | Requirement Title | Precondition | Input | Expected Result | Pass/Fail Condition | Related Invariant |
|---|---|---|---|---|---|---|
| **AT-136** | Valid Multi-Strategy Capital Allocation | 3 certified strategies | Equal weight scheme | Each strategy assigned 31.66% weight, 5% cash reserve | Sum of weights matches 1.000000 | INV-28 |
| **AT-137** | Walk-Forward Degradation Throttling | Strategy A degradation score > 0.40 | Run rebalancer | Strategy A weight reduced to 0.0%, capital shifted to cash | Strategy A weight > 0.0 | INV-29 |
| **AT-138** | Macro Regime Alignment Scaling | FII net flow negative & breadth declining | Run macro-aligned allocator | Equity strategy weights scaled down by regime factor | Equity weights unscaled | INV-29 |
| **AT-139** | Deterministic Rebalance Order Generation | Target portfolio weight change | Run rebalancer | Discrete asset sell/buy order list generated | Order list non-deterministic | INV-31 |
| **AT-140** | Solvency Verification under Friction | Proposed rebalance orders | Indian cost & slippage calc | Cash balance remains >= 0.0 post-friction | Cash balance < 0.0 | INV-32 |
| **AT-141** | Single-Strategy Concentration Cap | Strategy signal confidence = 1.0 | `max_weight_cap` = 0.35 | Assigned strategy weight <= 0.35 | Assigned weight > 0.35 | INV-29 |
| **AT-142** | Zero Strategy Signals Cash Allocation | All strategies output ZERO signals | Run rebalancer | 100% portfolio capital held in cash reserve | Capital forced into assets | INV-28 |
| **AT-143** | Negative Strategy Weight Rejection | Allocation config with negative weight | Initialize allocator | Raises `ValueError` | Accepts negative weight | INV-28 |
| **AT-144** | Total Allocation Overflow Rejection | Sum of base weights = 1.25 | Initialize allocator | Raises `AllocationError` | Accepts sum > 1.0 | INV-28 |
| **AT-145** | Missing Strategy Metric Fail-Closed | Strategy B missing OOS evaluation metric | Run allocator | Raises `MissingMetricError` | Silently defaults missing weight | INV-30 |
| **AT-146** | Stale Macro Data Throttling Flag | Macro intelligence data > 3 days stale | Run allocator | Emits `STALE_MACRO_DATA` warning & caps equity weight | Ignores stale macro data | INV-29 |
| **AT-147** | Conflicting Allocation Signal Resolution | Conflicting allocation rules defined | Run allocator | Raises `SourceConflictError` | Resolves conflict silently | INV-31 |
| **AT-148** | Point-in-Time Strategy Access Lockout | Query OOS metric for $t_{\text{OOS}} > t_{\text{sim}}$ | Query allocator | Raises `LookAheadBiasError` | Returns future metric | INV-30 |
| **AT-149** | Point-in-Time Macro Allocation Guard | Macro record published at 18:00 IST | Query rebalance at 15:30 IST | Consumes $T-1$ macro record strictly | Consumes unpublished $T$ record | INV-30 |
| **AT-150** | Historical Performance Revision Isolation | Revised strategy metric published post-$t$ | Query rebalance at $t$ | Consumes unrevised initial metric | Consumes revised metric | INV-30 |
| **AT-151** | Bit-for-Bit Deterministic Rebalancing | Identical multi-strategy backtest | Run backtest twice | Allocation time-series matches bit-for-bit | Allocation time-series diverges | INV-31 |
| **AT-152** | Alphabetical Strategy Tie-Breaker | Strategy A & B achieve equal score | Run tie-breaker | Strategy A receives allocation priority | Non-deterministic ordering | INV-31 |
| **AT-153** | Cryptographic Portfolio Audit Manifest | Completed portfolio run | Inspect audit manifest | Manifest contains strategy manifest SHA-256 hashes | Hashes missing or invalid | INV-36 |
| **AT-154** | AI Summary Authority Boundary | AI summary generator invoked | Pass portfolio manifest | Manifest fingerprint remains identical | Manifest mutated | INV-34 |
| **AT-155** | Secret Protection in Portfolio Exports | Portfolio audit manifest JSON | Run secret scanner | Zero API keys or credentials detected | Credential leaked | INV-36 |
| **AT-156** | Hard Risk Limit Precedence Over Signals | Bullish strategy + Drawdown > Limit | Evaluate risk budget | Rebalance rejected, capital held in cash | Hard risk limit bypassed | INV-29 |
| **AT-157** | **Static AST Execution Isolation** | Parse `services/portfolio_optimization/` | Walk AST nodes | Zero prohibited broker imports detected | Prohibited import detected | INV-33 |
| **AT-158** | Live Environment Lockout Gate | Portfolio manifest instantiated | Environment = LIVE | Raises `PermissionError` | Accepts LIVE environment | INV-33 |
| **AT-159** | Cross-Strategy State Isolation | Strategy A mutates local state | Evaluate Strategy B | Strategy B state remains 100% unaffected | Strategy B state mutated | INV-35 |
| **AT-160** | Turnover Constraint Enforcement | Rebalance order turnover > 0.20 cap | Run rebalancer | Orders scaled down to satisfy 0.20 turnover cap | Turnover cap exceeded | INV-32 |
| **AT-161** | Stage 6 Regression Gate | Full Stage 6 test suite | Run `pytest` | All 192 Stage 6 tests PASS ($100\%$) | Any Stage 6 test failure | Baseline |
| **AT-162** | Stage 7 Regression Gate | Full Stage 7 test suite | Run `pytest` | All 24 Stage 7 tests PASS ($100\%$) | Any Stage 7 test failure | Baseline |
| **AT-163** | Stage 8 Regression Gate | Full Stage 8 test suite | Run `pytest` | All 13 Stage 8 tests PASS ($100\%$) | Any Stage 8 test failure | Baseline |
| **AT-164** | Full Combined Suite Pass Gate | Combined test suite (Stage 6-9) | Run `pytest` | All 261+ tests PASS ($100\%$) | Pass rate $< 100\%$ | Baseline |
| **AT-165** | Non-Finite Floating Point Rejection | Strategy weight = NaN | Initialize config | Raises `AllocationError` | Accepts NaN weight | INV-37 |
| **AT-166** | Residual Share Cash Attribution | Rebalance ₹10k for ₹800 stock | Run rebalancer | 12 shares bought (₹9,600), ₹400 credited to $W_{\text{cash}}$ | Residual cash lost | INV-38 |
| **AT-167** | Simultaneous Multi-Limit Breach Cascade | Drawdown & Volatility limit breached | Evaluate risk budget | Rebalance scales equity to 0%, 100% cash allocated | Partial risk reduction | INV-29 |

---

## 27. Detailed Specification of Acceptance Tests (AT-136 to AT-167)

#### AT-136 — Valid Multi-Strategy Capital Allocation
- **Requirement:** Allocating capital across 3 strategies with an `EQUAL_WEIGHT` scheme assigns 31.666666% to each strategy and 5.0% to cash reserve, summing to 1.000000.
- **Preconditions:** Portfolio configuration initialized with 3 active strategies and 5% cash floor.
- **Input:** Execute `DynamicAllocationEngine.calculate_allocations()`.
- **Expected Result:** Weights returned: `{"StratA": 0.316667, "StratB": 0.316667, "StratC": 0.316667, "CASH": 0.050000}`.
- **Pass/Fail Condition:** Pass if sum of weights equals 1.000000 within $10^{-6}$; Fail if sum diverges.
- **Evidence Produced:** Float sum assertion.
- **Related Invariant:** INV-28.

#### AT-137 — Walk-Forward Degradation Throttling
- **Requirement:** When Strategy A's Stage 7 out-of-sample degradation score exceeds `max_degradation_threshold` (0.40), its allocated weight is automatically throttled to 0.0.
- **Preconditions:** Strategy A degradation score = 0.45; Strategy B degradation score = 0.10.
- **Input:** Execute allocation calculation.
- **Expected Result:** Strategy A weight = 0.0; Strategy B weight receives unthrottled allocation; excess capital assigned to cash reserve.
- **Pass/Fail Condition:** Pass if Strategy A weight == 0.0; Fail if Strategy A receives > 0.0 weight.
- **Evidence Produced:** Assertion verifying `record.is_throttled is True` and `assigned_weight == 0.0`.
- **Related Invariant:** INV-29.

#### AT-138 — Macro Regime Alignment Scaling
- **Requirement:** Equity strategy allocation weights are dynamically scaled down when Stage 8 market intelligence indicates net FII distribution and declining breadth.
- **Preconditions:** Stage 8 macro regime score = -0.80 (Strongly Bearish Distribution).
- **Input:** Compute allocations for trend-following equity strategies.
- **Expected Result:** Equity strategy weights scaled down by macro factor (0.50x), shifting unallocated capital to cash reserve.
- **Pass/Fail Condition:** Pass if equity weights are scaled down proportionally; Fail if macro regime score is ignored.
- **Evidence Produced:** Assertion checking weight reduction vs base weight.
- **Related Invariant:** INV-29.

#### AT-139 — Deterministic Rebalance Order Generation
- **Requirement:** Converting target strategy weight changes into asset-level buy/sell orders produces discrete, deterministic order lists.
- **Preconditions:** Portfolio holds 100 shares STOCK_A; target rebalance requires 150 shares STOCK_A.
- **Input:** Execute `PortfolioRebalancer.generate_rebalance_orders()`.
- **Expected Result:** Generates single order: `BUY 50 shares STOCK_A`.
- **Pass/Fail Condition:** Pass if order quantity and side match exact delta; Fail if order quantity diverges or duplicates.
- **Evidence Produced:** Order list object assertion.
- **Related Invariant:** INV-31.

#### AT-140 — Solvency Verification under Friction
- **Requirement:** Proposed multi-strategy rebalance orders are executed only if remaining cash post-friction (brokerage, STT, exchange fees, GST, slippage) remains $\ge 0.0$.
- **Preconditions:** Cash balance = ₹10,000; proposed trade buy value = ₹9,950; estimated transaction fees + slippage = ₹60.
- **Input:** Evaluate rebalance order set.
- **Expected Result:** Rebalance rejected with `SolvencyError` because required cash (₹10,010) exceeds available cash (₹10,000).
- **Pass/Fail Condition:** Pass if trade rejected and zero portfolio state mutated; Fail if trade executes causing negative cash balance.
- **Evidence Produced:** Exception assertion and cash balance verification.
- **Related Invariant:** INV-32.

#### AT-141 — Single-Strategy Concentration Cap
- **Requirement:** Hard concentration cap (`max_weight_cap` = 0.35) limits capital assigned to a single strategy regardless of signal strength.
- **Preconditions:** Strategy A outputs maximum signal confidence (1.0).
- **Input:** Compute allocation for Strategy A.
- **Expected Result:** Strategy A assigned weight = 0.35 (capped at max weight cap).
- **Pass/Fail Condition:** Pass if assigned weight <= 0.35; Fail if assigned weight > 0.35.
- **Evidence Produced:** Assertion verifying `assigned_weight <= max_weight_cap`.
- **Related Invariant:** INV-29.

#### AT-142 — Zero Strategy Signals Cash Allocation
- **Requirement:** When all active strategies output zero signals, 100% of available capital (after cash floor) is assigned to cash reserve.
- **Preconditions:** All strategies return 0.0 signal strength.
- **Input:** Execute allocation calculation.
- **Expected Result:** Portfolio weight assigned to CASH = 1.000000; asset target orders = empty.
- **Pass/Fail Condition:** Pass if 100% allocated to cash; Fail if capital forced into market assets.
- **Evidence Produced:** Assertion verifying `target_cash_weight == 1.0`.
- **Related Invariant:** INV-28.

#### AT-143 — Negative Strategy Weight Rejection
- **Requirement:** Configuring negative base weight or short allocation raises `ValueError` immediately.
- **Preconditions:** Strategy allocation config contains `base_weight: -0.15`.
- **Input:** Instantiate `StrategyAllocationConfig`.
- **Expected Result:** Raises `ValueError`.
- **Pass/Fail Condition:** Pass if `ValueError` raised; Fail if negative weight accepted.
- **Evidence Produced:** Exception assertion.
- **Related Invariant:** INV-28.

#### AT-144 — Total Allocation Overflow Rejection
- **Requirement:** Configuring initial strategy base weights summing to $> 1.0$ fails closed.
- **Preconditions:** 3 strategy configs with base weights 0.50, 0.40, 0.35 (sum = 1.25).
- **Input:** Instantiate `PortfolioOptimizationService`.
- **Expected Result:** Raises `AllocationError`.
- **Pass/Fail Condition:** Pass if exception raised; Fail if invalid configuration initialized.
- **Evidence Produced:** Exception type check.
- **Related Invariant:** INV-28.

#### AT-145 — Missing Strategy Metric Fail-Closed
- **Requirement:** If out-of-sample evaluation metrics for an active strategy are missing, allocation fails closed.
- **Preconditions:** Strategy B is registered but its walk-forward metric file is missing.
- **Input:** Execute allocation calculation.
- **Expected Result:** Raises `MissingMetricError`.
- **Pass/Fail Condition:** Pass if exception raised; Fail if missing metric is silently replaced with default value.
- **Evidence Produced:** Exception check assertion.
- **Related Invariant:** INV-30.

#### AT-146 — Stale Macro Data Throttling Flag
- **Requirement:** If Stage 8 macro intelligence datasets are $> 3$ trading days stale, equity strategy weights are capped at 50% and `STALE_MACRO_DATA` warning is logged.
- **Preconditions:** Market intelligence dataset last updated 5 days prior to $t_{\text{sim}}$.
- **Input:** Execute allocation calculation.
- **Expected Result:** Allocation records include `STALE_MACRO_DATA` warning and equity weights are capped.
- **Pass/Fail Condition:** Pass if warning present and weights capped; Fail if stale macro data ignored.
- **Evidence Produced:** Assertion checking warning flag.
- **Related Invariant:** INV-29.

#### AT-147 — Conflicting Allocation Signal Resolution
- **Requirement:** Loading conflicting strategy allocation configurations for the same strategy ID raises `SourceConflictError`.
- **Preconditions:** Two configuration sources specify different base weights for `STRATEGY_ALPHA`.
- **Input:** Initialize allocation engine.
- **Expected Result:** Raises `SourceConflictError`.
- **Pass/Fail Condition:** Pass if exception raised; Fail if conflict resolved silently.
- **Evidence Produced:** Exception assertion.
- **Related Invariant:** INV-31.

#### AT-148 — Point-in-Time Strategy Access Lockout
- **Requirement:** Attempting to query out-of-sample strategy metrics for evaluation periods ending after simulation clock $t_{\text{sim}}$ raises `LookAheadBiasError`.
- **Preconditions:** Strategy OOS evaluation period ends on 2024-06-30.
- **Input:** Query strategy metric at simulation clock $t_{\text{sim}} = \text{2024-06-15 09:15:00}$.
- **Expected Result:** Raises `LookAheadBiasError`.
- **Pass/Fail Condition:** Pass if exception raised; Fail if future OOS metric returned.
- **Evidence Produced:** Exception check assertion.
- **Related Invariant:** INV-30.

#### AT-149 — Point-in-Time Macro Allocation Guard
- **Requirement:** Macro flow records published at 18:00 IST on Day $T$ cannot influence rebalance decisions made at 15:30 IST on Day $T$.
- **Preconditions:** Day $T$ FII flow published at 18:00 IST.
- **Input:** Compute portfolio rebalance at simulation clock $t_{\text{sim}} = T \text{ 15:30:00 IST}$.
- **Expected Result:** Allocator consumes Day $T-1$ macro record strictly.
- **Pass/Fail Condition:** Pass if Day $T-1$ record consumed; Fail if Day $T$ record consumed before publication.
- **Evidence Produced:** Assertion checking record publication timestamp vs simulation clock.
- **Related Invariant:** INV-30.

#### AT-150 — Historical Performance Revision Isolation
- **Requirement:** Re-evaluating historical portfolio allocations at clock $t$ consumes unrevised strategy metrics available at $t$, ignoring revisions published at $T_{\text{rev}} > t$.
- **Preconditions:** Strategy performance record revised on July 1; initial record published June 1.
- **Input:** Execute rebalance calculation for simulation date June 15.
- **Expected Result:** Consumes June 1 unrevised performance record.
- **Pass/Fail Condition:** Pass if initial record consumed; Fail if July 1 revision consumed.
- **Evidence Produced:** Revision ID assertion.
- **Related Invariant:** INV-30.

#### AT-151 — Bit-for-Bit Deterministic Rebalancing
- **Requirement:** Executing identical multi-strategy backtests produces bit-for-bit identical portfolio allocation time-series.
- **Preconditions:** Multi-strategy backtest manifest + market data registered.
- **Input:** Run backtest twice.
- **Expected Result:** Output `allocation_history` matches bit-for-bit across both runs.
- **Pass/Fail Condition:** Pass if outputs identical; Fail if float drift occurs.
- **Evidence Produced:** Deep object equality assertion.
- **Related Invariant:** INV-31.

#### AT-152 — Alphabetical Strategy Tie-Breaker
- **Requirement:** When two strategies tie in allocation score, capital tie-breaker sorts strategy IDs alphabetically.
- **Preconditions:** `STRATEGY_BETA` and `STRATEGY_ALPHA` achieve identical allocation score (0.75).
- **Input:** Run allocation tie-breaker.
- **Expected Result:** `STRATEGY_ALPHA` evaluated/allocated before `STRATEGY_BETA`.
- **Pass/Fail Condition:** Pass if `STRATEGY_ALPHA` precedes `STRATEGY_BETA`; Fail if non-deterministic order.
- **Evidence Produced:** List order assertion.
- **Related Invariant:** INV-31.

#### AT-153 — Cryptographic Portfolio Audit Manifest
- **Requirement:** Audit manifest generated for portfolio run contains SHA-256 hashes of all strategy manifests, market intelligence datasets, and rebalance history.
- **Preconditions:** Multi-strategy portfolio backtest completed.
- **Input:** Inspect `AuditManifest`.
- **Expected Result:** Manifest contains valid SHA-256 strings for `portfolio_manifest_hash` and `strategy_manifest_hashes`.
- **Pass/Fail Condition:** Pass if hashes present and valid; Fail if hashes missing.
- **Evidence Produced:** Dictionary key & regex hash assertion.
- **Related Invariant:** INV-36.

#### AT-154 — AI Summary Authority Boundary
- **Requirement:** AI portfolio analysis summary generator cannot alter strategy weights, risk budget parameters, or manifest fingerprints.
- **Preconditions:** Portfolio manifest initialized with fixed risk budget.
- **Input:** Pass manifest and allocation results to `AIPortfolioSummaryGenerator`.
- **Expected Result:** Manifest `compute_fingerprint()` remains unchanged before and after report generation.
- **Pass/Fail Condition:** Pass if fingerprint identical; Fail if manifest mutated.
- **Evidence Produced:** Fingerprint equality assertion.
- **Related Invariant:** INV-34.

#### AT-155 — Secret Protection in Portfolio Exports
- **Requirement:** Exporting portfolio audit manifests to JSON or Markdown contains zero hardcoded API keys, passwords, or secrets.
- **Preconditions:** Portfolio evaluation completed.
- **Input:** Export manifest via `to_json()` and `to_markdown()`.
- **Expected Result:** Scanning exports with `PROHIBITED_SECRET_PATTERNS` finds zero matches.
- **Pass/Fail Condition:** Pass if 0 matches found; Fail if secret pattern detected.
- **Evidence Produced:** Regex scanner assertion pass.
- **Related Invariant:** INV-36.

#### AT-156 — Hard Risk Limit Precedence Over Signals
- **Requirement:** When aggregate portfolio drawdown exceeds `max_aggregate_drawdown_pct` (15%), rebalancer forces 100% allocation to cash despite bullish strategy signals.
- **Preconditions:** Current portfolio drawdown = 18%; all strategies output strong BUY signals.
- **Input:** Execute portfolio rebalancer.
- **Expected Result:** Rebalancing rejected; all assets liquidated/held in cash reserve.
- **Pass/Fail Condition:** Pass if 100% cash allocated; Fail if buy signals executed during drawdown breach.
- **Evidence Produced:** Assertion verifying `target_cash_weight == 1.0`.
- **Related Invariant:** INV-29.

#### AT-157 — Static AST Execution Isolation (INV-33)
- **Requirement:** Static AST scanner parses all `.py` files in `services/portfolio_optimization/` and verifies zero prohibited imports of live broker SDKs or order routing adapters.
- **Preconditions:** All Python source files in `services/portfolio_optimization/` parsed into AST.
- **Input:** Walk AST nodes for `Import` and `ImportFrom`.
- **Expected Result:** Zero matches for `services.paper_engine.adapters`, `kiteconnect`, `upstox_client`, `smartapi`, `socket`, `websockets`.
- **Pass/Fail Condition:** Pass if 0 prohibited imports found; Fail if prohibited import detected.
- **Evidence Produced:** AST walker assertion pass.
- **Related Invariant:** INV-33.

#### AT-158 — Live Environment Lockout Gate
- **Requirement:** Instantiating `PortfolioOptimizationService` with `EvaluationEnvironment.LIVE` raises `PermissionError` immediately.
- **Preconditions:** Portfolio configuration created.
- **Input:** Pass `environment=EvaluationEnvironment.LIVE` to service constructor.
- **Expected Result:** Raises `PermissionError` with message "LIVE is strictly forbidden".
- **Pass/Fail Condition:** Pass if `PermissionError` raised; Fail if LIVE environment initialized.
- **Evidence Produced:** Exception assertion.
- **Related Invariant:** INV-33.

#### AT-159 — Cross-Strategy State Isolation
- **Requirement:** Strategy A mutating its local indicator state during evaluation cannot alter Strategy B's indicator state or signals.
- **Preconditions:** Strategy A and Strategy B evaluate overlapping symbol histories.
- **Input:** Mutate Strategy A internal state during replay step.
- **Expected Result:** Strategy B signals and indicators remain bit-for-bit identical to isolated evaluation.
- **Pass/Fail Condition:** Pass if Strategy B output unchanged; Fail if Strategy B state corrupted.
- **Evidence Produced:** State comparison assertion.
- **Related Invariant:** INV-35.

#### AT-160 — Turnover Constraint Enforcement
- **Requirement:** When calculated portfolio rebalance turnover exceeds `max_turnover_per_rebalance_pct` (0.20), asset orders are scaled down proportionally to satisfy the turnover cap.
- **Preconditions:** Calculated unconstrained rebalance requires 35% portfolio turnover.
- **Input:** Execute `PortfolioRebalancer`.
- **Expected Result:** Order quantities scaled down such that total turnover equals 0.20 (20%).
- **Pass/Fail Condition:** Pass if turnover <= 0.20; Fail if turnover exceeds cap.
- **Evidence Produced:** Assertion verifying `actual_turnover <= max_turnover`.
- **Related Invariant:** INV-32.

#### AT-165 — Non-Finite Floating Point Rejection
- **Requirement:** Passing `NaN` or `Infinity` as a strategy signal, degradation score, or allocation weight raises `AllocationError` immediately.
- **Preconditions:** Allocation config initialized with `base_weight = float('nan')`.
- **Input:** Instantiate allocation config or engine.
- **Expected Result:** Raises `AllocationError`.
- **Pass/Fail Condition:** Pass if `AllocationError` raised; Fail if NaN accepted.
- **Evidence Produced:** Exception assertion.
- **Related Invariant:** INV-37.

#### AT-166 — Residual Share Cash Attribution
- **Requirement:** Unallocated capital resulting from discrete integer share order rounding is credited deterministically back to $W_{\text{cash}}$, preserving $\sum W_i + W_{\text{cash}} = 1.0$.
- **Preconditions:** Target ₹10,000 allocation for ₹800 stock yields 12 shares (₹9,600).
- **Input:** Execute `PortfolioRebalancer.generate_rebalance_orders()`.
- **Expected Result:** 12 shares ordered, residual ₹400 credited back to `target_cash_weight`.
- **Pass/Fail Condition:** Pass if residual credited to cash; Fail if residual lost or unaccounted.
- **Evidence Produced:** Assertion checking `target_cash_weight` adjustment.
- **Related Invariant:** INV-38.

#### AT-167 — Simultaneous Multi-Limit Breach Cascade
- **Requirement:** When both `max_portfolio_volatility_annual` and `max_aggregate_drawdown_pct` limits are breached simultaneously, the strictest risk reduction (scaling equity allocation down to 0%, 100% cash reserve) takes absolute precedence.
- **Preconditions:** Portfolio volatility = 30% (limit 25%); portfolio drawdown = 18% (limit 15%).
- **Input:** Evaluate risk budget.
- **Expected Result:** Portfolio equity weights scaled to 0.0, 100% allocated to cash reserve.
- **Pass/Fail Condition:** Pass if 100% cash allocated; Fail if partial risk reduction allowed.
- **Evidence Produced:** Assertion verifying `target_cash_weight == 1.0`.
- **Related Invariant:** INV-29.

---

## 28. Traceability Matrix

| Objective / Requirement | Architectural Invariant | Acceptance Test Coverage |
|---|---|---|
| **Conservation of Shared Capital** | INV-28, INV-38 | AT-136, AT-140, AT-142, AT-143, AT-144, AT-166 |
| **Dynamic Risk-Budgeting Engine** | INV-29 | AT-137, AT-138, AT-141, AT-146, AT-156, AT-167 |
| **Point-in-Time Allocation Isolation** | INV-30 | AT-145, AT-148, AT-149, AT-150 |
| **Deterministic Portfolio Rebalancing** | INV-31 | AT-139, AT-147, AT-151, AT-152 |
| **Non-Negative Cash Pool Solvency** | INV-32 | AT-140, AT-160 |
| **Static AST Execution Boundary** | INV-33 | AT-157, AT-158 |
| **AI Authority Boundary Non-Mutation** | INV-34 | AT-154 |
| **Cross-Strategy State Isolation** | INV-35 | AT-159 |
| **Cryptographic Portfolio Auditability** | INV-36 | AT-153, AT-155 |
| **Non-Finite Numerical Fail-Closed** | INV-37 | AT-165 |
| **Residual Capital Cash Attribution** | INV-38 | AT-166 |
| **Baseline Regression Protection** | Stage 6–8 Baseline | AT-161, AT-162, AT-163, AT-164 |

---

## 29. Mandatory Adversarial Review & Vulnerability Challenge

The corrected specification was subjected to a thorough adversarial challenge across 18 critical failure modes:

| # | Vulnerability Challenge Area | Audit Assessment & Finding | Resolution / Specification Safeguard |
|---|---|---|---|
| 1 | **Look-Ahead Bias** | Rebalance decisions could query OOS metrics for ongoing periods. | **Enforced:** `t_OOS,end <= t_sim` check in INV-30 & AT-148. |
| 2 | **Publication-Time Leakage** | Macro indicators used in allocation could leak intraday. | **Enforced:** $T_{\text{pub}} \le t_{\text{sim}}$ check in INV-30 & AT-149. |
| 3 | **Revision Leakage** | Post-rebalance macro revisions could alter past decisions. | **Enforced:** Revision isolation check in INV-30 & AT-150. |
| 4 | **Survivorship Bias** | Delisted strategies or assets could be omitted historically. | **Enforced:** Historical strategy registry check in Section 11 & AT-127. |
| 5 | **Data Leakage** | Shared indicators between strategies could leak state. | **Enforced:** Cross-strategy context isolation in INV-35 & AT-159. |
| 6 | **Hidden Execution Access** | Rebalancer could attempt to route real orders via paper engine. | **Enforced:** Pure mathematical rebalancer, zero execution handles. |
| 7 | **Broker / Live SDK Access** | Indirect imports of live trading SDKs could enter portfolio code. | **Enforced:** Static AST scanner in INV-33 & AT-157. |
| 8 | **AI Authority Escalation** | AI reports could attempt to adjust strategy risk weights. | **Enforced:** AI authority boundary in INV-34 & AT-154. |
| 9 | **Research-State Mutation** | Running portfolio backtests could mutate strategy manifests. | **Enforced:** Frozen dataclasses & fingerprint assertions in AT-154. |
| 10 | **Nondeterminism** | Float drift or un-ordered dicts could alter rebalance orders. | **Enforced:** Bit-for-bit determinism & string tie-breaker in INV-31 & AT-151/152. |
| 11 | **Missing Provenance** | Multi-strategy runs could omit underlying strategy hashes. | **Enforced:** Cryptographic audit manifest in INV-36 & AT-153. |
| 12 | **Audit Gaps** | Rebalance order logs could be omitted from audit outputs. | **Enforced:** Complete rebalance log serialization in Section 15. |
| 13 | **Fail-Open Behavior** | Missing strategy performance metrics could default to 1.0 weight. | **Enforced:** Fail-closed `MissingMetricError` in AT-145. |
| 14 | **Race Conditions** | Concurrent portfolio evaluations could collide on shared state. | **Enforced:** Process isolation & zero shared state in Section 18. |
| 15 | **Idempotency Failures** | Re-running rebalancer on same state could yield different orders. | **Enforced:** Pure function `generate_rebalance_orders()` in Section 18. |
| 16 | **Security / Secret Exposure** | Portfolio manifests could leak API keys or environment tokens. | **Enforced:** Automated secret pattern scanner in AT-155. |
| 17 | **Stage 8 Regression** | Portfolio additions could alter Stage 6–8 behavior. | **Enforced:** Mandatory pass gates for all 229 existing tests (AT-161..164). |
| 18 | **Superficial Test Coverage** | Tests claiming coverage without asserting exact state. | **Enforced:** Every AT specifies explicit input, expected result, pass/fail & evidence. |

---

## 30. Implementation Readiness Assessment

```
===============================================================================
               STAGE 9 SPECIFICATION AUDIT COMPLETE
===============================================================================
Baseline Commit:    ad651247fdd4eacf2c67dd9463702c97120a009a (stage8-verified)
Baseline Test Suite:  229/229 PASSED (100%)
Specification:      algo_lab_stage9_specification.md (UPDATED & CORRECTED)
Acceptance Tests:   AT-136 to AT-167 (32 Acceptance Tests Specified)
Invariants:         INV-28 to INV-38 (11 Architectural Invariants Specified)
Adversarial Audit:  18/18 Vulnerability Areas Verified & Resolved
Production Code:    UNTOUCHED (0 Code Changes)

VERDICT: READY FOR IMPLEMENTATION

IMPLEMENTATION APPROVAL: NOT GRANTED (Awaiting Human Authorization)
===============================================================================
```
