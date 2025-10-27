# URLPath

URLPath turns raw URLs into first-class objects that behave like `pathlib` paths and `requests` sessions at the same time. Build, query, and call URLs with an expressive, chainable API.

[![Tests](https://github.com/brandonschabell/urlpath/actions/workflows/test.yml/badge.svg)](https://github.com/brandonschabell/urlpath/actions/workflows/test.yml)
[![PyPI version](https://img.shields.io/pypi/v/urlpath.svg)](https://pypi.python.org/pypi/urlpath)
[![Downloads](https://pepy.tech/badge/urlpath)](https://pepy.tech/project/urlpath)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Versions](https://img.shields.io/pypi/pyversions/urlpath.svg)](https://pypi.org/project/urlpath/)

## Features

- Compose URLs with `pathlib` semantics: join segments, inspect components, and normalise paths.
- Access and mutate parts of the URL (`scheme`, `netloc`, `userinfo`, `query`, `fragment`, etc.) with fluent helpers.
- Treat query strings as multidicts, rebuild them from dicts/objects, or append additional parameters without losing order.
- Make HTTP requests directly from any `URL` (`get`, `post`, `patch`, `put`, `delete`) and fetch JSON with optional JMESPath filtering.
- Keep callers inside a known root using `JailedURL` guards.
- Accept familiar inputs: strings, bytes, `urllib.parse` results, `webob.Request`, and other `PathLike` objects.

## How to install

```bash
pip install urlpath
```
### Dependencies

* **Python 3.9–3.14**
* **[Requests](http://docs.python-requests.org/)** - required for HTTP verbs.
* **[JMESPath](https://pypi.org/project/jmespath/)** - optional, enables filtered `get_json` responses.
* **[WebOb](http://webob.org/)** - optional, allows constructing URLs directly from `webob.Request` instances.

## Quick start

```python
from urlpath import URL

api = URL("https://api.example.com/v1")
user = api / "users" / "123"

# Manipulate components just like pathlib
assert user.path == "/v1/users/123"
assert user.parent == URL("https://api.example.com/v1/users")

# Tweak and inspect the query string
endpoint = user.with_query(include=["profile", "activity"]).add_query(page=2)
assert str(endpoint) == "https://api.example.com/v1/users/123?include=profile&include=activity&page=2"

# Call the URL with requests
response = endpoint.get()
if response.ok:
    data = endpoint.get_json(keys="user.profile")  # Optional JMESPath filter
```

## Path-aware URL composition

`URL` subclasses `pathlib.PurePath` to give you intuitive operations:

```python
url = URL("https://username:password@secure.example.com:1234/path/to/file.ext?field1=1#fragment")

url.drive      # 'https://username:password@secure.example.com:1234'
url.anchor     # 'https://username:password@secure.example.com:1234/'
url.parts      # ('https://username:password@secure.example.com:1234/', 'path', 'to', 'file.ext')
url.name       # 'file.ext'
url.suffixes   # ['.ext']
url.parent     # URL('https://username:password@secure.example.com:1234/path/to')

# Slash-join works the way pathlib users expect
assert str(url / "reports" / "2024.json") == "https://username:password@secure.example.com:1234/path/to/file.ext/reports/2024.json"
assert str((url / "../templates").resolve()) == "https://username:password@secure.example.com:1234/path/to/templates"

# Absolute joins or constructor segments reset the path
assert str(url / "/reset/path") == "https://username:password@secure.example.com:1234/reset/path"
assert str(URL("https://example.com/base", "/fresh")) == "https://example.com/fresh"
```

Use the fluent `with_*` helpers to surgically update components:

```python
url = URL("http://www.example.com/path/to/file.exe?query#frag")
url = url.with_scheme("https").with_userinfo("user", "secret")
assert str(url) == "https://user:secret@www.example.com/path/to/file.exe?query#frag"
assert url.hostname == "www.example.com"
```

## Query and fragment helpers

URLPath keeps queries ordered and exposes them through a WebOb-style multidict:

```python
url = URL("http://www.example.com/form")
form_url = url.with_query({"field1": ["value1", "value2"], "field2": "hello, world"})

form_url.form.get("field1")      # ("value1", "value2")
"field2" in form_url.form        # True

# Append without losing the existing parameters
extended = form_url.add_query(field3="value3")
assert extended.query == "field1=value1&field1=value2&field2=hello%2C+world&field3=value3"

# Swap out the fragment without touching the rest of the URL
assert str(url.with_fragment("section-3")) == "http://www.example.com/form#section-3"
```

## HTTP requests & JSON extraction

Every `URL` instance can issue HTTP requests via `requests`:

```python
url = URL("https://httpbin.org/anything")
response = url.post(json={"hello": "world"})
response.raise_for_status()

# Fetch JSON and optionally apply a JMESPath expression
reporting_api = URL("https://api.example.com/reports")
document = reporting_api.get_json(query={"status": "active"}, keys="items[*].name")
# => ["Quarterly", "Annual"]
```

Pass a compiled JMESPath expression instead of a string when you need to reuse filters:

```python
import jmespath

expr = jmespath.compile("users[*].age")
ages = URL("https://api.example.com/users").get_json(keys=expr)
```

`jmespath` is optional; install it to enable filtered lookups (`pip install urlpath[jmespath]`).

## Constrain navigation with jailed URLs

`JailedURL` confines joins and resolutions to a particular origin, preventing escapes:

```python
root = URL("https://www.example.com/app/")
current = root.jailed / "path/to/content"

assert str(current / "appendix") == "https://www.example.com/app/path/to/content/appendix"
assert str((current / "/root").resolve()) == "https://www.example.com/app/root"
assert str(current / "https://malicious.test") == "https://www.example.com/app/"
```

You can also wrap an incoming `webob.Request` to mirror the application's mount point:

```python
import webob
from urlpath import JailedURL

request = webob.Request.blank(
    "/docs/page",
    base_url="https://docs.example.com",
    environ={"SCRIPT_NAME": "/knowledge-base"},
)

jailed = JailedURL(request)
assert str(jailed) == "https://docs.example.com/knowledge-base/docs/page"
assert str(jailed.chroot) == "https://docs.example.com/knowledge-base"
```

## Works with familiar URL sources

The constructor accepts many canonical URL representations:

```python
from pathlib import PurePosixPath
from urllib.parse import urlsplit

URL(urlsplit("https://example.com/from-split"))
URL(PurePosixPath("path/segment"))            # usable when joining onto a local path
URL(b"https://example.com/from-bytes")
URL(webob.Request.blank("/resource", base_url="https://example.com"))
```

## Encoding-aware by default

IDNs and percent-encoding are handled for you:

```python
url = URL("http://www.xn--alliancefranaise-npb.nu/")
url.hostname # "www.alliancefran\u00e7aise.nu"

URL("http://example.com/name").with_name("\u65e5\u672c\u8a9e/\u540d\u524d")
# str(encoded) == "http://example.com/%E6%97%A5%E6%9C%AC%E8%AA%9E%2F%E5%90%8D%E5%89%8D"
```

## Testing the examples

You can find additional examples in the doctest script located at [docttests.md](tests/doctests.md).

See the [test suite](tests/test_url.py) for more usage patterns and edge cases.

Run `make test` to execute tests and ensure the published examples stay up to date.
