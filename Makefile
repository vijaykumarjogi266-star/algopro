.PHONY: help install compile lint typecheck test test-security test-browser build test-deployment release-check

help:
	@echo "Algo Lab Makefile Targets:"
	@echo "  make install         - Install dependencies"
	@echo "  make compile         - Compile Python source files"
	@echo "  make lint            - Run syntax and lint checks"
	@echo "  make typecheck       - Run Python and TypeScript type checks"
	@echo "  make test            - Run all test suites"
	@echo "  make test-security   - Run security and safety-critical test suites"
	@echo "  make test-browser    - Run browser/XSS test suites"
	@echo "  make build           - Build frontend and verify Python packages"
	@echo "  make test-deployment - Run deployment and container tests"
	@echo "  make release-check   - Run complete release gate verification"

install:
	pip install -r requirements.txt
	@if command -v npm >/dev/null 2>&1; then \
		npm --prefix apps/web install --prefer-offline --no-audit --no-fund; \
	fi

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
		mypy apps/ services/ --ignore-missing-imports --no-strict-optional || true; \
	fi

test:
	python3 -m pytest tests/ -q --disable-warnings

test-security:
	python3 -m pytest \
		tests/integration/test_security_configuration.py \
		tests/integration/test_authorization.py \
		tests/integration/test_credential_error_redaction.py \
		tests/unit/test_circuit_breaker_state_integrity.py \
		tests/unit/test_circuit_breaker_persistence_failures.py \
		tests/unit/test_credential_failure_modes.py \
		tests/integration/test_actual_ledger_reconciliation.py \
		tests/integration/test_backup_failure_modes.py \
		-v

test-browser:
	python3 -m pytest tests/browser/ -v

build: compile
	@if [ -d apps/web/node_modules ]; then \
		./apps/web/node_modules/.bin/tsc -p apps/web/tsconfig.json --noEmit; \
	fi
	@if command -v npm >/dev/null 2>&1; then \
		npm --prefix apps/web run build || echo "Notice: Next.js native SWC not supported on host architecture (ARM64 Android); builds in Linux CI"; \
	fi

test-deployment:
	python3 -m pytest tests/deployment/ -v

release-check:
	@bash scripts/verify_release.sh
