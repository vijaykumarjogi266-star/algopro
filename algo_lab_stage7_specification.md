# Algo Lab — Stage 7 Specification & Implementation Plan

**Project:** Algo Lab  
**Stage:** 7 — Research & Strategy Evaluation Layer  
**STATUS:** DRAFT — PENDING HUMAN APPROVAL  
**IMPLEMENTATION:** NOT APPROVED / NOT STARTED  
**BASELINE:** Tag `stage6-verified` | Commit `2c09e57` (2c09e57765d39bb018f212f8844504fcb7fc215e)  
**BASELINE CERTIFICATION:** 192/192 tests passing  
**CODE CHANGES:** NONE  

---

## 1. Executive Summary & Philosophy

Stage 7 establishes the **Research & Strategy Evaluation Layer** atop the certified Stage 5 strategy foundation and Stage 6 market-data/replay/paper-trading infrastructure.

The core objective of Stage 7 is to answer the fundamental question:
> *«Can Algo Lab evaluate a quantitative trading strategy rigorously, deterministically, and reproducibly without look-ahead bias, data leakage, invalid test methodology, hidden assumptions, or uncontrolled parameter selection?»*

Stage 7 is strictly an **offline evaluation and research validation** framework. It establishes a formal architectural firewall between strategy research/evaluation and any form of live/broker execution:
- **Zero Live Execution Pathways:** Zero real-money order routing, zero broker SDK imports, zero live WebSocket execution handlers, and zero execution adapters other than the deterministic evaluation loop.
- **Structural and Behavioral Isolation:** Stage 7 evaluation packages must be isolated structurally (via static AST import inspection) and behaviorally (fail-closed runtime lockout).
- **No Autonomous Strategy Deployment:** No automatic trade generation into production, autonomous parameter selection into live trading, or auto-activation of paper or live broker sessions.
- **Fail-Closed Research Invariants:** If market data is corrupted, checksums drift, timestamps invert, or partitions overlap, the evaluation engine halts immediately with explicit diagnostic exceptions rather than producing distorted metrics.

---

## 2. Problem Statement

Stage 6 provided a certified dataset registry, deterministic bar replay engine, order execution lifecycle simulator, paper trading engine, and broker adapter interfaces. However, Stage 6 lacks a formal, reproducible, out-of-sample research & evaluation layer.

Specifically, Stage 6 alone does not address:
1. **Uncontrolled Overfitting & Data Leakage:** Without formal temporal partitioning (train / validation / test splits), strategies risk optimizing hyperparameters directly on test data, introducing severe look-ahead and selection bias.
2. **Lack of Walk-Forward Validation:** Static single-period backtests fail to evaluate how a strategy adapts over expanding or rolling historical windows.
3. **Friction Sensitivity Blind Spots:** Standard backtests evaluate performance at a single transaction cost and slippage level, failing to test strategy robustness against cost and slippage increases (+10%, +25%, +50%).
4. **Regime Identification:** Strategies evaluated in aggregate lack visibility into performance across distinct market regimes (Bull, Bear, Sideways, High Volatility).
5. **Lack of Structural Execution Boundary:** Without automated static analysis (AST inspection), evaluation code could inadvertently import broker adapters or instantiate live order routines.

Stage 7 solves these gaps by introducing a deterministic, auditable, walk-forward evaluation engine with strict temporal isolation, structural AST dependency checks, friction sensitivity sweeps, and out-of-sample degradation metrics.

---

## 3. Scope

Stage 7 introduces the following components and capabilities:
1. **Experiment Manifests & Domain Model:** Immutable experiment configurations defining strategy identity, dataset version, date ranges, capital, and friction parameters.
2. **Temporal Partitioning & Chronological Guards:** Disjoint train, validation, and out-of-sample test splits ($t_{\text{train}} < t_{\text{val}} < t_{\text{test}}$) enforcing zero overlap and zero future data access.
3. **Walk-Forward Simulation Engine:** Expanding and rolling window walk-forward execution with deterministic step sizes and minimum observation threshold gates.
4. **Deterministic Evaluation Engine:** Evaluation pipeline integrating certified Stage 6 Indian transaction cost calculations (STT, GST, brokerage, exchange fees) and slippage models.
5. **Analytics & Robustness Suite:** Performance metrics (CAGR, Sharpe, Sortino, Max Drawdown, Drawdown Duration, Win Rate, Profit Factor, Turnover, Holding Period) with explicit guards against division-by-zero or undefined values.
6. **Sensitivity & Stress Sweep Module:** Multi-tier friction stress testing (+10%, +25%, +50% cost & 2x, 5x slippage) and local parameter neighborhood sweeps.
7. **Historical Market Regime Classifier:** Deterministic regime breakdown (Bull, Bear, Sideways, High/Low Volatility) computed using historical data only.
8. **Out-of-Sample Degradation & Evidence Classification:** Classification of research evidence into `VALIDATED`, `OOS_DEGRADED`, or `INSUFFICIENT_EVIDENCE`.
9. **Structural AST Isolation Test (AT-79):** Automated AST static inspection verifying zero imports of broker adapters, live SDKs, or order routing gateways in the evaluation package.
10. **Immutable Research Audit Trail:** Comprehensive JSON audit manifests recording SHA-256 dataset hashes, Git commit, parameter sets, and explicit methodological limitations.

---

## 4. Non-Goals

Stage 7 explicitly excludes:
- **Live Trading:** No real-money execution, live order routing, or production broker connectivity.
- **Autonomous Broker Execution:** No automated dispatch of signals to external brokers.
- **Autonomous AI Trading:** No AI model or LLM authority to place trades, modify risk limits, or deploy strategies.
- **Uncontrolled External Execution:** No dynamic execution webhooks or external order listeners.
- **Options-Chain Implementation:** Excluded unless explicitly authorized in a separate specification.
- **WebSocket / Live Tick Infrastructure:** Excluded unless explicitly authorized in a separate specification.
- **Modification of Stage 6 Controls:** Stage 6 replay determinism, pre-trade cash checks, risk gating, and paper trading isolation remain untouched and fully preserved.

