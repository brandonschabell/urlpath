"""URLPath - Object-oriented URL manipulation extending pathlib.PurePath.

This package provides the URL and JailedURL classes for working with URLs
using familiar pathlib-style operations combined with URL component manipulation.

Examples:
    >>> from urlpath import URL
    >>> url = URL('https://example.com/path/to/file.txt')
    >>> url.hostname
    'example.com'
    >>> str(url / 'other.txt')
    'https://example.com/path/to/other.txt'
"""

from __future__ import annotations

__all__ = ["URL", "JailedURL"]

from ._url import URL, JailedURL
