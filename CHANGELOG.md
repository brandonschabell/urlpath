# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- **`JailedURL` now collapses `..` segments eagerly** when joining or constructing, so `str()` of a jailed URL
  can never point outside the jail root (previously this only happened on `.resolve()`). For example,
  `str(JailedURL("http://example.com/app") / "../../etc")` is now `http://example.com/app/etc`.
- Invalid argument combinations (`with_components`, `with_query`, `add_query`) and a malformed `JailedURL` root
  now raise `ValueError` instead of `AssertionError` (the checks no longer disappear under `python -O`)
- URLs containing a raw NUL character now raise `ValueError`
- Added support for Python 3.15; CI also runs on pushes to `main`
- Docstring examples are now run as doctests

### Fixed
- Python 3.15: `os.fspath(url)` returned the internal escaped string, breaking joins and `with_*` methods
- IPv6 hosts lost their brackets (`http://[::1]:8080/` was rendered as `http://::1:8080/`)
- The literal text `\x00` (and `%5Cx00` / `%5cx00`) in a URL was rewritten to `/` or raised `AssertionError`
- `JailedURL.resolve()` could duplicate the root path (`/app/app/...`) if `.parts` had been accessed first
- `relative_to()` raised on Python 3.12+ when the URL had a trailing slash, query or fragment
- Incorrect docstring examples for `URL`, `JailedURL` and `FrozenDict`

## [2.0.0] - 2025-10-13

### Changed
- **License changed from PSF to MIT**
- **Dropped support for Python 3.4-3.8** (now requires Python 3.9+)
- **Added support for Python 3.11, 3.12, 3.13, and 3.14**
- Build system migrated from setuptools to UV/hatchling
- README format changed from RST to Markdown
- Package structure changed from single-file module (`urlpath.py`, 689 lines) to multi-module package (`urlpath/__init__.py` + 4 submodules, 1852 total lines)
- Test directory renamed from `test/` to `tests/`
- Tests converted from unittest style to pytest style
- GitHub Actions workflow updated to use UV package manager and test Python 3.9-3.14
- GitHub Actions `deploy.yml` replaced with `release.yml` for PyPI releases
- `.gitignore` simplified from 103 lines to 29 lines
- Internal Python version checks consolidated into `IS_PY312_PLUS` constant in `_compat.py`
- Duplicate escape sequence handling patterns replaced with `cleanup_escapes()` helper function in `_utils.py`

### Added
- `.python-version` file (specifies 3.9-3.14)
- `Makefile` with development targets (install, test, lint, format, check, build, clean, help)
- `pyproject.toml` for all package configuration and metadata
- `conftest.py` for pytest configuration
- `.pre-commit-config.yaml` for automated code quality checks
- `LICENSE` file (MIT)
- `CHANGELOG.md` (this file)
- `uv.lock` for dependency locking
- `.github/copilot-instructions.md` for AI development assistance
- Ruff for linting and formatting
- mypy for type checking
- pytest and pytest-markdown-docs for testing
- Type annotations (`from __future__ import annotations` and full typing throughout)
- Comprehensive docstrings for all classes, methods, and properties
- Additional test coverage (constructor canonicalization, multi-argument construction, JMESPath filtering)

### Removed
- `setup.py`
- `MANIFEST` file
- `README.rst`
- `.github/workflows/deploy.yml`
- Travis CI badge from README

## [1.2.0] - 2021-11-12

See git history for changes prior to this release.
