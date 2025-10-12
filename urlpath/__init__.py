"""Object-oriented URL from `urllib.parse` and `pathlib`."""

from __future__ import annotations

__all__ = ("URL",)

import collections.abc
import functools
import re
import urllib.parse
from collections.abc import Iterator
from pathlib import PurePath, _PosixFlavour
from typing import Any, Callable, TypeVar
from unittest.mock import patch

import requests

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
        assert sep == self.sep
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

    @classmethod
    def _from_parts(cls, args: Any) -> URL:
        ret = super()._from_parts(args)
        ret._init()
        return ret

    @classmethod
    def _from_parsed_parts(cls, drv: str, root: str, parts: list[str]) -> URL:
        ret = super()._from_parsed_parts(drv, root, parts)
        ret._init()
        return ret

    @classmethod
    def _parse_args(cls, args: Any) -> Any:
        return super()._parse_args(cls._canonicalize_arg(a) for a in args)

    @classmethod
    def _canonicalize_arg(cls, a: Any) -> str:
        if isinstance(a, urllib.parse.SplitResult):
            return urllib.parse.urlunsplit(a)

        if isinstance(a, urllib.parse.ParseResult):
            return urllib.parse.urlunparse(a)

        if webob and isinstance(a, webob.Request):
            return a.url

        return a

    def _init(self) -> None:
        if self._parts:
            # trick to escape '/' in query and fragment and trailing
            self._parts[-1] = self._parts[-1].replace("\\x00", "/")

    def _make_child(self, args: Any) -> URL:
        # replace by parts that have no query and have no fragment
        with patch.object(self, "_parts", list(self.parts)):
            return super()._make_child(args)

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
        return urllib.parse.urlsplit(self._drv)._userinfo

    @property
    @cached_property
    def _hostinfo(self) -> tuple[str | None, int | None]:
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

    def _init(self) -> None:
        chroot = self._chroot
        assert chroot is not None  # Always set by __new__

        if self._parts[: len(chroot.parts)] != list(chroot.parts):  # type: ignore[has-type]
            self._drv, self._root, self._parts = chroot._drv, chroot._root, chroot._parts[:]

        super()._init()

    def resolve(self) -> URL:
        chroot = self._chroot
        assert chroot is not None  # Always set by __new__

        with (
            patch.object(self, "_root", chroot.path),
            patch.object(self, "_parts", ["".join(chroot._parts)] + self._parts[len(chroot._parts) :]),
        ):
            return super().resolve()

    @property
    def chroot(self) -> URL:
        assert self._chroot is not None  # Always set by __new__
        return self._chroot
