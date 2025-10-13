# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- **License changed from PSF-2.0 to MIT** - More permissive and standard for open source libraries
- Migrated from setuptools to modern UV/hatchling build system
- Migrated README from RST to Markdown format with executable code examples
- Dropped support for Python 3.4-3.8 (now requires Python 3.9+)
- Replaced `python -m doctest README.rst` with pytest-markdown-docs for testing examples
- Converted tests from unittest to pytest style (native assert statements, fixtures)
- Restructured package from single file (`urlpath.py`) to proper package directory (`urlpath/__init__.py`)
- Converted README examples from RST doctest format to executable Python code blocks
- Reorganized test directory from `test/` to `tests/` (following pytest conventions)
- Enhanced pytest configuration with strict mode and warning filters
- Consolidated and cleaned up `.gitignore` file with modern Python tooling patterns
- Replaced Travis CI with GitHub Actions for all CI/CD workflows
- Updated GitHub Actions workflows to use modern actions and UV package manager
- Modernized code formatting (improved consistency and readability)
- Centralized all package metadata in `pyproject.toml` (removed from module docstring)
- **Updated all docstrings from reStructuredText to Google/NumPy style** (Args/Returns/Raises format)
- **Refactored monolithic module into modular structure**: Split `urlpath/__init__.py` (1540 lines) into `_compat.py`, `_utils.py`, `_flavour.py`, and `_url.py` for better maintainability
- **Centralized Python version checking**: Replaced 18 scattered `sys.version_info >= (3, 12)` checks with single `IS_PY312_PLUS` constant in `_compat.py`
- **Added `cleanup_escapes()` helper function**: Eliminated 6 duplicate `.replace("\\x00", "/")` patterns for cleaner code
- **Made WebOb a required test dependency**: Removed conditional imports and test skips to ensure WebOb integration is always tested

### Added
- `.python-version` file for Python version management
- Comprehensive Makefile with development targets (test, lint, format, build, clean, etc.)
- Ruff for both linting and code formatting
- mypy for static type checking with relaxed configuration
- pytest as the test runner (replacing unittest CLI)
- pytest-markdown-docs for testing README code examples
- `conftest.py` for pytest sys.path configuration
- GitHub Actions workflow for automated releases to PyPI (`release.yml`)
- Separate CI jobs for linting/formatting/type checking vs. tests
- Pre-commit hooks configuration (`.pre-commit-config.yaml`)
- Keywords in `pyproject.toml` for better PyPI discoverability
- Downloads badge in README.md
- MIT LICENSE file
- CHANGELOG.md file (this file)
- `.github/copilot-instructions.md` for AI-assisted development
- `uv.lock` for reproducible dependency resolution
- **`from __future__ import annotations`** for modern type annotation support in Python 3.9+
- **Complete type annotations** for all 56+ functions, methods, and properties
- **Comprehensive docstrings** for all public classes, functions, methods, and properties
- **Pydocstyle linting** (Ruff "D" rules) to enforce documentation consistency
- **Type annotations for all test functions** (`-> None` return types)
- **Docstrings for magic methods** (`__str__`, `__bytes__`, etc.)
- **Test coverage for constructor canonicalization**: Tests for `SplitResult`, `ParseResult`, `bytes`, and `__fspath__` inputs
- **Test coverage for multi-argument URL construction**: Validates that `URL("base", "child", "../final")` matches chained joinpath semantics

### Removed
- `setup.py` (replaced by `pyproject.toml`)
- `MANIFEST` file (replaced by hatchling configuration)
- `README.rst` (replaced by `README.md`)
- `deploy.yml` workflow (replaced by `release.yml`)
- Support for Python 3.4, 3.5, 3.6, 3.7, and 3.8
- Travis CI configuration (replaced by GitHub Actions)

## [1.2.0] - (Previous release)

See git history for changes prior to modernization.