---

## 5. Architectural Structure & Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                STAGE 7 ARCHITECTURE                                     │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│ 1. Experiment Definition & Manifest                                                     │
│    (Explicit parameters, dataset hashes, universe, capital, cost/slippage configs)      │
│                                           │                                             │
│                                           ▼                                             │
│ 2. Temporal Partitioning (Strict Chronological Guard)                                  │
│    TRAIN ────────────────────▶ VALIDATION ────────────────────▶ FINAL TEST (OOS)        │
│    (Disjoint intervals: t_train < t_val < t_test; zero look-ahead; boundary checks)     │
│                                           │                                             │
│                                           ▼                                             │
│ 3. Walk-Forward Simulation Engine                                                       │
│    (Expanding & rolling windows, anchored step sizes, min observation gates)            │
│                                           │                                             │
│                                           ▼                                             │
│ 4. Deterministic Evaluation Loop (Certified Stage 6 Infrastructure)                     │
│    - Deterministic Bar Replay with Look-Ahead Prevention                                │
│    - Certified Indian Transaction Cost Calculator (STT, GST, Exchange, Stamp Duty)      │
│    - Deterministic Slippage Model                                                       │
│    - Independent Pre-Trade Risk Gate & Solvency Verification                            │
│                                           │                                             │
│                                           ▼                                             │
│ 5. Analytics & Robustness Suite                                                         │
│    - Risk, Return & Trading Statistics (Safe undefined metric handling)                 │
│    - Sensitivity Analysis (+10%, +25%, +50% cost & slippage friction perturbations)    │
│    - Regime Classification (Bull, Bear, Sideways, High/Low Volatility)                  │
│    - Out-of-Sample Degradation Tracking (IS vs OOS delta)                               │
│                                           │                                             │
│                                           ▼                                             │
│ 6. Research Evidence Classification & Audit Trail                                       │
│    - Factual Evidence Status (INSUFFICIENT_EVIDENCE, OOS_DEGRADED, VALIDATED)           │
│    - Full JSON Manifest with SHA-256 Hashes, Git Commit, and Explicit Limitations       │
└─────────────────────────────────────────────────────────────────────────────────────────┘
                                           │
                                           │ STRICT ARCHITECTURAL FIREWALL
                                           ▼ (Verified structurally via AST + runtime)
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              FORBIDDEN BROKER DOMAIN                                    │
│  [Live Broker Adapters]  [Order Routing Gateways]  [Real-Money Brokerage Credentials]  │
│                   *** ZERO ACCESS — STRUCTURAL & RUNTIME LOCKOUT ***                     │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Component Boundaries

| Component Domain | Authority & Responsibility | Forbidden Capabilities |
|---|---|---|
| **Market Data** | Provides validated, checksummed OHLCV datasets | Cannot generate signals or execute trades |
| **Research / Strategy** | Computes signal inputs based on historical slice $\le t_{\text{sim}}$ | Cannot access future data ($> t_{\text{sim}}$) or broker APIs |
| **Deterministic Evaluation** | Runs backtests & walk-forward simulations | Cannot route orders to brokers or bypass risk checks |
| **Risk Engine** | Validates pre-trade solvency, position limits, and order sizes | Cannot be bypassed or overridden by evaluation logic |
| **Execution Simulation** | Simulates fills, statutory Indian costs, and slippage | Cannot connect to live exchange or real broker |
| **Paper Trading Engine** | Manages simulated real-time paper sessions (Stage 6) | Completely isolated from Stage 7 evaluation loops |
| **Broker Abstraction Layer** | Provides broker interface contracts (Stage 6) | Must NEVER be imported or instantiated in Stage 7 |
| **AI Assistance** | Explains metrics, summarizes reports, formats charts | Zero trade placement or strategy deployment authority |

---

## 7. Determinism & Reproducibility Requirements

Stage 7 requires 100% bit-for-bit reproducibility:
1. **Deterministic Inputs:** Identical experiment parameters + identical dataset (SHA-256 hash) + identical random seed = identical evaluation results.
2. **Deterministic Bar Processing:** Bar sequence iteration is strictly ordered by timestamp (`timestamp_asc`).
3. **Deterministic Output Artifacts:** Re-executing an experiment manifest produces identical metric values, trade sequences, and equity curves.
4. **Configuration Fingerprinting:** Every experiment generates a deterministic SHA-256 fingerprint of its configuration parameters.

---

## 8. No-Lookahead Guarantees

Look-ahead bias is strictly prevented:
1. **Temporal Bar Isolation:** At simulation time $t_{\text{sim}}$, the evaluation loop has access *only* to market data where $\text{timestamp} \le t_{\text{sim}}$.
2. **Feature Calculation Isolation:** Indicators and factors at time $t$ are calculated strictly using slice $[0, t]$.
3. **Signal & Fill Timing:** Signals generated at bar $t$ close are executed at bar $t+1$ open (or bar $t$ close if explicit market-on-close policy is configured), preventing intraday price leakage.
4. **Multi-Symbol Temporal Alignment:** Multi-symbol datasets are aligned synchronously by timestamp slice; no future bars of symbol B can be inspected while evaluating symbol A at time $t$.

---

## 9. Evaluation / Execution Isolation & Structural AST Test (AT-79)

### 9.1 Evaluation / Execution Firewall
The Stage 7 evaluation engine is strictly separated from external execution:
- Evaluation modules must **not** import any broker adapters (`services.paper_engine.adapters`).
- Evaluation modules must **not** instantiate broker SDK classes (Zerodha Kite, Upstox, IB, etc.).
- Evaluation modules must **not** accept live broker API keys, tokens, or credentials.
- Evaluation runs configured with `ExecutionEnvironment.LIVE` fail closed immediately at runtime with `PermissionError`.

### 9.2 Structural AST Inspection Test (AT-79)
AT-79 is implemented as a static Abstract Syntax Tree (AST) analysis test in pytest.
It parses all Python modules within `services/evaluation_engine/` and asserts that **zero imports** match any forbidden patterns:

