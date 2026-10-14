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
| **C01-C07** | Strategy registry & dispatch, stop/target parameter protection | `quant/strategies/`, orchestrator, daemon | `tests/unit/test_manifest_freshness_and_replay.py`, `test_buy_and_hold_allocation.py` | PENDING | Batch C |
| **D01-D07** | Accurate backtest persistence & timestamp integrity | `services/backtest-engine/` | `tests/unit/test_backtest_accounting_and_risk.py` | PENDING | Batch D |
| **E01-E08** | Protective cutoff & exchange session resilience | `run_live_paper_daemon.py`, sentinel | `tests/integration/test_protective_cutoff_failure_modes.py` | PENDING | Batch E |
| **F01-F09** | Production configuration & durable breaker recovery | `apps/api/core/config.py`, breaker | `tests/integration/test_security_configuration_end_to_end.py` | PENDING | Batch F |
| **G01-G12** | Market-intelligence safety, timeouts, risk bounds | `services/market-intelligence/` | `tests/unit/test_news_fundamental_safety.py` | PENDING | Batch G |
| **H01-H08** | Portable lock verification, all-layer canary scan, CI gate | `scripts/verify_release.sh`, Makefile | `tests/unit/test_release_gate_behavior.py`, `test_image_canary_layers.py` | PENDING | Batch H |

---

## Gate Verdict Log
* **Current Baseline**: Head commit `57c34603506ecf9c28666886cee6bb9027085c29` on branch `feature/remediation-v2-plan`
* **Test Suite Baseline**: 684 collected tests
