.PHONY: help install compile lint typecheck test test-safety release-check

help:
	@echo "Algo Lab Makefile Targets:"
	@echo "  make install         - Install locked dependencies"
	@echo "  make compile         - Compile Python source files"
	@echo "  make test-safety     - Run safety-critical & regression test suites"
	@echo "  make release-check   - Run all comprehensive release verification checks"

compile:
	python3 -m compileall -q apps data database quant services

test-safety:
	python3 -m pytest tests/unit/test_circuit_breaker_security.py tests/unit/test_backtest_simulation.py tests/unit/test_credentials_security.py tests/unit/test_daemon_risk_state.py tests/unit/test_vwap_research.py tests/unit/test_backtest_step7.py tests/unit/test_stage5_integrity.py -v

release-check:
	@bash scripts/verify_release.sh