| Prohibited Import Category | Explicit Blocked Module Patterns |
|---|---|
| **Broker Adapters & Credential Stores** | `services.paper_engine.adapters`<br>`services.paper_engine.adapters.base`<br>`services.paper_engine.adapters.upstox`<br>`services.paper_engine.adapters.zerodha`<br>`services.paper_engine.adapters.credentials` |
| **Live Broker SDKs** | `kiteconnect`, `upstox_client`, `interactive_brokers`, `ib_insync`, `alpaca_trade_api`, `smartapi`, `NorenApi` |
| **Order Execution Engines** | `services.execution_engine`, `services.paper_engine.session.PaperTradingEngine` |
| **Live Sockets & WebSockets** | `websockets`, `socket`, `aiohttp.ClientWebSocketResponse` |
| **Dynamic Import Reflection** | Calls to `__import__`, `importlib.import_module`, `eval`, `exec` targeting execution modules |

---

## 10. The 18 Architectural Invariants

| ID | Invariant Name | Formal Architectural Definition |
|---|---|---|
| **INV-01** | **Deterministic Experiment** | Same experiment config + same dataset hash + same seed = bit-for-bit identical results. |
| **INV-02** | **No Look-Ahead Bias** | Information at $t > t_{\text{sim}}$ cannot be accessed or influence decisions at simulation time $t$. |
| **INV-03** | **Temporal Isolation** | Train, validation, and test periods are strictly disjoint and chronological ($t_{\text{train}} < t_{\text{val}} < t_{\text{test}}$). |
| **INV-04** | **Final Test Isolation** | Final test partition data cannot be used for hyperparameter tuning or feature selection. |
| **INV-05** | **Dataset Identity** | Every evaluation explicitly records exact dataset identifier, timeframe, universe, and version. |
| **INV-06** | **Dataset Integrity** | Unexpected data modifications, missing OHLCV fields, or SHA-256 checksum drift fail closed immediately. |
| **INV-07** | **Cost Model Consistency** | Evaluation must use certified statutory Indian cost calculator (brokerage, STT, GST, stamp duty). |
| **INV-08** | **Slippage Model Consistency** | Evaluation must use certified slippage models; zero frictionless simulations are permitted. |
| **INV-09** | **Invalid Experiment Rejection** | Incomplete, contradictory, or unphysical experiment configurations fail closed before execution. |
| **INV-10** | **Metric Integrity** | Undefined metrics (e.g. zero trades, zero losing trades) must never return silent 0.0 values. |
| **INV-11** | **Reproducibility** | Any experiment result must be fully reproducible from its persisted audit manifest alone. |
| **INV-12** | **Auditability** | Complete execution metadata (Git commit, seed, config, dataset hash, limitations) is persisted immutably. |
| **INV-13** | **Secret Protection** | Zero credentials, API tokens, or secrets may appear in evaluation manifests, logs, or reports. |
| **INV-14** | **Stage 6 Preservation** | Certified Stage 6 replay determinism, cash solvency, risk gating, and paper trading pass 100%. |
| **INV-15** | **Live Trading Isolation** | Stage 7 evaluation modules have zero structural imports of broker adapters and zero live execution paths. |
| **INV-16** | **No Autonomous Selection** | Optimization or evaluation never autonomously selects or deploys a strategy into live trading. |
| **INV-17** | **Insufficient Evidence** | "Insufficient evidence" is a formal first-class research status, not an error or disguised pass. |
| **INV-18** | **Limitation Disclosure** | All material methodological assumptions, caveats, and data limitations are explicitly reported. |

---

## 11. Acceptance-Test Matrix (AT-01 to AT-90) & Proposed (AT-91 to AT-100)

### Area 1: Experiment Configuration & Boundary Validation (AT-01 – AT-06)
| ID | Requirement | Preconditions | Action | Expected Result | Failure Condition | Test Type | Component | Security / Integrity | Regression Req |
|---|---|---|---|---|---|---|---|---|---|
| **AT-01** | Valid Experiment Manifest Creation | Valid config & dataset | Instantiate manifest | Manifest created with unique ID | Raises error on valid input | Behavioral | Config | Manifest integrity | Pass Stage 6 |
| **AT-02** | Missing Strategy Identity Rejection | Config missing strategy ID | Instantiate manifest | Fails closed with `ValueError` | Accepts missing strategy ID | Behavioral | Config | Schema validation | Pass Stage 6 |
| **AT-03** | Missing Dataset Identity Rejection | Config missing dataset ID | Instantiate manifest | Fails closed with `ValueError` | Accepts missing dataset ID | Behavioral | Config | Schema validation | Pass Stage 6 |
| **AT-04** | Inverted Date Range Rejection | Start date $\ge$ end date | Instantiate manifest | Fails closed with `ValueError` | Accepts inverted dates | Behavioral | Config | Date validation | Pass Stage 6 |
| **AT-05** | Invalid Timeframe Rejection | Timeframe string invalid | Instantiate manifest | Fails closed with `ValueError` | Accepts invalid timeframe | Behavioral | Config | Schema validation | Pass Stage 6 |
| **AT-06** | Non-Positive Capital Rejection | Capital $\le 0$ | Instantiate manifest | Fails closed with `ValueError` | Accepts zero/negative capital | Behavioral | Config | Capital solvency | Pass Stage 6 |

