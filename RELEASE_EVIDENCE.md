# Algo Lab Release Evidence Matrix

**Repository**: `https://github.com/vijaykumarjogi266-star/algopro`  
**Base Reviewed Commit**: `57c34603506ecf9c28666886cee6bb9027085c29`  
**Branch**: `feature/remediation-v2-plan`  

---

## Finding → Implementation → Regression Test → Result Matrix

| Finding ID | Requirement Description | Implementing File(s) | Regression Test(s) | Result | Batch |
|---|---|---|---|:---:|:---:|
| **A01** | Missing/default dataset produces no generated history | `services/backtest-engine/service.py` | `tests/unit/test_dataset_contract_enforcement.py::test_a01_missing_dataset_produces_no_generated_history` | **PASS** | Batch A |
| **A02** | Production path cannot call synthetic helpers | `services/backtest-engine/service.py` | `tests/unit/test_dataset_contract_enforcement.py::test_a02_production_path_blocks_synthetic_helpers` | **PASS** | Batch A |
| **A03** | Explicit registered fixture succeeds | `services/backtest-engine/service.py` | `tests/unit/test_dataset_contract_enforcement.py::test_a03_explicit_registered_fixture_succeeds` | **PASS** | Batch A |
| **A04** | Changed checksum/data for same version rejects | `services/market-data/registry.py` | `tests/unit/test_dataset_contract_enforcement.py::test_a04_dataset_version_immutable_on_conflict` | **PASS** | Batch A |
| **A05** | Identical registration is idempotent | `services/market-data/registry.py` | `tests/unit/test_dataset_contract_enforcement.py::test_a05_identical_registration_is_idempotent` | **PASS** | Batch A |
| **A06** | Conflicting registration returns 409 conflict | `apps/api/routes/datasets.py` | `tests/integration/test_data_api.py::test_a06_conflicting_dataset_registration_returns_conflict` | **PASS** | Batch A |
| **A07** | Experiment replay remains pinned to original version | `services/backtest-engine/service.py` | `tests/unit/test_dataset_contract_enforcement.py::test_a07_replay_pinned_to_exact_version` | **PASS** | Batch A |
| **A08** | Incompatible quality/timeframe/OHLCV/symbols fails before fill | `services/backtest-engine/service.py` | `tests/unit/test_dataset_contract_enforcement.py::test_a08_contract_violations_fail_before_fills` | **PASS** | Batch A |
| **B01** | Unaffordable BUY leaves every portfolio field unchanged | `services/paper-engine/session.py` | `tests/unit/test_fill_ledger_accounting.py::test_b01_unaffordable_buy_leaves_every_portfolio_field_unchanged` | **PASS** | Batch B |
| **B02** | Rejected BUY then valid BUY increments counters exactly once | `services/paper-engine/session.py` | `tests/unit/test_fill_ledger_accounting.py::test_b02_rejected_buy_then_valid_buy_increments_counters_exactly_once` | **PASS** | Batch B |
| **B03** | Rejected fill remains unchanged after database reload | `services/paper-engine/session.py` | `tests/unit/test_fill_ledger_accounting.py::test_b03_rejected_fill_remains_unchanged_after_database_reload` | **PASS** | Batch B |
| **B04** | Buy 5, sell 6 rejects with no phantom proceeds | `services/backtest-engine/execution_lifecycle.py` | `tests/unit/test_fill_ledger_accounting.py::test_b04_buy_5_sell_6_rejects_with_no_phantom_proceeds` | **PASS** | Batch B |
| **B05** | Buy 5, sell 3, then sell 3 rejects second oversell | `services/backtest-engine/execution_lifecycle.py` | `tests/unit/test_fill_ledger_accounting.py::test_b05_buy_5_sell_3_then_sell_3_rejects_second_oversell` | **PASS** | Batch B |
| **B06** | Direct portfolio oversell is rejected defensively | `services/paper-engine/session.py` | `tests/unit/test_fill_ledger_accounting.py::test_b06_direct_portfolio_oversell_is_rejected_defensively` | **PASS** | Batch B |
| **B07** | Initial cash 10,000; buy 10 at 100.05 with fee 1: cash = 8,998.50 | `services/paper-engine/session.py` | `tests/unit/test_fill_ledger_accounting.py::test_b07_initial_cash_10000_buy_10_at_100_05_with_fee_1` | **PASS** | Batch B |
| **B08** | Sell those 10 at 109.95 with fee 1: final cash 10,097.00; net PnL 97.00 | `services/paper-engine/session.py` | `tests/unit/test_fill_ledger_accounting.py::test_b08_sell_those_10_at_109_95_with_fee_1_final_cash_and_pnl` | **PASS** | Batch B |
| **B09** | Double deduction of slippage fails reconciliation | `services/execution_gateway/reconciliation_engine.py` | `tests/unit/test_fill_ledger_accounting.py::test_b09_double_deduction_of_slippage_fails_reconciliation` | **PASS** | Batch B |
| **B10** | Real two-session fills/fees/carry positions reconcile | `services/execution_gateway/reconciliation_engine.py` | `tests/unit/test_fill_ledger_accounting.py::test_b10_real_two_session_fills_fees_carry_positions_reconcile` | **PASS** | Batch B |
| **B11** | NaN/Inf cash, price, quantity, equity or fees reject | `services/paper-engine/session.py`, `services/execution_gateway/` | `tests/unit/test_fill_ledger_accounting.py::test_b11_nan_inf_cash_price_quantity_equity_or_fees_reject` | **PASS** | Batch B |
| **B12** | Reported equity inconsistent with assets/cash rejects | `services/paper-engine/session.py`, `services/execution_gateway/` | `tests/unit/test_fill_ledger_accounting.py::test_b12_reported_equity_inconsistent_with_assets_cash_rejects` | **PASS** | Batch B |
| **C01** | Opposite strategy decisions on identical bars produce different orders | `quant/strategies/registry.py`, `run_live_paper_daemon.py` | `tests/unit/test_strategy_dispatch_provenance.py::test_c01_opposite_strategy_decisions_on_identical_bars_produce_different_orders` | **PASS** | Batch C |
| **C02** | Unknown strategy yields no entry | `quant/strategies/registry.py`, `run_live_paper_daemon.py` | `tests/unit/test_strategy_dispatch_provenance.py::test_c02_unknown_strategy_yields_no_entry` | **PASS** | Batch C |
| **C03** | Stop/target parameters change submitted and persisted protection exactly | `quant/strategies/registry.py`, `run_live_paper_daemon.py` | `tests/unit/test_strategy_dispatch_provenance.py::test_c03_stop_target_parameters_change_submitted_and_persisted_protection_exactly` | **PASS** | Batch C |
| **C04** | Order/fill evidence records strategy/version/decision/data metadata before fill | `services/backtest-engine/execution_lifecycle.py`, `services/paper-engine/` | `tests/unit/test_strategy_dispatch_provenance.py::test_c04_order_fill_evidence_records_strategy_version_decision_data_metadata_before_fill` | **PASS** | Batch C |
| **C05** | Buy-and-hold allocation is explicit and identical across execution paths | `quant/strategies/buy_and_hold.py`, `services/backtest-engine/service.py` | `tests/unit/test_strategy_dispatch_provenance.py::test_c05_buy_and_hold_allocation_is_explicit_and_identical_across_paths` | **PASS** | Batch C |
| **C06** | Invalid parameter types/ranges fail closed before dispatch | `quant/strategies/registry.py`, `run_live_paper_daemon.py` | `tests/unit/test_strategy_dispatch_provenance.py::test_c06_invalid_parameter_types_and_ranges_fail_closed_before_dispatch` | **PASS** | Batch C |
| **C07** | Upstream risk limits override strategy intent without AI/news bypass | `run_live_paper_daemon.py`, `services/risk-engine/` | `tests/unit/test_strategy_dispatch_provenance.py::test_c07_upstream_risk_limits_override_strategy_intent_without_ai_bypass` | **PASS** | Batch C |
| **D01** | 5-minute fixture with skipped intervals persists exact timestamps | `services/backtest-engine/service.py` | `tests/unit/test_batch_d_accurate_persistence.py::test_d01_five_minute_fixture_with_skipped_intervals_persists_exact_timestamps` | **PASS** | Batch D |
| **D02** | Trade timestamps differ correctly from experiment boundaries | `services/backtest-engine/service.py` | `tests/unit/test_batch_d_accurate_persistence.py::test_d02_trade_timestamps_differ_correctly_from_experiment_boundaries` | **PASS** | Batch D |
| **D03** | Held-position curve shows positive position value and actual cash | `services/backtest-engine/service.py` | `tests/unit/test_batch_d_accurate_persistence.py::test_d03_held_position_curve_shows_positive_position_value_and_actual_cash` | **PASS** | Batch D |
| **D04** | Equity components reconcile at every point (equity == cash + pos_val) | `services/backtest-engine/service.py` | `tests/unit/test_batch_d_accurate_persistence.py::test_d04_equity_components_reconcile_at_every_point` | **PASS** | Batch D |
| **D05** | Staggered symbols never use future/index-shifted prices | `services/backtest-engine/service.py` | `tests/unit/test_batch_d_accurate_persistence.py::test_d05_staggered_symbols_never_use_future_or_index_shifted_prices` | **PASS** | Batch D |
| **D06** | Pending open exit occurs at next valid bar open | `services/backtest-engine/service.py` | `tests/unit/test_batch_d_accurate_persistence.py::test_d06_pending_open_exit_occurs_at_next_valid_bar_open` | **PASS** | Batch D |
| **D07** | Unfillable open orders expire/cancel according to policy | `services/backtest-engine/service.py` | `tests/unit/test_batch_d_accurate_persistence.py::test_d07_unfillable_open_orders_expire_or_cancel_according_to_policy` | **PASS** | Batch D |
| **E01** | Weekend/holiday timestamps reject order submission | `services/paper-engine/session.py`, `services/market-data/calendar.py` | `tests/unit/test_batch_e_session_cutoff.py::test_e01_weekend_or_holiday_timestamps_reject_order_submission` | **PASS** | Batch E |
| **E02** | Timestamps outside market hours (09:15 - 15:30 IST) reject | `services/paper-engine/session.py`, `services/market-data/calendar.py` | `tests/unit/test_batch_e_session_cutoff.py::test_e02_timestamps_outside_market_hours_reject` | **PASS** | Batch E |
| **E03** | Stale quotes exceeding max age (>900s) or future quotes reject | `services/paper-engine/session.py`, `run_live_paper_daemon.py` | `tests/unit/test_batch_e_session_cutoff.py::test_e03_stale_and_future_quotes_reject` | **PASS** | Batch E |
| **E04** | Zero, negative, or NaN prices reject before execution | `services/paper-engine/session.py`, `services/backtest-engine/execution_lifecycle.py` | `tests/unit/test_batch_e_session_cutoff.py::test_e04_zero_negative_or_nan_prices_reject_before_execution` | **PASS** | Batch E |
| **E05** | Unresolved exit state marks position quarantine until verified recovery | `services/paper-engine/session.py`, `run_live_paper_daemon.py` | `tests/unit/test_batch_e_session_cutoff.py::test_e05_unresolved_exit_marks_quarantine_until_verified_recovery` | **PASS** | Batch E |
| **E06** | Auto-square-off triggers strictly at session cutoff (15:15 IST) | `run_live_paper_daemon.py` | `tests/unit/test_batch_e_session_cutoff.py::test_e06_auto_square_off_triggers_strictly_at_1515_ist` | **PASS** | Batch E |
| **E07** | Forced exit failure transitions session to EMERGENCY_HALT | `run_live_paper_daemon.py`, `services/paper-engine/session.py` | `tests/unit/test_batch_e_session_cutoff.py::test_e07_forced_exit_failure_transitions_to_emergency_halt` | **PASS** | Batch E |
| **E08** | Reconnect during closed session keeps trading halted | `run_live_paper_daemon.py`, `services/paper-engine/session.py` | `tests/unit/test_batch_e_session_cutoff.py::test_e08_reconnect_during_closed_session_keeps_trading_halted` | **PASS** | Batch E |
| **F01** | Production mode rejects insecure defaults, weak keys, and wildcard CORS | `apps/api/core/config.py` | `tests/unit/test_batch_f_config_and_breaker.py::test_f01_production_mode_rejects_insecure_defaults_weak_keys_and_wildcard_cors` | **PASS** | Batch F |
| **F02** | Validated configuration succeeds under production environment | `apps/api/core/config.py` | `tests/unit/test_batch_f_config_and_breaker.py::test_f02_validated_configuration_succeeds_under_production_environment` | **PASS** | Batch F |
| **F03** | Circuit breaker trips into halt and persists signed state | `services/execution_gateway/circuit_breaker.py` | `tests/unit/test_batch_f_config_and_breaker.py::test_f03_circuit_breaker_trips_into_halt_on_critical_condition` | **PASS** | Batch F |
| **F04** | Restart without state file preserves halt when unverified | `services/execution_gateway/circuit_breaker.py` | `tests/unit/test_batch_f_config_and_breaker.py::test_f04_restart_without_state_file_preserves_halt_status_when_unverified` | **PASS** | Batch F |
| **F05** | Tampered or invalid HMAC on state file triggers fail-closed halt | `services/execution_gateway/circuit_breaker.py` | `tests/unit/test_batch_f_config_and_breaker.py::test_f05_tampered_or_invalid_hmac_on_state_file_triggers_halt` | **PASS** | Batch F |
| **F06** | Replay of stale NORMAL state file is rejected by timestamp/sequence | `services/execution_gateway/circuit_breaker.py` | `tests/unit/test_batch_f_config_and_breaker.py::test_f06_replay_of_stale_normal_state_file_is_rejected_by_timestamp_sequence` | **PASS** | Batch F |
| **F07** | Admin rearm with valid secret clears halt | `services/execution_gateway/circuit_breaker.py` | `tests/unit/test_batch_f_config_and_breaker.py::test_f07_admin_rearm_with_valid_secret_clears_halt` | **PASS** | Batch F |
| **F08** | Admin rearm with invalid credentials preserves halt | `services/execution_gateway/circuit_breaker.py` | `tests/unit/test_batch_f_config_and_breaker.py::test_f08_admin_rearm_with_invalid_credentials_preserves_halt` | **PASS** | Batch F |
| **F09** | Recovery verifies clean ledger state before allowing order flow | `run_live_paper_daemon.py`, `services/execution_gateway/circuit_breaker.py` | `tests/unit/test_batch_f_config_and_breaker.py::test_f09_recovery_verifies_clean_ledger_state_before_allowing_order_flow` | **PASS** | Batch F |
| **G01** | Offline fixture separation blocks network access during offline evaluation | `services/market-intelligence/collector_service.py` | `tests/unit/test_news_fundamental_safety.py::test_g01_offline_fixture_separation_blocks_network` | **PASS** | Batch G |
| **G02** | Explicit non-silent fallback discipline (DataUnavailableError raised, no synthetic fallback) | `services/market-intelligence/collector_service.py` | `tests/unit/test_news_fundamental_safety.py::test_g02_explicit_non_silent_fallback_discipline` | **PASS** | Batch G |
| **G03** | External provider response sanitization (strip HTML, prompt injection patterns) | `services/market-intelligence/collector_service.py` | `tests/unit/test_news_fundamental_safety.py::test_g03_external_provider_response_sanitization` | **PASS** | Batch G |
| **G04** | Finite and valid fundamental ratios validation in contract | `services/market-intelligence/news_fundamental_contracts.py` | `tests/unit/test_news_fundamental_safety.py::test_g04_finite_and_valid_fundamental_ratios` | **PASS** | Batch G |
| **G05** | Division-by-zero and non-finite ratio protection (safe Piotroski F-score) | `services/market-intelligence/fundamental_engine.py` | `tests/unit/test_news_fundamental_safety.py::test_g05_division_by_zero_and_infinite_ratio_protection` | **PASS** | Batch G |
| **G06** | Upstream risk limits strictly override AI sizing recommendations | `services/market-intelligence/stock_decision_engine.py` | `tests/unit/test_news_fundamental_safety.py::test_g06_upstream_risk_limits_override_ai_sizing` | **PASS** | Batch G |
| **G07** | Red flag disqualification and veto persistence before order entry | `services/market-intelligence/stock_decision_engine.py` | `tests/unit/test_news_fundamental_safety.py::test_g07_red_flag_disqualification_and_veto_persistence` | **PASS** | Batch G |
| **G08** | Strict point-in-time causal protection against future data leakage | `services/market-intelligence/news_fundamental_contracts.py` | `tests/unit/test_news_fundamental_safety.py::test_g08_strict_point_in_time_causal_protection` | **PASS** | Batch G |
| **G09** | Emergency holding exit triggered on corporate governance scandals / disqualification | `services/market-intelligence/stock_decision_engine.py` | `tests/unit/test_news_fundamental_safety.py::test_g09_emergency_holding_exit_on_governance_scandals` | **PASS** | Batch G |
| **G10** | Configurable portable persistence paths (no hardcoded developer paths) | `services/market-intelligence/` modules | `tests/unit/test_news_fundamental_safety.py::test_g10_configurable_portable_persistence_paths` | **PASS** | Batch G |
| **G11** | Timeout bounding and exception containment on outbound feed requests | `services/market-intelligence/collector_service.py` | `tests/unit/test_news_fundamental_safety.py::test_g11_timeout_bounding_on_outbound_feeds` | **PASS** | Batch G |
| **G12** | End-to-end decision integrity and audit immutability | `services/market-intelligence/stock_decision_engine.py` | `tests/unit/test_news_fundamental_safety.py::test_g12_end_to_end_decision_integrity_and_audit_immutability` | **PASS** | Batch G |
| **H01** | Missing required tool causes nonzero exit code and BLOCKED report | `scripts/verify_release.sh` | `tests/unit/test_batch_h_release_gate.py::test_h01_missing_required_tool_causes_nonzero_blocked` | **PASS** | Batch H |
| **H02** | Any failure in lint/typecheck/test/build/scan propagates non-zero exit | `scripts/verify_release.sh` | `tests/unit/test_batch_h_release_gate.py::test_h02_lint_type_test_build_scan_failure_causes_nonzero` | **PASS** | Batch H |
| **H03** | npm ci failure cannot fall back to unlocked install | `Makefile`, `scripts/verify_release.sh` | `tests/unit/test_batch_h_release_gate.py::test_h03_npm_ci_failure_cannot_fall_back_to_unlocked_install` | **PASS** | Batch H |
| **H04** | Required skipped Docker/browser test strictly prevents VERIFIED release status | `scripts/verify_release.sh` | `tests/unit/test_batch_h_release_gate.py::test_h04_required_skipped_docker_browser_test_prevents_verified` | **PASS** | Batch H |
| **H05** | Real image positive and negative controls run in CI | `tests/deployment/test_image_canary_layers.py` | `tests/unit/test_batch_h_release_gate.py::test_h05_real_image_positive_and_negative_controls` | **PASS** | Batch H |
| **H06** | All maintained suites execute, including intelligence and browser execution tests | `scripts/verify_release.sh`, `Makefile` | `tests/unit/test_batch_h_release_gate.py::test_h06_all_maintained_suites_execute_including_intelligence` | **PASS** | Batch H |
| **H07** | Coverage thresholds fail when insufficient (<80% overall, <90% safety modules) | `scripts/verify_release.sh` | `tests/unit/test_batch_h_release_gate.py::test_h07_coverage_thresholds_fail_when_insufficient` | **PASS** | Batch H |
| **H08** | Lock install and pip dependency consistency pass on clean Python 3.12 | `requirements.lock` | `tests/unit/test_batch_h_release_gate.py::test_h08_lock_install_and_pip_dependency_consistency` | **PASS** | Batch H |

