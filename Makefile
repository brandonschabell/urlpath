.PHONY: help install install-hooks test test-unit test-doctest build clean format lint check mypy
.DEFAULT_GOAL := help

# Use copy mode to avoid filesystem reflink issues
export UV_LINK_MODE = copy

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Targets:'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-15s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install development dependencies
	uv sync --group dev

install-hooks: ## Install pre-commit hooks (optional)
	uv run --group dev pre-commit install

test: test-unit test-doctest ## Run all tests

test-unit: ## Run unit tests
	uv run --group dev pytest tests/

test-doctest: ## Run doctests from README
	uv run --group dev pytest README.md --markdown-docs

build: ## Build package
	uv build

clean: ## Clean build artifacts
	rm -rf build/ dist/ *.egg-info/ __pycache__/ tests/__pycache__/ .mypy_cache/
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete

format: ## Format code with ruff
	uv run --group dev ruff format

format-check: ## Check if code is formatted
	uv run --group dev ruff format --check

lint: ## Lint code with ruff
	uv run --group dev ruff check

lint-fix: ## Lint and fix code with ruff
	uv run --group dev ruff check --fix

mypy: ## Run mypy type checking
	uv run --group dev mypy urlpath/ tests/

check: format-check lint mypy test ## Run format check, linting, type checking, and tests