### Area 2: Dataset Integrity, Checksums & Quarantine (AT-07 – AT-12)
| ID | Requirement | Preconditions | Action | Expected Result | Failure Condition | Test Type | Component | Security / Integrity | Regression Req |
|---|---|---|---|---|---|---|---|---|---|
| **AT-07** | Valid Dataset Loading | Registered dataset | Load dataset | Dataset loaded successfully | Fails on valid dataset | Behavioral | Data | Data loading | Pass Stage 6 |
| **AT-08** | SHA-256 Checksum Validation | Registered dataset | Verify hash | Checksum matches registry | Mismatch ignored | Behavioral | Data | Data immutability | Pass Stage 6 |
| **AT-09** | Checksum Mismatch Detection | Modified dataset file | Load dataset | Raises `DatasetIntegrityError` | Loads corrupted dataset | Behavioral | Data | Data tamper detection | Pass Stage 6 |
| **AT-10** | Missing Field Detection | Dataset missing Close | Load dataset | Raises `ValidationError` | Loads incomplete dataset | Behavioral | Data | Schema enforcement | Pass Stage 6 |
| **AT-11** | Dataset Discontinuity Flagging | Dataset with bar gaps | Load dataset | Flags missing bar warning | Ignores data gaps | Behavioral | Data | Data quality | Pass Stage 6 |
| **AT-12** | Quarantined Dataset Rejection | Dataset flagged quarantined | Load dataset | Raises `PermissionError` | Loads quarantined data | Behavioral | Data | Quarantine enforcement | Pass Stage 6 |

### Area 3: Temporal Partitioning & Overlap Prevention (AT-13 – AT-17)
| ID | Requirement | Preconditions | Action | Expected Result | Failure Condition | Test Type | Component | Security / Integrity | Regression Req |
|---|---|---|---|---|---|---|---|---|---|
| **AT-13** | Valid Disjoint Partitions | Valid date range | Create splits | Train < Val < Test created | Interval overlap permitted | Behavioral | Partition | Temporal isolation | Pass Stage 6 |
| **AT-14** | Train/Val Overlap Rejection | Overlapping dates | Create splits | Fails closed with `ValueError` | Accepts overlap | Behavioral | Partition | Data leakage prevention | Pass Stage 6 |
| **AT-15** | Val/Test Overlap Rejection | Overlapping dates | Create splits | Fails closed with `ValueError` | Accepts overlap | Behavioral | Partition | Data leakage prevention | Pass Stage 6 |
| **AT-16** | Train Extending into Test | Train end $>$ Test start | Create splits | Fails closed with `ValueError` | Accepts extension | Behavioral | Partition | Data leakage prevention | Pass Stage 6 |
| **AT-17** | Chronologically Inverted Splits | Test before Train | Create splits | Fails closed with `ValueError` | Accepts inverted splits | Behavioral | Partition | Temporal ordering | Pass Stage 6 |

### Area 4: Look-Ahead Bias Prevention (AT-18 – AT-21)
| ID | Requirement | Preconditions | Action | Expected Result | Failure Condition | Test Type | Component | Security / Integrity | Regression Req |
|---|---|---|---|---|---|---|---|---|---|
| **AT-18** | Future Bar Access Prohibition | Simulation at $t$ | Attempt read $t+1$ | Raises `LookAheadBiasError` | Returns future bar | Behavioral | Engine | No-lookahead guard | Pass Stage 6 |
| **AT-19** | Future Indicator Access Guard | Simulation at $t$ | Compute indicator | Uses data $\le t$ only | Inspects future slice | Behavioral | Engine | Indicator integrity | Pass Stage 6 |
| **AT-20** | Future State Access Guard | Simulation at $t$ | Query equity | Returns state at $t$ | Returns future state | Behavioral | Engine | State integrity | Pass Stage 6 |
| **AT-21** | Trade Outcome Leakage Guard | Signal generated $t$ | Check fill status | Fill processed $t+1$ | Signal sees future fill | Behavioral | Engine | Signal timing | Pass Stage 6 |

### Area 5: Parameter Selection & Leakage Detection (AT-22 – AT-25)
| ID | Requirement | Preconditions | Action | Expected Result | Failure Condition | Test Type | Component | Security / Integrity | Regression Req |
|---|---|---|---|---|---|---|---|---|---|
| **AT-22** | Fixed Parameter Run | Fixed params | Run evaluation | Parameters recorded fixed | Modifies parameters | Behavioral | Engine | Parameter tracking | Pass Stage 6 |
| **AT-23** | Train-Set Calibration | Training partition | Fit parameters | Parameters tagged trained | Fits on test data | Behavioral | Engine | Overfitting guard | Pass Stage 6 |
| **AT-24** | Val-Set Hyperparameter Selection | Validation partition | Select hyperparams | Tagged validated | Uses test data | Behavioral | Engine | Selection integrity | Pass Stage 6 |
| **AT-25** | Final-Test Tuning Rejection | Final test partition | Attempt tuning | Fails closed with `ValueError` | Allows tuning on test | Behavioral | Engine | OOS test isolation | Pass Stage 6 |

### Area 6: Walk-Forward Simulation (AT-26 – AT-30)
| ID | Requirement | Preconditions | Action | Expected Result | Failure Condition | Test Type | Component | Security / Integrity | Regression Req |
|---|---|---|---|---|---|---|---|---|---|
| **AT-26** | Expanding Window Execution | Valid config | Run walk-forward | Window expands correctly | Window bounds corrupt | Behavioral | Engine | Walk-forward logic | Pass Stage 6 |
| **AT-27** | Rolling Window Execution | Valid config | Run walk-forward | Window rolls deterministically | Step size drift | Behavioral | Engine | Walk-forward logic | Pass Stage 6 |
| **AT-28** | Sub-Minimum Window Rejection | Train window $<$ min | Run walk-forward | Fails closed with `ValueError` | Runs under-sized window | Behavioral | Engine | Sample size guard | Pass Stage 6 |
| **AT-29** | Invalid Step Size Rejection | Step size $\le 0$ | Run walk-forward | Fails closed with `ValueError` | Accepts non-positive step | Behavioral | Engine | Param validation | Pass Stage 6 |
| **AT-30** | Step $N+1$ Leakage Prevention | Step $N$ active | Attempt read $N+1$ | Access blocked | Reads step $N+1$ data | Behavioral | Engine | Window isolation | Pass Stage 6 |

