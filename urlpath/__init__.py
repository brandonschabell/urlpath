"""Object-oriented URL from `urllib.parse` and `pathlib`."""

from __future__ import annotations

__all__ = ("URL",)

import collections.abc
import functools
import os
import posixpath
import re
import sys
import urllib.parse
from collections.abc import Iterator
from pathlib import PurePath
from typing import Any, Callable, TypeVar
from unittest.mock import patch

import requests

# Python 3.12+ removed _PosixFlavour class, replaced with module-based approach
if sys.version_info >= (3, 12):
    _PosixFlavour = None  # noqa: F811
else:
    from pathlib import _PosixFlavour

try:
    import jmespath
except ImportError:
    jmespath = None

try:
    import webob
except ImportError:
    webob = None

missing = object()


_KT = TypeVar("_KT")
_VT = TypeVar("_VT")


# http://stackoverflow.com/a/2704866/3622941
class FrozenDict(collections.abc.Mapping[_KT, _VT]):
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
        type: Callable[[Any], Any] | None = None,
    ) -> Any:
        """Get the first value for a key that matches the predicate.

        Args:
            key: The dictionary key to look up
            default: Value to return if key not found or no value matches predicate
            predicate: Optional callable to filter values (e.g., from inspect.getmembers)
            type: Optional callable to transform the returned value

        Returns:
            The first matching value, optionally transformed by type callable,
            or default if no match found.
        """
        try:
            values = self[key]  # type: ignore[index]
        except LookupError:
            pass
        else:
            for value in values:
                if not predicate or predicate(value):
                    return value if not type else type(value)

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
    assert match is not None
    root, path = match.groups()

    return drive, root, path


# Python 3.12+ compatibility: create flavour class or simple object
if sys.version_info >= (3, 12):
    # Python 3.12+: _flavour is a module, we create a simple object with required attributes
    class _URLFlavour:
        r"""Custom pathlib flavour for parsing URLs as filesystem paths (Python 3.12+).

        Provides required attributes and methods for pathlib compatibility:
        - sep: path separator ('/')
        - splitroot: URL parsing function
        - has_drv, is_supported: configuration flags
        - join: path joining method
        - normcase: case normalization method
        """

        sep = "/"
        altsep = None
        has_drv = True
        is_supported = True

        def splitroot(self, part: str, sep: str = "/") -> tuple[str, str, str]:
            """Split a URL into drive (scheme+netloc), root, and path components.

            Args:
                part: URL string to split
                sep: Path separator (must be '/')

            Returns:
                Tuple of (drive, root, path) where:
                - drive is 'scheme://netloc'
                - root is the leading '/' if present
                - path is the remainder with query/fragment escaped
            """
            return _url_splitroot(part, sep)

        def join(self, *paths: str | list[str]) -> str:
            """Join path components with separator.

            Args:
                *paths: Path components to join (can be individual strings or a list)

            Returns:
                Joined path string
            """
            flat_parts: list[str] = []
            for part in paths:
                if isinstance(part, list):
                    flat_parts.extend(part)
                else:
                    flat_parts.append(part)

            if not flat_parts:
                return ""

            result = flat_parts[0]

            for segment in flat_parts[1:]:
                if not segment:
                    continue

                seg_drv, seg_root, _ = _url_splitroot(segment)
                if seg_drv:
                    # Absolute URL replaces everything
                    result = segment
                    continue

                if seg_root:
                    # Absolute path keeps existing drive if present
                    res_drv, _, _ = _url_splitroot(result)
                    segment_clean = segment.replace("\\x00", "/")
                    result = res_drv + segment_clean if res_drv else segment_clean
                    continue

                res_drv, res_root, res_tail = _url_splitroot(result)
                if res_drv or res_root:
                    base_path = (res_root + res_tail).replace("\\x00", "/")
                    segment_clean = segment.replace("\\x00", "/")
                    joined = posixpath.join(base_path, segment_clean)
                    if res_drv and not joined.startswith("/"):
                        joined = "/" + joined
                    result = res_drv + joined
                else:
                    result = posixpath.join(result.replace("\\x00", "/"), segment.replace("\\x00", "/"))

            return result

        def normcase(self, path: str) -> str:
            """Normalize path case (URLs are case-sensitive).

            Args:
                path: Path to normalize

            Returns:
                Path unchanged (URLs are case-sensitive)
            """
            return path

else:
    # Python 3.9-3.11: Inherit from _PosixFlavour class
    class _URLFlavour(_PosixFlavour):
        r"""Custom pathlib flavour for parsing URLs as filesystem paths.

        Extends PosixFlavour to treat URLs as paths by:
        - Using scheme+netloc as the drive component
        - Parsing URL components (scheme, netloc, path, query, fragment)
        - Escaping '/' characters in query and fragment with \\x00
        """

        has_drv = True  # drive is scheme + netloc
        is_supported = True  # supported in all platform

        def splitroot(self, part: str, sep: str = _PosixFlavour.sep) -> tuple[str, str, str]:
            """Split a URL into drive (scheme+netloc), root, and path components.

            Args:
                part: URL string to split
                sep: Path separator (must be '/')

            Returns:
                Tuple of (drive, root, path) where:
                - drive is 'scheme://netloc'
                - root is the leading '/' if present
                - path is the remainder with query/fragment escaped
            """
            return _url_splitroot(part, sep)


