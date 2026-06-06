# Vela VPP Makefile
# Usage: make <target>

.PHONY: help install dev-install test test-fast lint fmt typecheck clean \
        dashboard api celery bootstrap seed migrate

PYTHON   := python3
PIP      := $(PYTHON) -m pip
PYTEST   := $(PYTHON) -m pytest
RUFF     := $(PYTHON) -m ruff
MYPY     := $(PYTHON) -m mypy
UVICORN  := $(PYTHON) -m uvicorn
STREAMLIT := streamlit

##@ Help

help:  ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} \
	/^[a-zA-Z_0-9-]+:.*?##/ { printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2 } \
	/^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) }' $(MAKEFILE_LIST)

##@ Setup

install:  ## Install production dependencies
	$(PIP) install -e .

dev-install:  ## Install dev + optional dependencies
	$(PIP) install -e ".[dev,dashboard,graphql,kafka]"
	pre-commit install

bootstrap:  ## Bootstrap the environment (dirs, env vars check)
	$(PYTHON) scripts/bootstrap.py

seed:  ## Seed sample data
	$(PYTHON) scripts/seed_data.py

migrate:  ## Run database migrations
	$(PYTHON) scripts/migrate.py upgrade

##@ Testing

test:  ## Run full test suite
	$(PYTEST) tests/ -v --tb=short -q

test-fast:  ## Run tests excluding slow performance benchmarks
	$(PYTEST) tests/ -v --tb=short -q --ignore=tests/performance

test-unit:  ## Run unit tests only
	$(PYTEST) tests/ -v --tb=short -q \
		--ignore=tests/integration \
		--ignore=tests/performance

test-integration:  ## Run integration tests
	$(PYTEST) tests/integration/ -v --tb=short

test-cov:  ## Run tests with coverage report
	$(PYTEST) tests/ --cov=vela --cov-report=term-missing --cov-report=html:htmlcov -q

test-optimizer:  ## Run optimizer-specific tests
	$(PYTEST) tests/test_milp_optimizer.py tests/test_m6_co_optimization.py -v

test-market:  ## Run market module tests
	$(PYTEST) tests/test_m8_market.py tests/test_m9_settlement.py -v

test-forecast:  ## Run forecasting tests
	$(PYTEST) tests/test_price_forecast.py tests/test_m5_forecasting.py -v

##@ Code quality

lint:  ## Run ruff linter
	$(RUFF) check vela/ tests/ tools/ scripts/

lint-fix:  ## Run ruff linter with auto-fix
	$(RUFF) check --fix vela/ tests/ tools/ scripts/

fmt:  ## Format code with ruff
	$(RUFF) format vela/ tests/ tools/ scripts/

fmt-check:  ## Check formatting without modifying files
	$(RUFF) format --check vela/ tests/ tools/ scripts/

typecheck:  ## Run mypy type checking
	$(MYPY) vela/ --ignore-missing-imports --no-error-summary

pre-commit:  ## Run all pre-commit hooks
	pre-commit run --all-files

##@ Running services

api:  ## Start FastAPI server (reload mode)
	$(UVICORN) vela.api.app:create_app --factory --host 0.0.0.0 --port 8000 --reload

api-prod:  ## Start FastAPI server (production)
	$(UVICORN) vela.api.app:create_app --factory --host 0.0.0.0 --port 8000 --workers 4

dashboard:  ## Start Streamlit dashboard
	$(STREAMLIT) run dashboard/app.py --server.port 8501 --server.address 0.0.0.0

celery-worker:  ## Start Celery worker
	celery -A vela.workers.celery_app worker --loglevel=info --concurrency=4

celery-beat:  ## Start Celery beat scheduler
	celery -A vela.workers.celery_app beat --loglevel=info

celery-flower:  ## Start Celery Flower monitoring UI
	celery -A vela.workers.celery_app flower --port=5555

##@ Diagnostics

check-imports:  ## Check all critical imports resolve
	$(PYTHON) tools/vela_cli/commands/diagnostics.py --all

optimizer-smoke:  ## Quick optimizer smoke test
	$(PYTHON) tools/vela_cli/commands/diagnostics.py --optimizer

forecast-smoke:  ## Quick forecast smoke test
	$(PYTHON) tools/vela_cli/commands/diagnostics.py --forecast

debug-optimizer:  ## Interactive optimizer debug session
	$(PYTHON) tools/debug_optimizer.py

market-replay:  ## Run market replay backtest
	$(PYTHON) tools/market_replay.py --days 7

sim-run:  ## Run Monte Carlo simulation
	$(PYTHON) tools/sim_runner.py --scenarios 50

##@ Data

import-caiso:  ## Import CAISO LMP data
	$(PYTHON) scripts/import_iso_data.py --iso caiso

import-ercot:  ## Import ERCOT SPP data
	$(PYTHON) scripts/import_iso_data.py --iso ercot

backfill:  ## Backfill historical forecasts
	$(PYTHON) scripts/backfill_forecasts.py

data-quality:  ## Run data quality report
	$(PYTHON) scripts/data_quality_report.py

##@ Performance

load-test:  ## Run load tests against local API
	$(PYTHON) scripts/load_test.py

profile:  ## Profile optimizer and forecast
	$(PYTHON) scripts/performance_profile.py

dr-drill:  ## Simulate demand response drill
	$(PYTHON) scripts/dr_drill.py

##@ Certificates and security

gen-certs:  ## Generate self-signed TLS certificates
	$(PYTHON) scripts/generate_certificates.py

##@ Cleanup

clean:  ## Remove build artifacts and caches
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
	find . -type f -name "*.pyc" -delete 2>/dev/null; true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null; true
	rm -rf .pytest_cache/ .mypy_cache/ .ruff_cache/ htmlcov/ dist/ build/ 2>/dev/null; true

clean-all: clean  ## Remove all generated files including .env
	rm -f .env

.DEFAULT_GOAL := help