### Area 7: Replay Determinism & Sensitivity (AT-31 – AT-33)
| ID | Requirement | Preconditions | Action | Expected Result | Failure Condition | Test Type | Component | Security / Integrity | Regression Req |
|---|---|---|---|---|---|---|---|---|---|
| **AT-31** | Re-execution Determinism | Same manifest | Run twice | Bit-for-bit identical outputs | Metric variance between runs | Behavioral | Engine | Determinism | Pass Stage 6 |
| **AT-32** | Data Perturbation Detection | Altered data bar | Run evaluation | Results change deterministically | Output unchanged | Behavioral | Engine | Sensitivity | Pass Stage 6 |
| **AT-33** | Strategy Version Drift Detection | Altered strategy version | Run evaluation | Manifest reflects new version | Version unchanged | Behavioral | Engine | Version tracking | Pass Stage 6 |

### Area 8: Statutory Costs & Slippage Frictions (AT-34 – AT-37)
| ID | Requirement | Preconditions | Action | Expected Result | Failure Condition | Test Type | Component | Security / Integrity | Regression Req |
|---|---|---|---|---|---|---|---|---|---|
| **AT-34** | Statutory Indian Cost Inclusion | Indian market config | Calculate costs | STT, GST, brokerage included | Omits statutory taxes | Behavioral | Friction | Cost completeness | Pass Stage 6 |
| **AT-35** | Brokerage Cost Sensitivity | Increase brokerage | Run evaluation | Net return decreases | Net return unchanged | Behavioral | Friction | Cost engine integrity | Pass Stage 6 |
| **AT-36** | Slippage Friction Sensitivity | Increase slippage | Run evaluation | Fill prices degrade net P&L | Friction ignored | Behavioral | Friction | Slippage model | Pass Stage 6 |
| **AT-37** | Stage 6 Cost Engine Equivalence | Same fill inputs | Compare costs | Matches `IndianCostCalculator` | Diverges from Stage 6 | Behavioral | Friction | Stage 6 consistency | Pass Stage 6 |

### Area 9: Return, Risk & Undefined Metric Integrity (AT-38 – AT-46)
| ID | Requirement | Preconditions | Action | Expected Result | Failure Condition | Test Type | Component | Security / Integrity | Regression Req |
|---|---|---|---|---|---|---|---|---|---|
| **AT-38** | Total Return Accuracy | Equity curve | Compute return | Matches $(\text{End}-\text{Start})/\text{Start}$ | Incorrect return | Behavioral | Analytics | Math accuracy | Pass Stage 6 |
| **AT-39** | CAGR Calculation Accuracy | Multi-year curve | Compute CAGR | Annualized return correct | Incorrect compounding | Behavioral | Analytics | Math accuracy | Pass Stage 6 |
| **AT-40** | Max Drawdown Accuracy | Equity curve | Compute MDD | Peak-to-trough matches exact | Incorrect MDD | Behavioral | Analytics | Math accuracy | Pass Stage 6 |
| **AT-41** | Annualized Volatility Accuracy | Daily returns | Compute vol | Returns StdDev $\times \sqrt{252}$ | Incorrect scaling | Behavioral | Analytics | Math accuracy | Pass Stage 6 |
| **AT-42** | Sharpe Ratio & Zero Vol Guard | Flat returns | Compute Sharpe | Returns `None`/`NaN`, no crash | Div-by-zero exception | Behavioral | Analytics | Zero-divisor safety | Pass Stage 6 |
| **AT-43** | Sortino Ratio Accuracy | Daily returns | Compute Sortino | Downside deviation correct | Uses upside volatility | Behavioral | Analytics | Math accuracy | Pass Stage 6 |
| **AT-44** | Zero Winning Trades Handling | 0 win trades | Compute Win Rate | Returns 0.0 safely | Exception or Div-by-zero | Behavioral | Analytics | Zero-divisor safety | Pass Stage 6 |
| **AT-45** | Zero Losing Trades Handling | 0 loss trades | Compute Profit Factor | Returns `inf`/`None` flag, not 0.0 | Returns 0.0 or crashes | Behavioral | Analytics | Metric integrity | Pass Stage 6 |
| **AT-46** | Empty Trade Set Integrity | 0 trades executed | Compute metrics | All stats `None` with diagnostic | Fake 0.0 metrics | Behavioral | Analytics | Undefined handling | Pass Stage 6 |

### Area 10: Trade Distribution & Holding Statistics (AT-47 – AT-52)
| ID | Requirement | Preconditions | Action | Expected Result | Failure Condition | Test Type | Component | Security / Integrity | Regression Req |
|---|---|---|---|---|---|---|---|---|---|
| **AT-47** | Total Trade & Direction Split | Fills executed | Count trades | Long/short split correct | Count mismatch | Behavioral | Analytics | Trade accounting | Pass Stage 6 |
| **AT-48** | Win/Loss & Avg P&L Stats | Fills executed | Compute P&L stats | Gross/net averages correct | P&L mismatch | Behavioral | Analytics | Trade accounting | Pass Stage 6 |
| **AT-49** | Profit Factor Guard | Trade P&L array | Compute PF | Gross gains / Gross losses | Incorrect ratio | Behavioral | Analytics | Trade accounting | Pass Stage 6 |
| **AT-50** | Consecutive Streak Stats | Trade P&L sequence | Count streaks | Max win/loss streaks correct | Incorrect streak count | Behavioral | Analytics | Trade accounting | Pass Stage 6 |
| **AT-51** | Portfolio Turnover Rate | Traded volume | Compute turnover | Total value / Avg equity | Incorrect turnover | Behavioral | Analytics | Math accuracy | Pass Stage 6 |
| **AT-52** | Exposure & Holding Period | Bar holdings | Compute exposure | Exposure % and avg bars hold | Incorrect holding time | Behavioral | Analytics | Math accuracy | Pass Stage 6 |