class URL(urllib.parse._NetlocResultMixinStr, PurePath):
    """Object-oriented URL manipulation extending pathlib.PurePath.

    URL combines the power of pathlib's path operations with URL component
    manipulation. It provides:

    - Pathlib-style operations: joining paths with /, parent, name, suffix, etc.
    - URL components: scheme, netloc, username, password, hostname, port
    - Query string handling: form, form_fields, with_query(), add_query()
    - HTTP methods: get(), post(), put(), patch(), delete(), head(), options()
    - Immutability: all modifications return new URL instances

    Examples:
        >>> url = URL('https://user:pass@example.com:8080/path/to/file.txt?key=value#section')
        >>> url.scheme
        'https'
        >>> url.hostname
        'example.com'
        >>> str(url / 'other.txt')
        'https://user:pass@example.com:8080/path/to/other.txt?key=value#section'
        >>> str(url.with_query(foo='bar'))
        'https://user:pass@example.com:8080/path/to/file.txt?foo=bar#section'
    """

    _flavour = _URLFlavour()
    _parse_qsl_args: dict[str, Any] = {}
    _urlencode_args: dict[str, Any] = {"doseq": True}

    def __new__(cls, *args: Any) -> URL:
        """Create a new URL instance, canonicalizing arguments in Python 3.12+.

        In Python 3.12, PurePath validation is stricter. We canonicalize arguments
        (webob.Request, SplitResult, etc.) to strings before parent processing.

        Args:
            *args: URL components (strings, SplitResult, ParseResult, or webob.Request)

        Returns:
            New URL instance
        """
        if sys.version_info >= (3, 12):
            # Python 3.12: Canonicalize for stricter PurePath validation
            # Note: This happens BEFORE _parse_args, so it's not redundant
            canonicalized_args = tuple(cls._canonicalize_arg(a) for a in args)
            return super().__new__(cls, *canonicalized_args)
        else:
            # Python < 3.12: No early validation, canonicalization happens in _parse_args
            return super().__new__(cls, *args)

    def __init__(self, *args: Any) -> None:
        """Initialize URL instance.

        In Python 3.12+, PurePath.__init__ is called and we need to canonicalize args.
        Note: __init__ receives the ORIGINAL args, not the canonicalized ones from __new__.
        In Python <3.12, PurePath.__init__ is object.__init__ (does nothing).

        Args:
            *args: URL components (need to be canonicalized again for Python 3.12)
        """
        if sys.version_info >= (3, 12):
            # Python 3.12: Must canonicalize args again (__init__ gets original args)
            canonicalized_args = tuple(self._canonicalize_arg(a) for a in args)
            super().__init__(*canonicalized_args)
        # else: Python < 3.12 doesn't call parent __init__ (it's object.__init__)

    # Python 3.12 compatibility: _parts was replaced with _tail_cached
    if sys.version_info >= (3, 12):

        @property
        def _parts(self) -> list[str]:  # type: ignore[misc]
            """Compatibility property for Python 3.12+ with manual caching.

            In Python 3.12, pathlib uses _tail_cached instead of _parts. This property
            reconstructs the _parts list from _drv, _root, and _tail_cached for
            backward compatibility with pre-3.12 code.

            The result is cached in _parts_cache to avoid rebuilding on every access.
            Cache is cleared when _parts is set via the setter.

            Returns:
                List of path components, with first element containing drive+root
            """
            # Check if we have a cached value
            if hasattr(self, "_parts_cache"):
                return self._parts_cache  # type: ignore[return-value]

            self._ensure_parts_loaded()
            # In Python 3.12, the structure is: _raw_paths contains input,
            # and _tail_cached contains parsed components
            # We need to reconstruct the old _parts format: [drive_and_root, ...tail]
            # Also clean up \x00 escape in the last part (converts to /)
            parts: list[str]
            if self._drv or self._root:
                # Has drive/root: first element is drive+root
                parts = [self._drv + self._root] + list(self._tail_cached)
            else:
                # No drive/root: just the tail
                parts = list(self._tail_cached)

            # Clean up \x00 escape in last part (used to escape / in query/fragment/trailing)
            if parts:
                parts[-1] = parts[-1].replace("\\x00", "/")

            # Cache the result for future access
            object.__setattr__(self, "_parts_cache", parts)
            return parts

        @_parts.setter
        def _parts(self, value: list[str]) -> None:  # type: ignore[misc]
            """Compatibility setter for Python 3.12+.

            Converts _parts list back to _tail_cached tuple. Clears the cache
            to ensure the next read uses the new value.

            Args:
                value: New _parts list to set
            """
            # Clear the cache when setting new value
            if hasattr(self, "_parts_cache"):
                object.__delattr__(self, "_parts_cache")

            # When setting _parts, we need to update _tail_cached
            if value and (self._drv or self._root):
                # First element contains drive+root, rest is tail
                object.__setattr__(self, "_tail_cached", tuple(value[1:]))
            else:
                object.__setattr__(self, "_tail_cached", tuple(value))

    @classmethod
    def _from_parts(cls, args: Any) -> URL:
        """Create URL from parts, handling Python 3.12 changes.

        In Python 3.12, _from_parts was removed from the base class.

        Args:
            args: URL components to construct from

        Returns:
            New URL instance
        """
        if sys.version_info >= (3, 12):
            # Python 3.12 removed _from_parts, use direct construction
            ret = cls(*args)
        else:
            ret = super()._from_parts(args)
        ret._init()
        return ret

    @classmethod
    def _from_parsed_parts(cls, drv: str, root: str, parts: list[str]) -> URL:
        """Create URL from pre-parsed drive, root, and path parts.

        Python 3.12 changed this from a classmethod to an instance method,
        requiring manual instance creation and attribute setting.

        Args:
            drv: Drive component (scheme+netloc)
            root: Root component (leading '/')
            parts: List of path components

        Returns:
            New URL instance
        """
        # Python 3.12 changed _from_parsed_parts from classmethod to instance method
        # Signature changed from (drv, root, parts) to (self, drv, root, tail)
        if sys.version_info >= (3, 12):
            # In Python 3.12, we need to create an instance first and set _raw_paths
            self = object.__new__(cls)
            # Reconstruct the path string for _raw_paths
            path_str = drv + root + "/".join(parts) if parts else drv + root
            object.__setattr__(self, "_raw_paths", [path_str])
            # Now call the instance method which will set _drv, _root, _tail_cached
            super(URL, self)._from_parsed_parts(drv, root, tuple(parts))
            ret = self
        else:
            ret = super()._from_parsed_parts(drv, root, parts)
        ret._init()
        return ret

    @classmethod
    def _parse_args(cls, args: Any) -> Any:
        """Parse and canonicalize URL construction arguments.

        Converts webob.Request, SplitResult, ParseResult to strings.

        Args:
            args: Raw arguments to parse

        Returns:
            Parsed arguments suitable for parent class
        """
        return super()._parse_args(cls._canonicalize_arg(a) for a in args)

    @classmethod
    def _canonicalize_arg(cls, a: Any) -> str:
        """Convert various URL-like objects to strings.

        Handles urllib.parse result objects, webob.Request, and other types.

        Args:
            a: Argument to canonicalize (SplitResult, ParseResult, Request, etc.)

        Returns:
            String representation of the URL
        """
        if isinstance(a, urllib.parse.SplitResult):
            return urllib.parse.urlunsplit(a)

        if isinstance(a, urllib.parse.ParseResult):
            return urllib.parse.urlunparse(a)

        if webob and isinstance(a, webob.Request):
            return a.url

        if isinstance(a, str):
            return a

        if isinstance(a, bytes):
            return a.decode("utf-8")

        if hasattr(a, "__fspath__"):
            fspath = os.fspath(a)
            if isinstance(fspath, bytes):
                return fspath.decode("utf-8")
            return fspath

        # Fall back to string conversion for other objects (including URL instances)
        return str(a)

    def _ensure_parts_loaded(self) -> None:
        """Ensure internal path parts are loaded (Python 3.12+ compatibility).

        In Python 3.12, pathlib uses lazy loading. This method checks if
        _tail_cached is loaded and calls _load_parts() if needed.

        Note: We check _tail_cached instead of _parts to avoid recursion since
        _parts is a property that calls this method.
        """
        if sys.version_info >= (3, 12) and hasattr(self, "_load_parts"):
            # In Python 3.12+, _drv/_root/_tail_cached are lazy-loaded
            # Check if _tail_cached exists (not _parts to avoid recursion)
            try:
                _ = self._tail_cached  # type: ignore[attr-defined]
            except AttributeError:
                self._load_parts()  # type: ignore[attr-defined]

    def _init(self) -> None:
        r"""Initialize URL-specific attributes after construction.

        Loads parts (Python 3.12+) and cleans up escape sequences in the
        last path component (converting \x00 back to /).
        """
        # Python 3.12+: Must call _load_parts() to initialize _drv, _root, _parts
        if sys.version_info >= (3, 12) and hasattr(self, "_load_parts"):
            self._load_parts()  # type: ignore[attr-defined]

        if self._parts:
            # trick to escape '/' in query and fragment and trailing
            self._parts[-1] = self._parts[-1].replace("\\x00", "/")

    def _make_child(self, args: Any) -> URL:
        # replace by parts that have no query and have no fragment
        with patch.object(self, "_parts", list(self.parts)):
            return super()._make_child(args)

    def _handle_absolute_url_in_joinpath(
        self, canonicalized_segments: tuple[str, ...], start_index: int = 0
    ) -> tuple[bool, URL | None, int]:
        """Check if segments contain an absolute URL (with scheme).

        Args:
            canonicalized_segments: Canonicalized path segments
            start_index: Index to start checking from

        Returns:
            Tuple of (found, result_url, next_index):
            - found: True if absolute URL found
            - result_url: New URL constructed from absolute URL + remaining segments
            - next_index: Index after the absolute URL (for further processing)
        """
        for i in range(start_index, len(canonicalized_segments)):
            seg_str = canonicalized_segments[i]
            parsed = urllib.parse.urlsplit(seg_str)
            if parsed.scheme:
                # This segment has a scheme, it replaces everything
                return (True, type(self)(seg_str, *canonicalized_segments[i + 1 :]), i + 1)
        return (False, None, start_index)

    def joinpath(self, *pathsegments: Any) -> URL:
        """Join path segments to create a new URL.

        Supports various input types: strings, URLs, webob.Request objects.
        Handles absolute URLs (with scheme) and absolute paths (starting with /).

        - Absolute URLs (e.g., 'http://other.com/path') replace the entire URL
        - Absolute paths (e.g., '/root') replace the path but keep scheme/netloc
        - Relative paths are joined to the current path

        Args:
            *pathsegments: Path segments to join (strings, URLs, or webob.Request)

        Returns:
            New URL with joined paths

        Examples:
            >>> url = URL('http://example.com/path')
            >>> str(url / 'to' / 'file.txt')
            'http://example.com/path/to/file.txt'
            >>> str(url / '/absolute')
            'http://example.com/absolute'
        """
        if sys.version_info >= (3, 12):
            # Python 3.12: Manually implement join logic
            # First, canonicalize all segments (handles webob.Request, etc.)
            canonicalized_segments = tuple(self._canonicalize_arg(seg) for seg in pathsegments)

            # Check if any segment is an absolute URL (has a scheme)
            found, result, _ = self._handle_absolute_url_in_joinpath(canonicalized_segments)
            if found:
                return result  # type: ignore[return-value]

            # Check for absolute paths (starting with /)
            for seg_str in canonicalized_segments:
                if seg_str.startswith("/"):
                    # Absolute path - replace path but keep scheme/netloc
                    return type(self)(
                        urllib.parse.urlunsplit(
                            (
                                self.scheme,
                                self.netloc,
                                seg_str,
                                "",  # no query
                                "",  # no fragment
                            )
                        )
                    )

            # No absolute URLs/paths, do normal joining
            # Strip query/fragment from self first
            clean_url_str = urllib.parse.urlunsplit(
                (
                    self.scheme,
                    self.netloc,
                    self.path,
                    "",  # no query
                    "",  # no fragment
                )
            )
            # Create new URL by joining paths (use canonicalized segments)
            return type(self)(clean_url_str, *canonicalized_segments)
        else:
            return super().joinpath(*pathsegments)

    @cached_property
    def __str__(self) -> str:
        """Return string representation of the URL."""
        # NOTE: PurePath.__str__ returns '.' if path is empty.
        return urllib.parse.urlunsplit(self.components)

    @cached_property
    def __bytes__(self) -> bytes:
        """Return UTF-8 encoded bytes representation of the URL."""
        return str(self).encode("utf-8")

    # TODO: sort self.query in __hash__

    @cached_property
    def as_uri(self) -> str:
        """Return the URL as a URI string.

        Returns:
            The complete URI representation of the URL.
        """
        return str(self)

    @property
    @cached_property
    def parts(self) -> tuple[str, ...]:
        """Path components as a tuple, similar to pathlib.PurePath.parts.

        Components are decoded from percent-encoding. The first element
        is the URL root (scheme + netloc + '/') if present.

        Returns:
            Tuple of decoded path components.
        """
        self._ensure_parts_loaded()
        if self._drv or self._root:
            return tuple([self._parts[0]] + [urllib.parse.unquote(i) for i in self._parts[1:-1]] + [self.name])
        else:
            return tuple([urllib.parse.unquote(i) for i in self._parts[:-1]] + [self.name])

    @property
    @cached_property
    def components(self) -> tuple[str, str, str, str, str]:
        """All URL components as a tuple.

        Returns:
            Tuple of (scheme, netloc, path, query, fragment).
        """
        return self.scheme, self.netloc, self.path, self.query, self.fragment

    _cparts = components

    @property
    @cached_property
    def scheme(self) -> str:
        """URL scheme (e.g., 'http', 'https', 'ftp').

        Returns:
            The scheme component of the URL.
        """
        self._ensure_parts_loaded()
        return urllib.parse.urlsplit(self._drv).scheme

    @property
    @cached_property
    def netloc(self) -> str:
        """Network location (combined username, password, hostname, and port).

        Returns:
            The netloc component in the format 'user:pass@host:port'.
        """
        return netlocjoin(self.username, self.password, self.hostname, self.port)

    @property
    @cached_property
    def _userinfo(self) -> tuple[str | None, str | None]:
        self._ensure_parts_loaded()
        return urllib.parse.urlsplit(self._drv)._userinfo

    @property
    @cached_property
    def _hostinfo(self) -> tuple[str | None, int | None]:
        self._ensure_parts_loaded()
        return urllib.parse.urlsplit(self._drv)._hostinfo

    @property
    @cached_property
    def hostinfo(self) -> str:
        """Hostname and port combined (excluding username and password).

        Returns:
            The hostinfo in the format 'host:port'.
        """
        return netlocjoin(None, None, self.hostname, self.port)

    @property
    @cached_property
    def username(self) -> str | None:
        """Username from the URL's authentication section.

        Automatically decodes percent-encoded usernames.

        Returns:
            The decoded username, or None if not present.
        """
        # NOTE: username and password can be encoded by percent-encoding.
        #       http://%75%73%65%72:%70%61%73%73%77%64@httpbin.org/basic-auth/user/passwd
        result = super().username
        if result is not None:
            result = urllib.parse.unquote(result)
        return result

    @property
    @cached_property
    def password(self) -> str | None:
        """Password from the URL's authentication section.

        Automatically decodes percent-encoded passwords.

        Returns:
            The decoded password, or None if not present.
        """
        result = super().password
        if result is not None:
            result = urllib.parse.unquote(result)
        return result

    @property
    @cached_property
    def hostname(self) -> str | None:
        """Hostname from the URL.

        Automatically decodes internationalized domain names (IDN) from punycode.

        Returns:
            The decoded hostname, or None if not present.
        """
        import contextlib

        result = super().hostname
        if result is not None:
            with contextlib.suppress(UnicodeEncodeError):
                result = result.encode("ascii").decode("idna")
        return result

    @property
    @cached_property
    def path(self) -> str:
        """URL path component, including trailing separator if present.

        Properly encodes path characters according to RFC 3986.

        Returns:
            The percent-encoded path string with trailing separator preserved.
        """
        # https://tools.ietf.org/html/rfc3986#appendix-A
        safe_pchars = "-._~!$&'()*+,;=:@"

        self._ensure_parts_loaded()
        begin = 1 if self._drv or self._root else 0

        # Decode parts before encoding to avoid double-encoding
        parts = [urllib.parse.unquote(i) for i in self._parts[begin:-1]] + [self.name]

        return (
            self._root
            + self._flavour.sep.join(urllib.parse.quote(i, safe=safe_pchars) for i in parts)
            + self.trailing_sep
        )

    @property
    @cached_property
    def _name_parts(self) -> tuple[str, str, str]:
        """Parse super().name into (path, query, fragment) without using urlsplit.

        We can't use urlsplit here because it treats colons as scheme separators,
        which breaks filenames like 'abc:def.html'.

        Parsing order: fragment first (after #), then query (after ?), then path.

        Returns:
            Tuple of (path, query, fragment) strings.
        """
        full_name = super().name
        # In Python 3.12, super().name may have \x00 escape, clean it up
        if sys.version_info >= (3, 12):
            full_name = full_name.replace("\\x00", "/")

        # Fragment takes priority - everything after # is fragment
        fragment_idx = full_name.find("#")
        if fragment_idx != -1:
            fragment = full_name[fragment_idx + 1 :]
            before_fragment = full_name[:fragment_idx]
        else:
            fragment = ""
            before_fragment = full_name

        # Query is everything after ? (but before #)
        query_idx = before_fragment.find("?")
        if query_idx != -1:
            query = before_fragment[query_idx + 1 :]
            path = before_fragment[:query_idx]
        else:
            query = ""
            path = before_fragment

        return path, query, fragment

    @property
    @cached_property
    def name(self) -> str:
        """Final path component (filename), decoded and without query/fragment.

        Returns:
            The decoded filename or last path segment.
        """
        return urllib.parse.unquote(self._name_parts[0].rstrip(self._flavour.sep))

    @property
    @cached_property
    def query(self) -> str:
        """Query string component of the URL.

        Returns:
            The raw query string (without the leading '?').
        """
        return self._name_parts[1]

    @property
    @cached_property
    def fragment(self) -> str:
        """Fragment identifier component of the URL.

        Returns:
            The fragment string (without the leading '#').
        """
        return self._name_parts[2]

    @property
    @cached_property
    def trailing_sep(self) -> str:
        """Trailing separator characters from the path.

        Returns:
            The trailing '/' characters, or empty string if none.
        """
        match = re.search("(" + re.escape(self._flavour.sep) + "*)$", self._name_parts[0])
        assert match is not None
        return match.group(0)

    @property
    @cached_property
    def form_fields(self) -> tuple[tuple[str, str], ...]:
        """Query string parsed as a tuple of (key, value) pairs.

        Uses urllib.parse.parse_qsl for parsing, preserving order and duplicates.

        Returns:
            Tuple of (name, value) tuples from the query string.
        """
        return tuple(urllib.parse.parse_qsl(self.query, **self._parse_qsl_args))

    @property
    @cached_property
    def form(self) -> FrozenMultiDict:
        """Query string parsed as an immutable multi-value dictionary.

        Keys with multiple values are stored as tuples. Useful for accessing
        query parameters by name.

        Returns:
            FrozenMultiDict mapping parameter names to tuples of values.
        """
        return FrozenMultiDict(
            {k: tuple(v) for k, v in urllib.parse.parse_qs(self.query, **self._parse_qsl_args).items()}
        )

    def with_name(self, name: str) -> URL:
        """Return a new URL with the filename changed.

        Args:
            name: The new filename (automatically percent-encoded)

        Returns:
            A new URL instance with the modified filename.
        """
        return super().with_name(urllib.parse.quote(name, safe=""))

    def with_suffix(self, suffix: str) -> URL:
        """Return a new URL with the file suffix changed or added.

        Args:
            suffix: The new suffix including the dot (e.g., '.txt')

        Returns:
            A new URL instance with the modified suffix.
        """
        return super().with_suffix(urllib.parse.quote(suffix, safe="."))

    def with_components(
        self,
        *,
        scheme: Any = missing,
        netloc: Any = missing,
        username: Any = missing,
        password: Any = missing,
        hostname: Any = missing,
        port: Any = missing,
        path: Any = missing,
        name: Any = missing,
        query: Any = missing,
        fragment: Any = missing,
    ) -> URL:
        """Return a new URL with specified components changed.

        All arguments are keyword-only. Omitted arguments retain their current values.
        You can specify either netloc OR (username, password, hostname, port), not both.
        You can specify either path OR name, not both.

        Args:
            scheme: New scheme (e.g., 'https')
            netloc: New network location as a string
            username: New username (mutually exclusive with netloc)
            password: New password (mutually exclusive with netloc)
            hostname: New hostname (mutually exclusive with netloc)
            port: New port number (mutually exclusive with netloc)
            path: New path (mutually exclusive with name)
            name: New filename (mutually exclusive with path)
            query: New query string (str, dict, or list of tuples)
            fragment: New fragment identifier

        Returns:
            A new URL instance with the specified components modified.
        """
        if scheme is missing:
            scheme = self.scheme
        elif scheme is not None and not isinstance(scheme, str):
            scheme = str(scheme)

        if username is not missing or password is not missing or hostname is not missing or port is not missing:
            assert netloc is missing

            if username is missing:
                username = self.username
            elif username is not None and not isinstance(username, str):
                username = str(username)

            if password is missing:
                password = self.password
            elif password is not None and not isinstance(password, str):
                password = str(password)

            if hostname is missing:
                hostname = self.hostname
            elif hostname is not None and not isinstance(hostname, str):
                hostname = str(hostname)

            if port is missing:
                port = self.port

            netloc = netlocjoin(username, password, hostname, port)

        elif netloc is missing:
            netloc = self.netloc

        elif netloc is not None and not isinstance(netloc, str):
            netloc = str(netloc)

        if name is not missing:
            assert path is missing

            if not isinstance(name, str):
                name = str(name)

            path = urllib.parse.urljoin(self.path.rstrip(self._flavour.sep), urllib.parse.quote(name, safe=""))

        elif path is missing:
            path = self.path

        elif path is not None and not isinstance(path, str):
            path = str(path)

        if query is missing:
            query = self.query
        elif isinstance(query, collections.abc.Mapping):
            query = urllib.parse.urlencode(sorted(query.items()), **self._urlencode_args)
        elif isinstance(query, str):
            # TODO: Is escaping '#' required?
            # query = query.replace('#', '%23')
            pass
        elif isinstance(query, collections.abc.Sequence):
            query = urllib.parse.urlencode(query, **self._urlencode_args)
        elif query is not None:
            query = str(query)

        if fragment is missing:
            fragment = self.fragment
        elif fragment is not None and not isinstance(fragment, str):
            fragment = str(fragment)

        return self.__class__(urllib.parse.urlunsplit((scheme, netloc, path, query, fragment)))

    def with_scheme(self, scheme: Any) -> URL:
        """Return a new URL with the scheme changed.

        Args:
            scheme: New scheme (e.g., 'https', 'ftp')

        Returns:
            A new URL instance with the modified scheme.
        """
        return self.with_components(scheme=scheme)

    def with_netloc(self, netloc: Any) -> URL:
        """Return a new URL with the network location changed.

        Args:
            netloc: New netloc in format 'user:pass@host:port'

        Returns:
            A new URL instance with the modified netloc.
        """
        return self.with_components(netloc=netloc)

    def with_userinfo(self, username: Any, password: Any) -> URL:
        """Return a new URL with username and password changed.

        Args:
            username: New username
            password: New password

        Returns:
            A new URL instance with modified credentials.
        """
        return self.with_components(username=username, password=password)

    def with_hostinfo(self, hostname: Any, port: int | None = None) -> URL:
        """Return a new URL with hostname and port changed.

        Args:
            hostname: New hostname
            port: New port number (optional)

        Returns:
            A new URL instance with modified host information.
        """
        return self.with_components(hostname=hostname, port=port)

    def with_query(self, query: Any = None, **kwargs: Any) -> URL:
        """Return a new URL with the query string replaced.

        Args:
            query: New query as dict, list of tuples, or string
            **kwargs: Alternative way to specify query as keyword arguments

        Returns:
            A new URL instance with the modified query string.
        """
        assert not (query and kwargs)
        return self.with_components(query=query or kwargs)

    def add_query(self, query: Any = None, **kwargs: Any) -> URL:
        """Return a new URL with query parameters appended to existing query.

        Args:
            query: Additional query as dict, list of tuples, or string
            **kwargs: Alternative way to specify additional query parameters

        Returns:
            A new URL instance with query parameters added.
        """
        assert not (query and kwargs)
        query = query or kwargs
        if not query:
            return self.with_components()
        current = self.query
        if not current:
            return self.with_components(query=query)
        appendix = ""  # suppress lint warnings
        if isinstance(query, collections.abc.Mapping):
            appendix = urllib.parse.urlencode(sorted(query.items()), **self._urlencode_args)
        elif isinstance(query, collections.abc.Sequence):
            appendix = urllib.parse.urlencode(query, **self._urlencode_args)
        elif query is not None:
            appendix = str(query)
        if appendix:
            new = f"{current}&{appendix}"
            return self.with_components(query=new)
        return self.with_components()

    def with_fragment(self, fragment: Any) -> URL:
        """Return a new URL with the fragment identifier changed.

        Args:
            fragment: New fragment identifier (without the '#')

        Returns:
            A new URL instance with the modified fragment.
        """
        return self.with_components(fragment=fragment)

    def resolve(self) -> URL:
        """Resolve relative path components ('.' and '..').

        Returns:
            A new URL with normalized path (no relative components).
        """
        self._ensure_parts_loaded()
        path: list[str] = []

        for part in self.parts[1:] if self._drv or self._root else self.parts:
            if part == "." or part == "":
                pass
            elif part == "..":
                if path:
                    del path[-1]
            else:
                path.append(part)

        if self._root:
            path.insert(0, self._root.rstrip(self._flavour.sep))

        path_str = self._flavour.join(path)
        return self.__class__(urllib.parse.urlunsplit((self.scheme, self.netloc, path_str, self.query, self.fragment)))

    @property
    def jailed(self) -> JailedURL:
        """Create a JailedURL with this URL as both the current and root URL."""
        return JailedURL(self, root=self)

    def get(self, params: Any = None, **kwargs: Any) -> requests.Response:
        """Send a GET request to this URL.

        Args:
            params: Dictionary or bytes to send in the query string
            **kwargs: Additional arguments passed to requests.get()

        Returns:
            requests.Response object from the GET request.
        """
        url = str(self)
        response = requests.get(url, params, **kwargs)
        return response

    def options(self, **kwargs: Any) -> requests.Response:
        """Send an OPTIONS request to this URL.

        Args:
            **kwargs: Additional arguments passed to requests.options()

        Returns:
            requests.Response object from the OPTIONS request.
        """
        url = str(self)
        return requests.options(url, **kwargs)

    def head(self, **kwargs: Any) -> requests.Response:
        """Send a HEAD request to this URL.

        Args:
            **kwargs: Additional arguments passed to requests.head()

        Returns:
            requests.Response object from the HEAD request.
        """
        url = str(self)
        return requests.head(url, **kwargs)

    def post(self, data: Any = None, json: Any = None, **kwargs: Any) -> requests.Response:
        """Send a POST request to this URL.

        Args:
            data: Dictionary, bytes, or file-like object to send in the request body
            json: JSON data to send in the request body
            **kwargs: Additional arguments passed to requests.post()

        Returns:
            requests.Response object from the POST request.
        """
        url = str(self)
        return requests.post(url, data=data, json=json, **kwargs)

    def put(self, data: Any = None, **kwargs: Any) -> requests.Response:
        """Send a PUT request to this URL.

        Args:
            data: Dictionary, bytes, or file-like object to send in the request body
            **kwargs: Additional arguments passed to requests.put()

        Returns:
            requests.Response object from the PUT request.
        """
        url = str(self)
        return requests.put(url, data=data, **kwargs)

    def patch(self, data: Any = None, **kwargs: Any) -> requests.Response:
        """Send a PATCH request to this URL.

        Args:
            data: Dictionary, bytes, or file-like object to send in the request body
            **kwargs: Additional arguments passed to requests.patch()

        Returns:
            requests.Response object from the PATCH request.
        """
        url = str(self)
        return requests.patch(url, data=data, **kwargs)

    def delete(self, **kwargs: Any) -> requests.Response:
        """Send a DELETE request to this URL.

        Args:
            **kwargs: Additional arguments passed to requests.delete()

        Returns:
            requests.Response object from the DELETE request.
        """
        url = str(self)
        return requests.delete(url, **kwargs)

    def get_text(self, name: str = "", query: Any = "", pattern: Any = "", overwrite: bool = False) -> Any:
        """Execute a GET request and return text response, optionally filtered.

        Args:
            name: Path segment to append before making request
            query: Query parameters to add or replace
            pattern: Regex pattern (str or compiled) to filter response lines
            overwrite: If True, replace query; if False, amend existing query

        Returns:
            Response text as string, or list of matching lines if pattern provided.
        """
        q = query if overwrite else self.add_query(query).query if query else self.query
        url = self.joinpath(name) if name else self
        res = url.with_query(q).get()

        if res:
            if pattern:
                if isinstance(pattern, str):  # patterns should be a compiled transformer like a regex object
                    pattern = re.compile(pattern)

                return list(filter(pattern.match, res.text.split("\n")))

            return res.text

        return res

    def get_json(self, name: str = "", query: Any = "", keys: Any = "", overwrite: bool = False) -> Any:
        """Execute a GET request and return JSON response, optionally filtered with JMESPath.

        Args:
            name: Path segment to append before making request
            query: Query parameters to add or replace
            keys: JMESPath expression (str or compiled) to extract data from JSON
            overwrite: If True, replace query; if False, amend existing query

        Returns:
            Parsed JSON response, or JMESPath-filtered result if keys provided.

        Raises:
            ImportError: If keys is provided but jmespath is not installed.
        """
        q = query if overwrite else self.add_query(query).query if query else self.query
        url = self.joinpath(name) if name else self
        res = url.with_query(q).get()

        if res and keys:
            if not jmespath:
                raise ImportError("jmespath is not installed")

            if isinstance(keys, str):  # keys should be a compiled transformer like a jamespath object
                keys = jmespath.compile(keys)

            return keys.search(res.json())

        return res.json()