---

## Gate Verdict Log
* **Initial Reviewed Commit**: `57c34603506ecf9c28666886cee6bb9027085c29`
* **Active Remediation Branch**: `feature/remediation-v2-plan`
* **Batches Implemented & Verified**:
  - Batch A (Historical Data & Immutable Registry: A01–A08) -> **PASS**
  - Batch B (Atomic Fills & Canonical Accounting: B01–B12) -> **PASS**
  - Batch C (Real Strategy Dispatch & Order Provenance: C01–C07) -> **PASS**
  - Batch D (Accurate Backtest Persistence: D01–D07) -> **PASS**
  - Batch E (Exchange-Session Cutoff Handling: E01–E08) -> **PASS**
  - Batch F (Production Config, Secret Discipline & Durable Breaker: F01–F09) -> **PASS**
  - Batch G (Market-Intelligence Safety, Boundaries & Gate: G01–G12) -> **PASS**
  - Batch H (Real Tests, Canary Scanner, Locks, Builds & CI Gate: H01–H08) -> **PASS**
* **Host Environment Release Gate Verdict**:
  `NOT READY / RELEASE CHECK BLOCKED (2 Mandatory Host-Specific Criteria Blocked)`
  - Blocked Check 1: Next.js native SWC build (SWC compiler binary not published for ARM64 Android Termux host; enforced in Linux x86_64 CI).
  - Blocked Check 2: Docker daemon unavailable on Android Termux host (enforced in Linux x86_64 CI).
  - Fail-closed gate behavior verified: `verify_release.sh` strictly exited `1` upon detecting blocked checks, preventing erroneous VERIFIED claim.
* **Paper-Only Execution Invariant**:
  - `LIVE_TRADING_ENABLED = False` permanently locked.
  - `REAL_BROKER_EXECUTION_ENABLED = False` permanently locked.