### Area 11: Drawdown Duration Tracking (AT-53)
| ID | Requirement | Preconditions | Action | Expected Result | Failure Condition | Test Type | Component | Security / Integrity | Regression Req |
|---|---|---|---|---|---|---|---|---|---|
| **AT-53** | Max Drawdown Duration | Equity curve | Compute duration | Max bars from peak to recovery | Incorrect duration | Behavioral | Analytics | Risk tracking | Pass Stage 6 |

### Area 12: Sensitivity Analysis & Friction Sweeps (AT-54 – AT-58)
| ID | Requirement | Preconditions | Action | Expected Result | Failure Condition | Test Type | Component | Security / Integrity | Regression Req |
|---|---|---|---|---|---|---|---|---|---|
| **AT-54** | Base Friction Benchmark | Base config | Run benchmark | Establishes baseline metrics | Fails benchmark | Behavioral | Robustness | Friction baseline | Pass Stage 6 |
| **AT-55** | Multi-Tier Cost Stress (+10%, +25%, +50%) | Cost tiers | Run stress sweep | Monotonic P&L degradation | Non-monotonic return | Behavioral | Robustness | Friction stress | Pass Stage 6 |
| **AT-56** | Slippage Stress Testing (2x, 5x) | Slippage multiplier | Run stress sweep | Degradation curve generated | Slippage ignored | Behavioral | Robustness | Friction stress | Pass Stage 6 |
| **AT-57** | Parameter Neighborhood Sweep | Parameter delta | Run sweep | Local parameter surface mapped | Fails parameter sweep | Behavioral | Robustness | Sensitivity sweep | Pass Stage 6 |
| **AT-58** | No Autonomous Strategy Selection | Sweep output | Check deployment | Zero auto-selection/promotion | Auto-selects strategy | Behavioral | Robustness | No auto-deployment | Pass Stage 6 |

### Area 13: Market Regime Classification (AT-59 – AT-61)
| ID | Requirement | Preconditions | Action | Expected Result | Failure Condition | Test Type | Component | Security / Integrity | Regression Req |
|---|---|---|---|---|---|---|---|---|---|
| **AT-59** | Deterministic Regime Breakdown | Market data | Classify regimes | Regimes (Bull/Bear/etc) tagged | Non-deterministic tags | Behavioral | Regimes | Regime tagging | Pass Stage 6 |
| **AT-60** | Regime No-Lookahead Guard | Simulation at $t$ | Classify regime | Uses data $\le t$ only | Uses future returns | Behavioral | Regimes | No-lookahead guard | Pass Stage 6 |
| **AT-61** | Low Observation Regime Guard | Regime $<20$ bars | Classify regime | Flagged `INSUFFICIENT_EVIDENCE` | Unflagged small sample | Behavioral | Regimes | Sample size guard | Pass Stage 6 |

### Area 14: Out-of-Sample Degradation Tracking (AT-62 – AT-66)
| ID | Requirement | Preconditions | Action | Expected Result | Failure Condition | Test Type | Component | Security / Integrity | Regression Req |
|---|---|---|---|---|---|---|---|---|---|
| **AT-62** | In-Sample Performance Record | IS partition | Record metrics | IS metrics persisted with tag | Missing partition tag | Behavioral | Evaluation | OOS tracking | Pass Stage 6 |
| **AT-63** | Out-of-Sample Performance Record | OOS partition | Record metrics | OOS metrics persisted with tag | Missing partition tag | Behavioral | Evaluation | OOS tracking | Pass Stage 6 |
| **AT-64** | Walk-Forward Aggregated Record | Walk-forward run | Compile OOS curve | Stitched OOS metrics compiled | In-sample data mixed in | Behavioral | Evaluation | OOS tracking | Pass Stage 6 |
| **AT-65** | OOS Degradation Ratio | IS & OOS metrics | Compute ratio | Ratio $\text{Sharpe}_{\text{OOS}}/\text{Sharpe}_{\text{IS}}$ | Incorrect ratio calculation | Behavioral | Evaluation | Robustness metric | Pass Stage 6 |
| **AT-66** | Insufficient OOS Trades Flag | OOS trades $<30$ | Evaluate status | Status = `INSUFFICIENT_EVIDENCE` | Marked `VALIDATED` | Behavioral | Evaluation | Evidence classification | Pass Stage 6 |

### Area 15: Audit Trail & Provenance Manifests (AT-67 – AT-76)
| ID | Requirement | Preconditions | Action | Expected Result | Failure Condition | Test Type | Component | Security / Integrity | Regression Req |
|---|---|---|---|---|---|---|---|---|---|
| **AT-67** | Unique Experiment ID Persistence | Completed run | Inspect manifest | Unique Experiment ID present | Missing Experiment ID | Behavioral | Audit | Audit provenance | Pass Stage 6 |
| **AT-68** | Dataset Identity Persistence | Completed run | Inspect manifest | Dataset name & universe present | Missing dataset info | Behavioral | Audit | Audit provenance | Pass Stage 6 |
| **AT-69** | Dataset SHA-256 Hash Persistence | Completed run | Inspect manifest | SHA-256 hash present | Missing dataset hash | Behavioral | Audit | Audit provenance | Pass Stage 6 |
| **AT-70** | Strategy & Version Persistence | Completed run | Inspect manifest | Strategy class & version recorded | Missing strategy identity | Behavioral | Audit | Audit provenance | Pass Stage 6 |
| **AT-71** | Complete Parameter Set Persistence | Completed run | Inspect manifest | All input parameters recorded | Parameter truncation | Behavioral | Audit | Audit provenance | Pass Stage 6 |
| **AT-72** | Cost & Slippage Config Persistence | Completed run | Inspect manifest | Fee schedules & slippage recorded | Missing friction config | Behavioral | Audit | Audit provenance | Pass Stage 6 |
| **AT-73** | Git Commit Hash Persistence | Completed run | Inspect manifest | Exact Git commit hash present | Missing commit hash | Behavioral | Audit | Audit provenance | Pass Stage 6 |
| **AT-74** | Methodology Metadata Persistence | Completed run | Inspect manifest | Dates, step sizes, seeds present | Missing methodology info | Behavioral | Audit | Audit provenance | Pass Stage 6 |
| **AT-75** | Research Diagnostics Persistence | Completed run | Inspect manifest | Non-fatal warnings recorded | Omitted data warnings | Behavioral | Audit | Audit provenance | Pass Stage 6 |
| **AT-76** | Methodological Limitations Display | Completed run | Inspect manifest | Limitations section populated | Missing limitations block | Behavioral | Audit | Audit provenance | Pass Stage 6 |

