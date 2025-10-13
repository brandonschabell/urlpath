"""Custom pathlib flavour for URL parsing."""

from __future__ import annotations

__all__ = ("_URLFlavour",)

import posixpath
from typing import TYPE_CHECKING

from ._compat import IS_PY312_PLUS
from ._utils import _url_splitroot

# Python 3.12+ removed _PosixFlavour class, replaced with module-based approach
if not TYPE_CHECKING and not IS_PY312_PLUS:
    from pathlib import _PosixFlavour
else:
    _PosixFlavour = object


# Python 3.12+ compatibility: create flavour class or simple object
if IS_PY312_PLUS:
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
    class _URLFlavour(_PosixFlavour):  # type: ignore[no-redef]
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
