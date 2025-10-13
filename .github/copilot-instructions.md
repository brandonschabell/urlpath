# URLPath AI Coding Instructions

## Project Overview
URLPath is a Python library that extends `pathlib.PurePath` to provide object-oriented URL manipulation, combining filesystem path operations with URL components (scheme, netloc, query, fragment). The main `URL` class inherits from both `urllib.parse._NetlocResultMixinStr` and `PurePath`, enabling pathlib-style operations on URLs.

## Core Architecture

### URL Class Design Pattern
- **Inheritance**: `URL` extends `PurePath` with custom `_URLFlavour` that treats URLs as filesystem paths
- **Cached Properties**: Heavy use of `@cached_property` decorator for lazy evaluation of URL components
- **Immutability**: URLs are immutable; modifications return new instances via `with_*` methods
- **Path Encoding**: Uses `\x00` as escape character for `/` in query/fragment components during path operations

### Key Components
- **`_URLFlavour`**: Custom pathlib flavour that handles URL parsing via `splitroot()` method
- **`FrozenMultiDict`**: Immutable multi-value dictionary for query parameters with `get_one()` method
- **`JailedURL`**: Sandboxed URL subclass that prevents navigation outside a root URL
- **HTTP Methods**: Built-in `get()`, `post()`, `put()`, `patch()`, `delete()` using requests library

## Development Patterns

### Property Implementation
```python
@property
@cached_property
def scheme(self):
    return urllib.parse.urlsplit(self._drv).scheme
```
All URL components follow this pattern: property decorator + cached_property for performance.

### URL Construction Methods
- `with_*` methods for component replacement (e.g., `with_scheme()`, `with_query()`)
- Path operations use `/` operator: `url / 'path'` or `url / '/absolute'`
- Query building via `with_query()` and `add_query()` methods

### Testing Conventions
- Tests in `tests/test_url.py` use pytest with native assert statements
- Comprehensive property testing for all URL components
- HTTP method testing (when possible)
- Optional dependency tests use `@pytest.mark.skipif` decorators
- README examples are automatically tested using pytest-markdown-docs

### Development Workflow

### Setup and Dependencies
```bash
# Initialize development environment
make install

# Or directly with uv
uv sync --group dev
```

### Running Tests
```bash
# Run all tests
make test

# Run unit tests only
make test-unit

# Run README tests only
make test-doctest

# Or use uv directly
uv run pytest tests/
uv run pytest README.md --markdown-docs
```

### Building and Packaging
```bash
# Build package
make build

# Clean artifacts
make clean

# See all available commands
make help
```

### Dependencies
- **Core**: `requests` for HTTP operations
- **Optional**: `jmespath` for JSON parsing, `webob` for request object support
- **Testing**: `pytest` for unit tests, `pytest-markdown-docs` for README testing
- **Build System**: `uv` with `hatchling` backend for modern Python packaging

### CI Configuration
GitHub Actions tests against Python 3.9-3.13 using `uv sync` and matrix strategy. Both unit tests and README doctests must pass.

## Code Conventions

### URL Component Access
- Use properties for read access: `url.scheme`, `url.path`, `url.query`
- Use `with_*` methods for modifications: `url.with_scheme('https')`
- Query parameters via `url.form` (FrozenMultiDict) or `url.form_fields` (tuples)

### Error Handling
- Malformed URLs raise standard `ValueError` from urllib.parse
- JailedURL validates root constraints in `__new__` with assertion
- Optional dependencies gracefully degrade (check `if jmespath:`)

### Performance Considerations
- URL parsing is expensive; use `@cached_property` for derived properties
- `_init()` method handles post-construction setup after pathlib operations
- Path operations use `_make_child()` pattern from pathlib for efficiency

### File Structure
- `urlpath/__init__.py`: Single-file module with all classes
- `tests/test_url.py`: Comprehensive pytest test suite
- `README.md`: Extensive examples with automated pytest validation
- `conftest.py`: pytest configuration for test discovery and path setup
