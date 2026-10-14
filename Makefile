.PHONY: help install verify-locks sbom import-check compile lint typecheck test test-security test-browser build test-deployment security-scan release-check

help:
	@echo "Algo Lab Makefile Targets:"
	@echo "  make install         - Install dependencies from pinned lockfile"
	@echo "  make verify-locks    - Verify dependency lockfile consistency and integrity"
	@echo "  make sbom            - Generate CycloneDX JSON Software Bill of Materials"
	@echo "  make import-check    - Verify Python 3.12 startup and module imports"
	@echo "  make compile         - Compile Python source files"
	@echo "  make lint            - Run syntax and lint checks"
	@echo "  make typecheck       - Run Python and TypeScript type checks"
	@echo "  make test            - Run all test suites"
	@echo "  make test-security   - Run security and safety-critical test suites"
	@echo "  make test-browser    - Run browser/XSS test suites"
	@echo "  make build           - Build frontend and verify Python packages"
	@echo "  make test-deployment - Run deployment and container tests"
	@echo "  make security-scan   - Run static analysis security scan"
	@echo "  make release-check   - Run complete canonical release gate verification"

install:
	pip install -r requirements.lock
	@if command -v npm >/dev/null 2>&1; then \
		npm --prefix apps/web ci; \
	fi

verify-locks:
	python3 scripts/verify_locks.py

sbom:
	python3 scripts/generate_sbom.py --output sbom.json

import-check:
	python3 -m pytest tests/integration/test_python312_startup.py -v

compile:
	python3 -m compileall -q apps data database quant services

lint: compile
	@if command -v ruff >/dev/null 2>&1; then \
		ruff check apps/ services/ data/ --ignore E501,E402; \
	else \
		echo "ruff not installed; Python compilation passed"; \
	fi

typecheck:
	@if [ -f apps/web/node_modules/.bin/tsc ]; then \
		./apps/web/node_modules/.bin/tsc -p apps/web/tsconfig.json --noEmit; \
	fi
	@if command -v mypy >/dev/null 2>&1; then \
		mypy apps/ services/ --ignore-missing-imports --no-strict-optional; \
	fi

test:
	python3 -m pytest tests/ -q --disable-warnings

test-security:
	python3 -m pytest \
		tests/integration/test_security_configuration.py \
		tests/integration/test_authorization_enforcement.py \
		tests/integration/test_credential_error_redaction.py \
		tests/unit/test_circuit_breaker_state_integrity.py \
		tests/unit/test_circuit_breaker_persistence_failures.py \
		tests/unit/test_credential_failure_modes.py \
		tests/unit/test_batch_f_config_and_breaker.py \
		tests/unit/test_news_fundamental_safety.py \
		tests/integration/test_actual_ledger_reconciliation.py \
		tests/integration/test_backup_failure_modes.py \
		tests/integration/test_protective_cutoff_failure_modes.py \
		tests/unit/test_backup_restore_encryption.py \
		tests/unit/test_architecture_isolation.py \
		tests/unit/test_data_governance_lineage.py \
		-v

test-browser:
	python3 -m pytest tests/browser/ -v
	@if [ -f apps/web/package.json ] && command -v npm >/dev/null 2>&1; then \
		npm --prefix apps/web run test:ci; \
	fi

build: compile
	@if [ -d apps/web/node_modules ]; then \
		./apps/web/node_modules/.bin/tsc -p apps/web/tsconfig.json --noEmit; \
	fi
	@if command -v npm >/dev/null 2>&1; then \
		npm --prefix apps/web run build; \
	fi

test-deployment:
	python3 -m pytest tests/deployment/ -v

security-scan:
	@if command -v bandit >/dev/null 2>&1; then \
		bandit -r apps/ services/ -ll --skip B101,B311; \
	else \
		echo "bandit not installed"; \
	fi

release-check:
	@bash scripts/verify_release.sh