### Area 16: Credential & Secret Protection (AT-77 – AT-78)
| ID | Requirement | Preconditions | Action | Expected Result | Failure Condition | Test Type | Component | Security / Integrity | Regression Req |
|---|---|---|---|---|---|---|---|---|---|
| **AT-77** | API Secret Omission from Manifests | Run with env secret | Generate manifest | Scan JSON: Zero secrets present | Secret leaked into manifest | Behavioral | Security | Secret protection | Pass Stage 6 |
| **AT-78** | Credential Masking in Reports | Run evaluation | Generate report | Scan Markdown: Zero credentials | Credential leaked in log | Behavioral | Security | Secret protection | Pass Stage 6 |

### Area 17: Structural & Behavioral Live Isolation & Regression (AT-79 – AT-85)
| ID | Requirement | Preconditions | Action | Expected Result | Failure Condition | Test Type | Component | Security / Integrity | Regression Req |
|---|---|---|---|---|---|---|---|---|---|
| **AT-79** | **Structural AST & Behavioral Lockout** | Evaluation module | AST scan & Live run | **AST:** 0 broker imports.<br>**Runtime:** `ExecutionEnvironment.LIVE` raises `PermissionError`. | Broker import found or Live execution allowed | **Structural (AST) + Behavioral** | Isolation | Execution isolation | Pass Stage 6 |
| **AT-80** | Risk Gate Bypass Prevention | Evaluation trade | Attempt risk bypass | Fails closed; risk check enforced | Risk check bypassed | Behavioral | Safety | Risk engine enforcement | Pass Stage 6 |
| **AT-81** | Stage 6 Paper Session Regression | Stage 6 suite | Run `pytest` | Paper trading tests pass (12/12) | Stage 6 test failure | Behavioral | Regression | Stage 6 preservation | Pass Stage 6 |
| **AT-82** | Stage 6 Replay No-Lookahead Regression | Stage 6 suite | Run `pytest` | Replay look-ahead tests pass | Stage 6 test failure | Behavioral | Regression | Stage 6 preservation | Pass Stage 6 |
| **AT-83** | Stage 6 Replay Determinism Regression | Stage 6 suite | Run `pytest` | Concurrent replay tests pass | Stage 6 test failure | Behavioral | Regression | Stage 6 preservation | Pass Stage 6 |
| **AT-84** | Stage 6 Pre-Trade Cash Solvency Regression | Stage 6 suite | Run `pytest` | Cash solvency tests pass | Stage 6 test failure | Behavioral | Regression | Stage 6 preservation | Pass Stage 6 |
| **AT-85** | Stage 5 Certified Strategy Regression | Stage 5 suite | Run `pytest` | Strategy & indicator tests pass (127/127) | Stage 5 test failure | Behavioral | Regression | Stage 5 preservation | Pass Stage 6 |

### Area 18: Research Reporting & Reproducibility (AT-86 – AT-90)
| ID | Requirement | Preconditions | Action | Expected Result | Failure Condition | Test Type | Component | Security / Integrity | Regression Req |
|---|---|---|---|---|---|---|---|---|---|
| **AT-86** | Research Report Markdown Generation | Completed run | Render report | Valid Markdown report created | Report rendering crash | Behavioral | Reporting | Documentation | Pass Stage 6 |
| **AT-87** | Invalid Experiment Diagnostic Report | Invalid manifest | Render report | Explicit error report; no fake stats | Fake stats rendered | Behavioral | Reporting | Diagnostic clarity | Pass Stage 6 |
| **AT-88** | "Insufficient Evidence" Report Tag | Low trade count | Render report | Prominently displays `INSUFFICIENT_EVIDENCE` | Marked valid/successful | Behavioral | Reporting | Evidence reporting | Pass Stage 6 |
| **AT-89** | Methodological Limitations Display | Completed run | Render report | Disclaimer & limitations block displayed | Limitations hidden | Behavioral | Reporting | Transparency | Pass Stage 6 |
| **AT-90** | Bit-for-Bit Manifest Reproduction | Audit manifest | Re-run manifest | Reproduces exact original result | Result divergence | Behavioral | Reporting | Reproducibility | Pass Stage 6 |

---

### PROPOSED ADDITIONAL TESTS (AT-91 – AT-100) — STATUS: PROPOSED / NOT YET APPROVED

| ID | Proposed Acceptance Test Title | Test Type | Intended Verification & Safety Objective | Status |
|---|---|:---:|---|:---:|
| **AT-91** | **Dependency Graph Static Isolation** | Structural (AST) | Verify module imports in `services/evaluation_engine/` contain zero cycles and zero backward imports to UI/API layers | PROPOSED |
| **AT-92** | **Credential Non-Propagation Gate** | Structural (AST) | Verify evaluation context constructors explicitly reject passing dictionary keys containing `KEY`, `SECRET`, or `TOKEN` | PROPOSED |
| **AT-93** | **Dataset SHA-256 Immutability Gate** | Behavioral | Verify dataset modification during an active evaluation run raises `DatasetIntegrityError` and aborts evaluation | PROPOSED |
| **AT-94** | **Configuration Fingerprint Drift Rejection** | Behavioral | Verify altering any parameter in a saved manifest changes its SHA-256 fingerprint deterministically | PROPOSED |
| **AT-95** | **Rerun Equivalence Bit-for-Bit Verification** | Behavioral | Run 10 parallel evaluation workers on identical manifests and verify identical SHA-256 output hashes | PROPOSED |
| **AT-96** | **Strict Historical Order Sequence Enforcement** | Behavioral | Verify bar processing timestamps in evaluation are strictly monotonic ($t_k < t_{k+1}$) with zero time-travel | PROPOSED |
| **AT-97** | **Cross-Symbol Temporal Isolation** | Behavioral | Verify evaluating Multi-Symbol asset A at $t$ cannot inspect bar $t+1$ of asset B | PROPOSED |
| **AT-98** | **Failure Atomicity & Partial Output Rollback** | Behavioral | Verification that an unhandled evaluation exception cleans up partial files and leaves no corrupt state | PROPOSED |
| **AT-99** | **Paper/Live Execution Barrier Authorization Lockout** | Structural + Behavioral | Verify evaluation context cannot acquire paper-trading session ID or broker execution handle | PROPOSED |
| **AT-100** | **External Execution Emergency Kill Boundary** | Structural | Verify that calling any mock or real order placement method from within an evaluation loop triggers an immediate `KillSwitchException` | PROPOSED |

