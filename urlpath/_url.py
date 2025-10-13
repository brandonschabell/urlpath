"""Main URL class implementation."""

from __future__ import annotations

__all__ = ("URL", "JailedURL")

import collections.abc
import contextlib
import os
import posixpath
import re
import urllib.parse
from pathlib import PurePath
from typing import Any
from unittest.mock import patch

import requests

from ._compat import IS_PY312_PLUS
from ._flavour import _URLFlavour
from ._utils import FrozenMultiDict, cached_property, cleanup_escapes, netlocjoin

try:
    import jmespath
except ImportError:
    jmespath = None

try:
    import webob
except ImportError:
    webob = None

missing = object()


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
        canonicalized_args = tuple(cls._canonicalize_arg(a) for a in args)

        if len(canonicalized_args) > 1:
            canonicalized_args = cls._combine_args(canonicalized_args)

        if IS_PY312_PLUS:
            # Python 3.12: Canonicalize for stricter PurePath validation
            # Note: This happens BEFORE _parse_args, so it's not redundant
            return super().__new__(cls, *canonicalized_args)

        # Python < 3.12: Parent class will still invoke _parse_args, but we feed it
        # the canonicalized arguments so multi-argument construction matches joinpath.
        return super().__new__(cls, *canonicalized_args)

    def __init__(self, *args: Any) -> None:
        """Initialize URL instance.

        In Python 3.12+, PurePath.__init__ is called and we need to canonicalize args.
        Note: __init__ receives the ORIGINAL args, not the canonicalized ones from __new__.
        In Python <3.12, PurePath.__init__ is object.__init__ (does nothing).

        Args:
            *args: URL components (need to be canonicalized again for Python 3.12)
        """
        if IS_PY312_PLUS:
            # Python 3.12: Must canonicalize args again (__init__ gets original args)
            canonicalized_args = tuple(self._canonicalize_arg(a) for a in args)
            if len(canonicalized_args) > 1:
                combined = type(self)._combine_args(canonicalized_args)
                super().__init__(*combined)
            else:
                super().__init__(*canonicalized_args)
        # else: Python < 3.12 doesn't call parent __init__ (it's object.__init__)

    @classmethod
    def _combine_args(cls, canonicalized_args: tuple[str, ...]) -> tuple[str, ...]:
        """Combine raw constructor arguments to emulate legacy joining semantics."""
        if not canonicalized_args:
            return canonicalized_args

        current = canonicalized_args[0]
        for seg in canonicalized_args[1:]:
            parsed_current = urllib.parse.urlsplit(current)
            parsed_segment = urllib.parse.urlsplit(seg)

            if parsed_segment.scheme:
                current = cleanup_escapes(urllib.parse.urlunsplit(parsed_segment))
                continue

            if seg.startswith("/"):
                current = cleanup_escapes(
                    urllib.parse.urlunsplit(
                        (
                            parsed_current.scheme,
                            parsed_current.netloc,
                            parsed_segment.path or seg,
                            parsed_segment.query,
                            parsed_segment.fragment,
                        )
                    )
                )
                continue

            base_path = parsed_current.path or ("/" if parsed_current.netloc else "")
            joined_path = posixpath.join(base_path, seg)
            if joined_path == ".":
                joined_path = ""
            else:
                parts = joined_path.split("/")
                if "." in parts:
                    joined_path = "/".join(part for part in parts if part != ".")
            current = cleanup_escapes(
                urllib.parse.urlunsplit(
                    (
                        parsed_current.scheme,
                        parsed_current.netloc,
                        joined_path,
                        "",
                        "",
                    )
                )
            )

        return (cleanup_escapes(current),)

    if IS_PY312_PLUS:

        @classmethod
        def _parse_path(cls, path: str) -> tuple[str, str, list[str]]:
            r"""Parse a URL path into drive, root, and tail components.

            Python 3.13 switched pathlib to the new PurePath implementation that
            delegates parsing to ``os.path``. That behaviour breaks our URL
            handling, so we hook into the new extension point and reuse the URL
            flavour logic that previously powered ``_parse_parts``.

            Args:
                path: Raw path string produced from ``_raw_paths``.

            Returns:
                Tuple of ``(drive, root, tail_parts)`` where the tail preserves
                escaped ``"/"`` characters via ``"\x00"`` markers exactly like
                the historical implementation.
            """
            if not path:
                return "", "", []

            drv, root, tail = cls._flavour.splitroot(path)

            if not tail:
                tail_parts: list[str] = []
            else:
                tail_parts = [part for part in tail.split(cls._flavour.sep) if part]

            return drv, root, tail_parts

    # Python 3.12 compatibility: _parts was replaced with _tail_cached
    if IS_PY312_PLUS:

        @property
        def _parts(self) -> list[str]:
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
                return self._parts_cache

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
                parts[-1] = cleanup_escapes(parts[-1])

            # Cache the result for future access
            object.__setattr__(self, "_parts_cache", parts)
            return parts

        @_parts.setter
        def _parts(self, value: list[str]) -> None:
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
            tail_parts = list(value[1:]) if value and (self._drv or self._root) else list(value)

            object.__setattr__(self, "_tail_cached", tail_parts)
            tail_attr = getattr(type(self), "_tail", None)
            if not isinstance(tail_attr, property):
                object.__setattr__(self, "_tail", tail_parts)

    @classmethod
    def _from_parts(cls, args: Any) -> URL:
        """Create URL from parts, handling Python 3.12 changes.

        In Python 3.12, _from_parts was removed from the base class.

        Args:
            args: URL components to construct from

        Returns:
            New URL instance
        """
        ret = cls(*args) if IS_PY312_PLUS else super()._from_parts(args)
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
        if IS_PY312_PLUS:
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
        canonicalized = tuple(cls._canonicalize_arg(a) for a in args)
        if len(canonicalized) > 1:
            canonicalized = cls._combine_args(canonicalized)
        return super()._parse_args(canonicalized)

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

    def _bootstrap_legacy_parts(self) -> None:
        """Populate pathlib 3.11-style attributes when they are missing.

        Python 3.13 no longer materialises ``_drv``/``_root``/``_parts`` eagerly,
        but the rest of this module still expects them to be present. We rebuild
        those attributes from ``_raw_paths`` so existing logic keeps working.
        """
        if hasattr(self, "_drv"):
            return

        raw_paths = getattr(self, "_raw_paths", None)
        if not raw_paths:
            return

        raw_path = raw_paths[0]
        drv, root, tail = self._flavour.splitroot(raw_path)

        parts: list[str] = []
        if drv or root:
            parts.append(drv + root)

        if tail:
            parts.extend(tail.split(self._flavour.sep))

        object.__setattr__(self, "_drv", drv)
        object.__setattr__(self, "_root", root)
        object.__setattr__(self, "_parts", parts)

    def _ensure_parts_loaded(self) -> None:
        """Ensure internal path parts are available across Python versions."""
        if IS_PY312_PLUS:
            if hasattr(self, "_load_parts"):
                try:
                    _ = self._tail_cached
                except AttributeError:
                    self._load_parts()
            else:
                self._bootstrap_legacy_parts()

    def _init(self) -> None:
        r"""Initialize URL-specific attributes after construction.

        Loads parts (Python 3.12+) and cleans up escape sequences in the
        last path component (converting \x00 back to /).
        """
        self._ensure_parts_loaded()

        if self._parts:
            # trick to escape '/' in query and fragment and trailing
            self._parts[-1] = cleanup_escapes(self._parts[-1])

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
        if IS_PY312_PLUS:
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

            # No absolute URLs/paths, do manual joining to match legacy pathlib
            base_path = self.path
            if not base_path and self.netloc:
                base_path = "/"

            joined_path = base_path
            for seg_str in canonicalized_segments:
                if not seg_str:
                    continue
                joined_path = posixpath.join(joined_path, seg_str)

            clean_url_str = urllib.parse.urlunsplit(
                (
                    self.scheme,
                    self.netloc,
                    joined_path,
                    "",  # drop query for child joins
                    "",  # drop fragment for child joins
                )
            )

            return type(self)(clean_url_str)
        else:
            return super().joinpath(*pathsegments)

    if IS_PY312_PLUS:

        def __truediv__(self, key: Any) -> URL:
            """Ensure the / operator reuses joinpath on Python 3.12+."""
            return self.joinpath(key)

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
        decoded_name = urllib.parse.unquote(self.name)
        parts = [urllib.parse.unquote(i) for i in self._parts[begin:-1]] + [decoded_name]

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
        if IS_PY312_PLUS:
            full_name = cleanup_escapes(full_name)

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
        quoted_suffix = urllib.parse.quote(suffix, safe=".")
        return super().with_suffix(quoted_suffix)

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
        if IS_PY312_PLUS:
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
        if IS_PY312_PLUS:
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
        if IS_PY312_PLUS:
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
                            "",
                            "",
                        )
                    )
                    joined = type(self)._combine_args(
                        (chroot_url_str, seg_str.lstrip("/"), *canonicalized_segments[i + 1 :])
                    )
                    return type(self)(*joined)

            # No absolute paths, do normal joining
            clean_url_str = urllib.parse.urlunsplit(
                (
                    self.scheme,
                    self.netloc,
                    self.path,
                    "",
                    "",
                )
            )
            joined = type(self)._combine_args((clean_url_str, *canonicalized_segments))
            return type(self)(*joined)
        else:
            # Python < 3.12: use _make_child which handles jailed logic
            result = super().joinpath(*pathsegments)
            return result  # type: ignore[return-value]

    def _init(self) -> None:
        # Python 3.12+: Must call _load_parts() to initialize _drv, _root, _parts
        if IS_PY312_PLUS and hasattr(self, "_load_parts"):
            self._load_parts()

        chroot = self._chroot
        assert chroot is not None  # Always set by __new__

        if self._parts[: len(chroot.parts)] != list(chroot.parts):
            self._drv, self._root, self._parts = chroot._drv, chroot._root, chroot._parts[:]
            if IS_PY312_PLUS:
                object.__setattr__(self, "_raw_paths", [str(chroot)])
                if hasattr(self, "_parts_cache"):
                    object.__delattr__(self, "_parts_cache")
                if hasattr(self, "_str"):
                    object.__delattr__(self, "_str")
                tail_parts = list(chroot._parts[1:]) if len(chroot._parts) > 1 else []
                object.__setattr__(self, "_tail_cached", tail_parts)
                tail_attr = getattr(type(self), "_tail", None)
                if not isinstance(tail_attr, property):
                    object.__setattr__(self, "_tail", tail_parts)

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

        if IS_PY312_PLUS:
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
