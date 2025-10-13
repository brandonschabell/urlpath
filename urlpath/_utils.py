"""Utility functions and data structures for URL manipulation."""

from __future__ import annotations

__all__ = (
    "FrozenDict",
    "FrozenMultiDict",
    "MultiDictMixin",
    "cached_property",
    "netlocjoin",
    "_url_splitroot",
    "cleanup_escapes",
)

import functools
import re
import urllib.parse
from collections.abc import Iterator, Mapping
from typing import Any, Callable, TypeVar

_KT = TypeVar("_KT")
_VT = TypeVar("_VT")


# http://stackoverflow.com/a/2704866/3622941
class FrozenDict(Mapping[_KT, _VT]):
    """Immutable dictionary with hashability.

    An immutable mapping type that can be hashed and used as a dictionary key
    or set member. Uses XOR-based hashing for O(n) performance.

    This implementation provides:
    - Immutability: Cannot be modified after creation
    - Hashability: Can be used as dict keys or in sets
    - Memory efficiency: Uses __slots__ to reduce memory overhead

    Examples:
        >>> fd = FrozenDict({'a': 1, 'b': 2})
        >>> fd['a']
        1
        >>> hash(fd)  # Can be hashed
        >>> fd['a'] = 3  # Raises error - immutable
    """

    __slots__ = ("_d", "_hash")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._d: dict[_KT, _VT] = dict(*args, **kwargs)
        self._hash: int | None = None

    def __iter__(self) -> Iterator[_KT]:
        return iter(self._d)

    def __len__(self) -> int:
        return len(self._d)

    def __getitem__(self, key: _KT) -> _VT:
        return self._d[key]

    def __hash__(self) -> int:
        # It would have been simpler and maybe more obvious to
        # use hash(tuple(sorted(self._d.items()))) from this discussion
        # so far, but this solution is O(n). I don't know what kind of
        # n we are going to run into, but sometimes it's hard to resist the
        # urge to optimize when it will gain improved algorithmic performance.
        if self._hash is None:
            self._hash = 0
            for pair in self._d.items():
                self._hash ^= hash(pair)
        return self._hash

    def __repr__(self) -> str:
        return "<{} {{{}}}>".format(
            self.__class__.__name__,
            ", ".join("{!r}: {!r}".format(*i) for i in sorted(self._d.items())),
        )


class MultiDictMixin:
    """Mixin that adds get_one() method for multi-value dictionaries.

    Useful for dictionaries where values are sequences (like URL query parameters).
    """

    def get_one(
        self,
        key: Any,
        default: Any = None,
        predicate: Callable[[Any], bool] | None = None,
        type_: Callable[[Any], Any] | None = None,
    ) -> Any:
        """Get the first value for a key that matches the predicate.

        Args:
            key: The dictionary key to look up
            default: Value to return if key not found or no value matches predicate
            predicate: Optional callable to filter values (e.g., from inspect.getmembers)
            type_: Optional callable to transform the returned value

        Returns:
            The first matching value, optionally transformed by type_ callable,
            or default if no match found.
        """
        try:
            values = self[key]  # type: ignore[index]
        except LookupError:
            pass
        else:
            for value in values:
                if not predicate or predicate(value):
                    return value if not type_ else type_(value)

        return default


class FrozenMultiDict(MultiDictMixin, FrozenDict[str, tuple[str, ...]]):
    """Immutable multi-value dictionary for URL query parameters.

    Combines FrozenDict's immutability and hashing with MultiDictMixin's
    get_one() method for handling multiple values per key.
    """


_F = TypeVar("_F", bound=Callable[..., Any])


def cached_property(getter: _F) -> _F:
    """Cached property decorator that doesn't require __hash__.

    A lightweight alternative to functools.lru_cache that stores the
    computed value in the instance's __dict__ without requiring the
    instance to be hashable.

    This decorator can be stacked with @property for compatibility with
    PurePath's property-based API.

    Args:
        getter: The property getter function to cache

    Returns:
        A wrapper function that caches the result of the first call
    """

    @functools.wraps(getter)
    def helper(self: Any) -> Any:
        key = "_cached_property_" + getter.__name__

        if key in self.__dict__:
            return self.__dict__[key]

        result = self.__dict__[key] = getter(self)
        return result

    return helper  # type: ignore[return-value]


def netlocjoin(
    username: str | None,
    password: str | None,
    hostname: str | None,
    port: int | None,
) -> str:
    """Build a network location string from components.

    Constructs a netloc in the format 'username:password@hostname:port',
    omitting components that are None and properly percent-encoding
    username and password.

    Args:
        username: Username string (will be percent-encoded) or None
        password: Password string (will be percent-encoded) or None
        hostname: Hostname string or None
        port: Port number or None

    Returns:
        Formatted netloc string (e.g., 'user:pass@host:8080').
    """
    result = ""

    if username is not None:
        result += urllib.parse.quote(username, safe="")

    if password is not None:
        result += ":" + urllib.parse.quote(password, safe="")

    if result:
        result += "@"

    if hostname is not None:
        result += hostname.encode("idna").decode("ascii")

    if port is not None:
        result += ":" + str(port)

    return result


def _url_splitroot(part: str, sep: str = "/") -> tuple[str, str, str]:
    """Split a URL into drive (scheme+netloc), root, and path components.

    Shared implementation for both Python 3.12+ and <3.12 _URLFlavour classes.

    Args:
        part: URL string to split
        sep: Path separator (must be '/')

    Returns:
        Tuple of (drive, root, path) where:
        - drive is 'scheme://netloc'
        - root is the leading '/' if present
        - path is the remainder with query/fragment escaped
    """
    assert sep == "/"
    assert "\\x00" not in part

    scheme, netloc, path, query, fragment = urllib.parse.urlsplit(part)

    # trick to escape '/' in query and fragment and trailing
    if not re.match(re.escape(sep) + "+$", path):
        path = re.sub(f"{re.escape(sep)}+$", lambda m: "\\x00" * len(m.group(0)), path)
    path = urllib.parse.urlunsplit(("", "", path, query.replace("/", "\\x00"), fragment.replace("/", "\\x00")))

    drive = urllib.parse.urlunsplit((scheme, netloc, "", "", ""))
    match = re.match(f"^({re.escape(sep)}*)(.*)$", path)
    assert match is not None  # we're sure it's always valid for this regex
    root, path = match.groups()
    return drive, root, path


def cleanup_escapes(text: str) -> str:
    r"""Clean up escape sequences used for URL component separation.

    Replaces the internal escape character (\x00) used to protect
    forward slashes in query and fragment components back to regular
    forward slashes.

    Args:
        text: String potentially containing \x00 escape sequences

    Returns:
        String with \x00 replaced by /
    """
    return text.replace("\x00", "/").replace("\\x00", "/").replace("%5Cx00", "/").replace("%5cx00", "/")