class JailedURL(URL):
    """URL that is restricted to stay within a root URL path (sandboxed).

    JailedURL ensures all path operations stay within the specified root,
    preventing navigation outside the jail via '..' or absolute paths.
    Useful for security-sensitive applications or URL templating.

    Examples:
        >>> root = URL('http://example.com/app/')
        >>> jail = JailedURL('http://example.com/app/content', root=root)
        >>> str(jail / '../../escape')  # Stays within /app/
        'http://example.com/app/'
        >>> str(jail / '/absolute')  # Absolute paths relative to root
        'http://example.com/app/absolute'

    Attributes:
        _chroot: The root URL that constrains all operations
    """

    _chroot: URL | None = None  # Dynamically set by __new__, will be URL when methods run

    def __new__(cls, *args: Any, root: Any = None) -> JailedURL:
        if root is not None:
            root = URL(root)
        elif cls._chroot is not None:
            # This is reachable when __new__ is called on dynamically created subclasses
            root = cls._chroot
        elif webob and len(args) >= 1 and isinstance(args[0], webob.Request):
            root = URL(args[0].application_url)
        else:
            root = URL(*args)

        assert root.scheme and root.netloc and not root.query and not root.fragment, f"malformed root: {root}"

        if not root.path:
            root = root / "/"

        return type(cls.__name__, (cls,), {"_chroot": root})._from_parts(args)

    def __init__(self, *args: Any, root: Any = None) -> None:
        """Override __init__ to consume the root keyword argument.

        In Python 3.12, PurePath.__init__ doesn't accept keyword arguments,
        so we need to consume them here and canonicalize args.

        Args:
            *args: URL arguments (need canonicalization in Python 3.12)
            root: The root URL (handled in __new__)
        """
        # The root argument is already handled in __new__
        # In Python < 3.12, PurePath.__init__ does nothing, so we can't pass args
        # In Python 3.12, we need to canonicalize and pass args (without root kwarg)
        if sys.version_info >= (3, 12):
            # Must canonicalize args (__init__ receives original args)
            canonicalized_args = tuple(self._canonicalize_arg(a) for a in args)
            super().__init__(*canonicalized_args)
        # else: do nothing, PurePath.__init__ is object.__init__ which takes no args

    @classmethod
    def _from_parts(cls, args: Any) -> URL:
        """Override _from_parts to avoid recursion in JailedURL.__new__.

        In Python 3.12, calling cls(*args) would trigger __new__ which creates
        a dynamic subclass and calls _from_parts again, causing infinite recursion.
        Instead, we use object.__new__ directly.
        """
        if sys.version_info >= (3, 12):
            # Create instance using object.__new__ to bypass __new__
            self = object.__new__(cls)
            # Set _raw_paths which is required for _load_parts
            # Canonicalize args (handles webob.Request, etc.)
            if args:
                object.__setattr__(self, "_raw_paths", [cls._canonicalize_arg(arg) for arg in args])
            else:
                object.__setattr__(self, "_raw_paths", [])
            # Copy _chroot from the class if it exists
            if hasattr(cls, "_chroot"):
                object.__setattr__(self, "_chroot", cls._chroot)
            self._init()
            return self
        else:
            # Python < 3.12: Use parent implementation
            ret = super()._from_parts(args)
            ret._init()
            return ret

    def _make_child(self, args: Any) -> URL:
        drv, root, parts = self._parse_args(args)
        chroot = self._chroot
        assert chroot is not None  # Always set by __new__

        if drv:
            # check in _init
            pass

        elif root:
            drv, root, parts = chroot._drv, chroot._root, list(chroot.parts) + parts[1:]

        else:
            drv, root, parts = chroot._drv, chroot._root, list(self.parts) + parts

        return self._from_parsed_parts(drv, root, parts)

    def joinpath(self, *pathsegments: Any) -> JailedURL:
        """Join path segments to create a new jailed URL.

        For JailedURL, behavior differs from regular URL for security:
        - Absolute paths (starting with /) are relative to the chroot, not the domain
        - Full URLs (with scheme) are accepted but will be constrained to chroot in _init
        - Navigation outside the jail (via '..') is prevented by _init

        Args:
            *pathsegments: Path segments to join (strings, URLs, or webob.Request)

        Returns:
            New jailed URL with joined paths, constrained within the jail

        Examples:
            >>> root = URL('http://example.com/app/')
            >>> jail = JailedURL('http://example.com/app/content', root=root)
            >>> str(jail / '/data')  # Absolute path is relative to /app/
            'http://example.com/app/data'
            >>> str(jail / '../../escape')  # Prevented by _init
            'http://example.com/app/'
        """
        if sys.version_info >= (3, 12):
            chroot = self._chroot
            assert chroot is not None  # Always set by __new__

            # Canonicalize all segments (handles webob.Request, etc.)
            canonicalized_segments = tuple(self._canonicalize_arg(seg) for seg in pathsegments)

            # Check if any segment is an absolute URL (has a scheme)
            # Reuse parent's helper method for absolute URL detection
            found, result, _ = self._handle_absolute_url_in_joinpath(canonicalized_segments)
            if found:
                return result  # type: ignore[return-value]

            # Check for absolute paths (starting with /)
            # For jailed URLs, these are relative to chroot, not domain
            for i, seg_str in enumerate(canonicalized_segments):
                if seg_str.startswith("/"):
                    # Absolute path - join to chroot instead of self
                    chroot_url_str = urllib.parse.urlunsplit(
                        (
                            chroot.scheme,
                            chroot.netloc,
                            chroot.path,
                            "",  # no query
                            "",  # no fragment
                        )
                    )
                    # Join the absolute path (with / stripped) to chroot
                    return type(self)(chroot_url_str, seg_str.lstrip("/"), *canonicalized_segments[i + 1 :])

            # No absolute paths, do normal joining
            clean_url_str = urllib.parse.urlunsplit(
                (
                    self.scheme,
                    self.netloc,
                    self.path,
                    "",  # no query
                    "",  # no fragment
                )
            )
            return type(self)(clean_url_str, *canonicalized_segments)
        else:
            # Python < 3.12: use _make_child which handles jailed logic
            result: JailedURL = super().joinpath(*pathsegments)  # type: ignore[assignment]
            return result

    def _init(self) -> None:
        # Python 3.12+: Must call _load_parts() to initialize _drv, _root, _parts
        if sys.version_info >= (3, 12) and hasattr(self, "_load_parts"):
            self._load_parts()  # type: ignore[attr-defined]

        chroot = self._chroot
        assert chroot is not None  # Always set by __new__

        if self._parts[: len(chroot.parts)] != list(chroot.parts):  # type: ignore[has-type]
            self._drv, self._root, self._parts = chroot._drv, chroot._root, chroot._parts[:]
            # Python 3.12: Also update _raw_paths to reflect the corrected path
            if sys.version_info >= (3, 12):
                # Use the string representation of chroot as the new path
                object.__setattr__(self, "_raw_paths", [str(chroot)])
                # Clear _parts_cache since we updated _parts
                if hasattr(self, "_parts_cache"):
                    object.__delattr__(self, "_parts_cache")
                # Clear other cached properties that depend on the path
                if hasattr(self, "_str"):
                    object.__delattr__(self, "_str")
                if hasattr(self, "_tail_cached"):
                    object.__setattr__(self, "_tail_cached", tuple(chroot._parts))

        super()._init()

    def resolve(self) -> URL:
        """Resolve relative path components (like '..') within the jail.

        Creates a fake filesystem-like structure where the chroot appears as the
        root directory. This allows pathlib's resolve() to process '..' correctly
        while keeping the result within the jail boundaries.

        In Python 3.12, we patch _parts_cache directly to avoid issues with the
        cached property returning incorrect values based on the real _drv/_root.

        Returns:
            Resolved URL with '..' components processed, staying within chroot
        """
        chroot = self._chroot
        assert chroot is not None  # Always set by __new__

        if sys.version_info >= (3, 12):
            # Python 3.12: _parts is a property computed from _drv, _root, _tail_cached
            # The resolve logic for jailed URLs needs _parts to look like:
            # ["http://example.com/app/", "path", "to", "content", "..", "file"]
            # This maps to:
            # - _drv = "" (empty, no URL scheme/netloc drive)
            # - _root = "http://example.com/app/" (the chroot as a fake filesystem root)
            # - _tail_cached = ("path", "to", "content", "..", "file")
            chroot_root_str = "".join(chroot._parts)  # Join chroot parts into one string
            tail_parts = self._parts[len(chroot.parts) :]  # Get parts after chroot

            # Build the _parts list that resolve() expects
            fake_parts = [chroot_root_str] + tail_parts

            with (
                patch.object(self, "_drv", ""),
                patch.object(self, "_root", chroot_root_str),
                patch.object(self, "_tail_cached", tuple(tail_parts)),
                patch.object(self, "_parts_cache", fake_parts),  # Directly patch the cache
            ):
                return super().resolve()
        else:
            with (
                patch.object(self, "_root", chroot.path),
                patch.object(self, "_parts", ["".join(chroot._parts)] + self._parts[len(chroot._parts) :]),
            ):
                return super().resolve()

    @property
    def chroot(self) -> URL:
        assert self._chroot is not None  # Always set by __new__
        return self._chroot
