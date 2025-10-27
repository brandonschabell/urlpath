.PHONY: help install install-hooks test test-unit test-doctest build clean fix check mypy
.DEFAULT_GOAL := help

# Use copy mode to avoid filesystem reflink issues
export UV_LINK_MODE = copy

DOC_TESTS = tests/doctests.md

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

test-doctest: ## Run doctests from doctests.md
	uv run --group dev pytest $(DOC_TESTS) --markdown-docs

build: ## Build package
	uv build

clean: ## Clean build artifacts
	rm -rf build/ dist/ *.egg-info/ __pycache__/ tests/__pycache__/ .mypy_cache/
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete

fix: ## Fix formatting and linting issues automatically
	uv run --group dev ruff check --fix
	uv run --group dev ruff format

mypy: ## Run mypy type checking
	uv run --group dev mypy urlpath/ tests/

check: ## Verify code quality (format, lint, type check, test)
	uv run --group dev ruff format --check
	uv run --group dev ruff check
	uv run --group dev mypy urlpath/ tests/
	uv run --group dev pytest tests/ $(DOC_TESTS) --markdown-docs