---

## 12. Stage 6 Regression Requirement

Stage 7 requires **zero regression** of certified Stage 5 and Stage 6 functionality:
- All 192 certified tests must continue passing ($100\%$ pass rate).
- No baseline tests may be deleted, commented out, or weakened.
- Verification command: `pytest -q`

---

## 13. Test Design Requirements

Stage 7 tests are split into two mandatory categories:
1. **Behavioral Tests:** Test functional logic (e.g. CAGR calculation, walk-forward window splitting, friction degradation, drawdown tracking).
2. **Structural / Security Static Tests (AST):** Inspect Python Abstract Syntax Trees to verify architectural boundaries (e.g. AT-79 static AST import prohibition of broker adapters and SDKs).

A passing runtime test alone is **insufficient** for an architectural safety boundary. Structural AST verification is required.

---

## 14. Failure Policy

The Stage 7 system operates under a **Strict Fail-Closed Policy**:
- Invalid experiment configuration $\rightarrow$ Abort immediately with `ValueError`.
- Missing or invalid dataset / SHA-256 mismatch $\rightarrow$ Abort immediately with `DatasetIntegrityError`.
- Look-ahead access attempt $\rightarrow$ Abort immediately with `LookAheadBiasError`.
- Import of prohibited broker module $\rightarrow$ Abort build/test with `AssertionError`.
- Live environment execution configuration $\rightarrow$ Abort immediately with `PermissionError`.
- Missing required audit metadata $\rightarrow$ Abort manifest generation.

*No failure condition may ever be swallowed, ignored, or silently fallback to a default value.*

---

## 15. AI Authority Boundary

AI assistance within Algo Lab is strictly constrained:
- **Permitted AI Actions:** Summarizing backtest performance, explaining metrics (Sharpe, Drawdown), comparing experiment manifests, generating markdown research reports.
- **Forbidden AI Actions:** Autonomously placing trades, modifying risk rules, overriding evaluation logic, acquiring broker execution credentials, or promoting strategies to live execution.

---

## 16. UI / API Requirements

If Stage 7 evaluation endpoints are exposed via API:
- Endpoint: `POST /api/v1/evaluation/experiments`
- Request Schema: Validated `ExperimentManifestSchema` (rejecting unvalidated fields).
- Authorization: Requires authenticated session.
- Idempotency: Duplicate experiment submission with identical SHA-256 fingerprint returns existing result.
- Error Behavior: Standard JSON error response with explicit failure diagnostics.

---

## 17. Implementation Plan (Post-Approval Only)

Upon receiving explicit human approval, implementation will proceed through the following phased steps:

### Phase 1: Isolated Branch Setup
1. Create isolated working branch: `git checkout -b feature/stage7-evaluation` from baseline `2c09e57`.
2. Confirm baseline test suite passes: `pytest -q` (192/192 passed).

### Phase 2: Domain Model & Manifest Foundation
1. Implement `services/evaluation_engine/manifest.py` (Experiment manifest, parameters, friction configs).
2. Implement `services/evaluation_engine/partitioning.py` (Disjoint train/val/test splits, chronological guards).

### Phase 3: Walk-Forward & Evaluation Core Engine
1. Implement `services/evaluation_engine/walk_forward.py` (Expanding/rolling walk-forward simulation).
2. Implement `services/evaluation_engine/engine.py` (Deterministic evaluation loop integrating Stage 6 cost & slippage models).

### Phase 4: Analytics, Regimes & Sensitivity Module
1. Implement `services/evaluation_engine/analytics.py` (Risk, return, drawdown, and safe undefined metric calculations).
2. Implement `services/evaluation_engine/sensitivity.py` (Multi-tier friction stress sweeps +10%, +25%, +50% and 2x, 5x slippage).
3. Implement `services/evaluation_engine/regimes.py` (Historical regime classification).

### Phase 5: Structural AST Isolation Test (AT-79) & Test Suite
1. Implement `tests/unit/test_stage7_structural_isolation.py` (AT-79 static AST import scanner).
2. Implement `tests/unit/test_stage7_acceptance_matrix.py` (AT-01 through AT-90 behavioral tests).

### Phase 6: Verification & Certification Gate
1. Run full Stage 6 regression: `pytest -q` (192/192 passed).
2. Run complete Stage 7 suite: minimum 282 total tests passing.
3. Verify clean git status.
4. Report results for human review before tagging `stage7-verified`.

---

## 18. STOP GATE DECLARATION

```
===============================================================================
                    STAGE 7 SPECIFICATION READY
===============================================================================
Baseline Commit:    2c09e57765d39bb018f212f8844504fcb7fc215e
Baseline Tag:       stage6-verified (192/192 tests passing)
Implementation:     NOT STARTED / NOT APPROVED
Code Changes:       NONE (0 production files modified)
Specification:      DRAFT (algo_lab_stage7_specification.md)
Working Tree:       CLEAN
Approval Required:  YES — WAITING FOR EXPLICIT HUMAN APPROVAL
===============================================================================
```

**Next Action:** Awaiting explicit human approval to proceed with Phase 1 implementation.
