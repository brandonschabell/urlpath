#!/usr/bin/env python3
import os
import urllib.parse
from pathlib import PurePosixPath
from typing import Any, cast
from unittest.mock import Mock

import jmespath
import pytest
import webob

from urlpath import URL, JailedURL


def test_simple() -> None:
    original = "http://www.example.com/path/to/file.ext?query#fragment"
    url = URL(original)

    assert str(url) == original
    assert url.as_uri() == original
    assert url.as_posix() == original
    assert url.drive == "http://www.example.com"
    assert url.root == "/"
    assert url.anchor == "http://www.example.com/"
    assert url.path == "/path/to/file.ext"
    assert url.name == "file.ext"
    assert url.suffix == ".ext"
    assert url.suffixes == [".ext"]
    assert url.stem == "file"
    assert url.parts == ("http://www.example.com/", "path", "to", "file.ext")
    assert str(url.parent) == "http://www.example.com/path/to"
    assert url.scheme == "http"
    assert url.netloc == "www.example.com"
    assert url.query == "query"
    assert url.fragment == "fragment"


def test_netloc_mixin() -> None:
    url = URL("https://username:password@secure.example.com:1234/secure/path?query#fragment")

    assert url.drive == "https://username:password@secure.example.com:1234"
    assert url.scheme == "https"
    assert url.netloc == "username:password@secure.example.com:1234"
    assert url.username == "username"
    assert url.password == "password"
    assert url.hostname == "secure.example.com"
    assert url.port == 1234


def test_join() -> None:
    url = URL("http://www.example.com/path/to/file.ext?query#fragment")

    assert str(url / "https://secure.example.com/path") == "https://secure.example.com/path"
    assert str(url / "/changed/path") == "http://www.example.com/changed/path"
    assert str(url.with_name("other_file")) == "http://www.example.com/path/to/other_file"


def test_join_with_absolute_segment_resets_path() -> None:
    url = URL("http://example.com/base/path") / "child"

    assert str(url) == "http://example.com/base/path/child"
    assert str(url / "/absolute") == "http://example.com/absolute"
    assert str((url / "deeper") / "/absolute/child") == "http://example.com/absolute/child"


def test_constructor_with_absolute_segment_resets_path() -> None:
    url = URL("http://example.com/base", "/absolute/path")

    assert str(url) == "http://example.com/absolute/path"


def test_path() -> None:
    url = URL("http://www.example.com/path/to/file.ext?query#fragment")

    assert url.path == "/path/to/file.ext"


def test_with() -> None:
    url = URL("http://www.example.com/path/to/file.exe?query?fragment")

    assert str(url.with_scheme("https")) == "https://www.example.com/path/to/file.exe?query?fragment"
    assert str(url.with_netloc("localhost")) == "http://localhost/path/to/file.exe?query?fragment"
    assert (
        str(url.with_userinfo("username", "password"))
        == "http://username:password@www.example.com/path/to/file.exe?query?fragment"
    )
    assert str(url.with_userinfo(None, None)) == "http://www.example.com/path/to/file.exe?query?fragment"
    assert str(url.with_hostinfo("localhost", 8080)) == "http://localhost:8080/path/to/file.exe?query?fragment"

    assert str(URL("http://example.com/base/") / "path/to/file") == "http://example.com/base/path/to/file"

    assert (
        str(URL("http://example.com/path/?q") / URL("http://localhost/app/?q") / URL("to/content"))
        == "http://localhost/app/to/content"
    )


def test_query() -> None:
    query = "field1=value1&field1=value2&field2=hello,%20world%26python"
    url = URL("http://www.example.com/form?" + query)

    assert url.query == query
    assert set(url.form) == {"field1", "field2"}
    assert url.form.get("field1") == ("value1", "value2")
    assert url.form.get("field2") == ("hello, world&python",)
    assert "field1" in url.form
    assert "field2" in url.form
    assert "field3" not in url.form
    assert "field4" not in url.form

    url = url.with_query({"field3": "value3", "field4": [1, 2, 3]})
    assert set(url.form) == {"field3", "field4"}
    assert "field1" not in url.form
    assert "field2" not in url.form
    assert "field3" in url.form
    assert "field4" in url.form
    assert url.form.get("field3") == ("value3",)
    assert url.form.get("field4") == ("1", "2", "3")


def test_add_query() -> None:
    query = "field1=value1&field1=value2&field2=hello,%20world%26python"
    url = URL("http://www.example.com/form?" + query)

    # if initial query is null, it should include the added query
    ext_url = url.with_query("").add_query({"field3": "value3", "field4": [1, 2, 3]})
    assert set(ext_url.form) == {"field3", "field4"}
    assert ext_url.form.get("field3") == ("value3",)
    assert ext_url.form.get("field4") == ("1", "2", "3")
    assert "field1" not in ext_url.form
    assert "field2" not in ext_url.form
    assert "field3" in ext_url.form
    assert "field4" in ext_url.form

    # if initial query exists, it should include the both fields
    ext_url = url.add_query({"field3": "value3", "field4": [1, 2, 3]})
    assert ext_url.query == f"{query}&field3=value3&field4=1&field4=2&field4=3"
    assert set(ext_url.form) == {"field1", "field2", "field3", "field4"}
    assert "field1" in ext_url.form
    assert "field2" in ext_url.form
    assert "field3" in ext_url.form
    assert "field4" in ext_url.form
    assert ext_url.form.get("field1") == ("value1", "value2")
    assert ext_url.form.get("field2") == ("hello, world&python",)
    assert ext_url.form.get("field3") == ("value3",)
    assert ext_url.form.get("field4") == ("1", "2", "3")

    # if added query is null, it should include original query
    assert url.add_query({}).query == query


def test_query_field_order() -> None:
    url = URL("http://example.com/").with_query(field1="field1", field2="field2", field3="field3")

    assert str(url) == "http://example.com/?field1=field1&field2=field2&field3=field3"


def test_fragment() -> None:
    url = URL("http://www.example.com/path/to/file.ext?query#fragment")

    assert url.fragment == "fragment"

    url = url.with_fragment("new fragment")

    assert str(url) == "http://www.example.com/path/to/file.ext?query#new fragment"
    assert url.fragment == "new fragment"


def test_resolve() -> None:
    url = URL("http://www.example.com//./../path/./..//./file/")
    assert str(url.resolve()) == "http://www.example.com/file"


def test_trailing_sep() -> None:
    original = "http://www.example.com/path/with/trailing/sep/"
    url = URL(original)

    assert str(url) == original
    assert url.name == "sep"
    assert url.parts[-1] == "sep"

    assert URL("htp://example.com/").trailing_sep == ""
    assert URL("htp://example.com/with/sep/").trailing_sep == "/"
    assert URL("htp://example.com/without/sep").trailing_sep == ""
    assert URL("htp://example.com/with/double-sep//").trailing_sep == "//"


def test_webob() -> None:
    base_url = "http://www.example.com"
    url = URL(webob.Request.blank("/webob/request", base_url=base_url))

    assert str(url) == "http://www.example.com/webob/request"
    assert str(url / webob.Request.blank("/replaced/path", base_url=base_url)) == "http://www.example.com/replaced/path"
    assert str(url / webob.Request.blank("/replaced/path")) == "http://localhost/replaced/path"


def test_webob_jail() -> None:
    request = webob.Request.blank("/path/to/filename.ext", {"SCRIPT_NAME": "/app/root"})

    assert request.application_url == "http://localhost/app/root"
    assert request.url == "http://localhost/app/root/path/to/filename.ext"

    url = JailedURL(request)

    assert str(url.chroot) == "http://localhost/app/root"
    assert str(url) == "http://localhost/app/root/path/to/filename.ext"


def test_jail() -> None:
    root = "http://www.example.com/app/"
    current = "http://www.example.com/app/path/to/content"
    url = URL(root).jailed / current

    assert str(url) == current
    assert str(url.chroot) == root
    assert str(url / "appendix") == "http://www.example.com/app/path/to/content/appendix"
    assert str(url / "./appendix") == "http://www.example.com/app/path/to/content/appendix"
    assert str(url / "/root") == "http://www.example.com/app/root"
    assert str(url / "http://other.domain/") == "http://www.example.com/app/"
    assert str((url / "../file").resolve()) == "http://www.example.com/app/path/to/file"
    assert str((url / "../../../../../root").resolve()) == "http://www.example.com/app/root"
    assert str((url / "/../../../../../root").resolve()) == "http://www.example.com/app/root"
    assert str(url / "http://www.example.com/app/path") == "http://www.example.com/app/path"


def test_jail_clamps_parent_references() -> None:
    root = URL("http://www.example.com/app/")
    url = root.jailed / "http://www.example.com/app/path/to/content"

    # '..' must never survive into the string form, where a server could follow it out of the jail
    assert str(url / "../file") == "http://www.example.com/app/path/to/file"
    assert str(url / "../../../../etc") == "http://www.example.com/app/etc"
    assert str(url / "a" / ".." / ".." / ".." / ".." / ".." / "etc") == "http://www.example.com/app/etc"
    assert str(url / "%2e%2e/%2E%2E/%2e%2e/%2e%2e/etc") == "http://www.example.com/app/etc"
    assert str(url.joinpath("..", "..", "..", "..", "etc")) == "http://www.example.com/app/etc"
    assert str(JailedURL("http://www.example.com/app/../../etc", root=root)) == "http://www.example.com/app/etc"
    assert str(url.with_components(path="/app/../../etc")) == "http://www.example.com/app/etc"
    assert isinstance(url / "../file", JailedURL)
    assert (url / "../file").chroot == root


def test_jail_resolve_is_independent_of_cached_parts() -> None:
    url = URL("http://www.example.com/app/").jailed / "http://www.example.com/app/path/./to//file/"
    expected = "http://www.example.com/app/path/to/file"

    assert str(url.resolve()) == expected
    url = URL("http://www.example.com/app/").jailed / "http://www.example.com/app/path/./to//file/"
    assert url.parts  # populate cached properties before resolving
    assert str(url.resolve()) == expected


def test_init_with_empty_string() -> None:
    url = URL("")

    assert str(url) == ""


def test_bytes_arguments_are_canonicalized_without_str_roundtrip() -> None:
    url = URL(b"http://example.com/base")

    assert str(url) == "http://example.com/base"
    assert str(URL("http://example.com") / cast(Any, b"path")) == "http://example.com/path"


def test_pathlike_arguments_are_supported() -> None:
    pathlike: Any = PurePosixPath("path/like/segment")

    url = URL("http://example.com") / pathlike

    assert str(url) == "http://example.com/path/like/segment"


def test_encoding() -> None:
    assert URL("http://www.xn--alliancefranaise-npb.nu/").hostname == "www.alliancefran\xe7aise.nu"
    assert (
        str(URL("http://localhost/").with_hostinfo("www.alliancefran\xe7aise.nu"))
        == "http://www.xn--alliancefranaise-npb.nu/"
    )

    url = URL("http://%75%73%65%72:%70%61%73%73%77%64@httpbin.org/basic-auth/user/passwd")
    assert url.username == "user"
    assert url.password == "passwd"

    username = "foo@example.com"
    password = "pa$$word"
    url = URL("http://example.com").with_userinfo(username, password)
    assert url.username == username
    assert url.password == password
    assert str(url) == "http://foo%40example.com:pa%24%24word@example.com"

    assert (
        str(URL("http://example.com/日本語の/パス"))
        == "http://example.com/%E6%97%A5%E6%9C%AC%E8%AA%9E%E3%81%AE/%E3%83%91%E3%82%B9"
    )

    original = "http://example.com/\u3081\u3061\u3083\u304f\u3061\u3083\u306a/\u30d1\u30b9/%2F%23%3F"
    url = URL(original)
    assert (
        str(url) == "http://example.com/%E3%82%81%E3%81%A1%E3%82%83%E3%81%8F%E3%81%A1%E3%82%83%E3%81%AA/"
        "%E3%83%91%E3%82%B9/%2F%23%3F"
    )
    assert url.path == "/%E3%82%81%E3%81%A1%E3%82%83%E3%81%8F%E3%81%A1%E3%82%83%E3%81%AA/%E3%83%91%E3%82%B9/%2F%23%3F"
    assert url.name == "/#?"
    assert url.parts == (
        "http://example.com/",
        "\u3081\u3061\u3083\u304f\u3061\u3083\u306a",
        "\u30d1\u30b9",
        "/#?",
    )

    assert (
        str(URL("http://example.com/name").with_name("\u65e5\u672c\u8a9e/\u540d\u524d"))
        == "http://example.com/%E6%97%A5%E6%9C%AC%E8%AA%9E%2F%E5%90%8D%E5%89%8D"
    )

    assert (
        str(URL("http://example.com/name") / "\u65e5\u672c\u8a9e/\u540d\u524d")
        == "http://example.com/name/%E6%97%A5%E6%9C%AC%E8%AA%9E/%E5%90%8D%E5%89%8D"
    )

    assert str(URL("http://example.com/file").with_suffix(".///")) == "http://example.com/file.%2F%2F%2F"


def test_idempotent() -> None:
    url = URL(
        "http://\u65e5\u672c\u8a9e\u306e.\u30c9\u30e1\u30a4\u30f3.jp/"
        "path/to/\u30d5\u30a1\u30a4\u30eb.ext?\u30af\u30a8\u30ea"
    )

    assert url == URL(str(url))
    assert url == URL(
        "http://xn--u9ju32nb2abz6g.xn--eckwd4c7c.jp/path/to/\u30d5\u30a1\u30a4\u30eb.ext?\u30af\u30a8\u30ea"
    )


def test_embed() -> None:
    url = URL("http://example.com/").with_fragment(URL("/param1/param2").with_query(f1=1, f2=2))
    assert str(url) == "http://example.com/#/param1/param2?f1=1&f2=2"


def test_pchar() -> None:
    url = URL("s3://mybucket") / "some_folder/123_2017-10-30T18:43:11.csv.gz"
    assert str(url) == "s3://mybucket/some_folder/123_2017-10-30T18:43:11.csv.gz"


@pytest.mark.parametrize(
    ("raw", "expected"),
    (
        (urllib.parse.urlsplit("http://example.com/from-split?x=1#frag"), "http://example.com/from-split?x=1#frag"),
        (urllib.parse.urlparse("https://example.com/from-parse"), "https://example.com/from-parse"),
        (b"http://example.com/from-bytes", "http://example.com/from-bytes"),
    ),
)
def test_constructor_canonicalizes_supported_types(raw: Any, expected: str) -> None:
    class PathLike:
        def __fspath__(self) -> str:
            return "http://example.com/from-fspath"

    assert str(URL(raw)) == expected

    # PathLike objects should be accepted consistently regardless of other inputs
    assert str(URL(PathLike())) == "http://example.com/from-fspath"


def test_multi_argument_constructor_matches_joinpath_semantics() -> None:
    base = URL("http://example.com/base/")

    combined = URL("http://example.com/base/", "child", "../final")
    chained = base / "child" / "../final"

    assert str(combined) == str(chained)
    assert "\x00" not in "".join(combined.parts)

    absolute_override = URL("http://example.com/base/", "https://other.com/override", "tail")
    assert str(absolute_override) == "https://other.com/override/tail"


def test_percent_encoding_spaces() -> None:
    """Test that %20 encoded spaces don't get double-encoded."""
    # Reported bug: URL with %20 in middle of path segment gets double-encoded to %2520
    url = URL("https://somepath.com/test/Test%20path/my%20test%20file.txt")
    assert str(url) == "https://somepath.com/test/Test%20path/my%20test%20file.txt"

    # Test various positions of %20
    assert str(URL("https://somepath.com/Test%20path")) == "https://somepath.com/Test%20path"
    assert str(URL("https://somepath.com/%20leading")) == "https://somepath.com/%20leading"
    assert str(URL("https://somepath.com/trailing%20")) == "https://somepath.com/trailing%20"
    assert str(URL("https://somepath.com/multiple%20spaces%20here")) == "https://somepath.com/multiple%20spaces%20here"

    # Test that actual spaces get encoded properly
    url_with_spaces = URL("https://somepath.com/test") / "Test path" / "my test file.txt"
    assert str(url_with_spaces) == "https://somepath.com/test/Test%20path/my%20test%20file.txt"


def test_colon_in_filename() -> None:
    """Test that colons in filenames are not treated as scheme separators."""
    # Reported bug: URL('http://www.example.com/abc:def.html') was truncated to 'http://www.example.com/def.html'
    url = URL("http://www.example.com/abc:def.html")
    assert str(url) == "http://www.example.com/abc:def.html"
    assert url.name == "abc:def.html"
    assert url.path == "/abc:def.html"

    # Test various positions and uses of colons
    assert str(URL("http://www.example.com/file:name.txt")) == "http://www.example.com/file:name.txt"
    assert str(URL("http://www.example.com/path/to/file:v2.html")) == "http://www.example.com/path/to/file:v2.html"
    assert str(URL("http://www.example.com/:colon.txt")) == "http://www.example.com/:colon.txt"
    assert str(URL("http://www.example.com/colon:.txt")) == "http://www.example.com/colon:.txt"

    # Test with query and fragment
    url = URL("http://www.example.com/abc:def.html?key=value#frag")
    assert url.name == "abc:def.html"
    assert url.query == "key=value"
    assert url.fragment == "frag"
    assert str(url) == "http://www.example.com/abc:def.html?key=value#frag"


def test_fspath_matches_str() -> None:
    # Python 3.15 aliased PurePath.__fspath__ to PurePath.__str__, bypassing URL.__str__
    url = URL("http://localhost/app/?q#frag")

    assert os.fspath(url) == str(url) == "http://localhost/app/?q#frag"
    assert str(URL("http://example.com/path/?q") / URL("to/content")) == "http://example.com/path/to/content"


def test_ipv6() -> None:
    url = URL("http://[::1]:8080/path")

    assert str(url) == "http://[::1]:8080/path"
    assert url.netloc == "[::1]:8080"
    assert url.hostinfo == "[::1]:8080"
    assert url.hostname == "::1"
    assert url.port == 8080
    assert str(url / "child") == "http://[::1]:8080/path/child"
    assert str(URL("http://user:pw@[2001:db8::1]/")) == "http://user:pw@[2001:db8::1]/"
    assert str(URL("http://localhost/").with_hostinfo("::1", 80)) == "http://[::1]:80/"


def test_escape_marker_text_is_preserved() -> None:
    # Literal text resembling the internal '/' escape marker must round-trip unchanged
    assert str(URL("http://example.com/x?q=%5Cx00")) == "http://example.com/x?q=%5Cx00"
    assert URL("http://example.com/x?q=%5cx00").query == "q=%5cx00"
    assert str(URL("http://example.com/a%5Cx00b")) == "http://example.com/a%5Cx00b"
    assert URL("http://example.com/a%5Cx00b").name == "a\\x00b"
    assert str(URL("http://example.com/x#frag%5Cx00")) == "http://example.com/x#frag%5Cx00"


def test_escape_marker_does_not_leak() -> None:
    # '/' in trailing separators, query and fragment is escaped internally and must be restored
    for original in (
        "http://example.com/dir/",
        "http://example.com/dir//",
        "http://example.com/dir/?next=/a/b#/frag/ment",
        "http://example.com/?q=/",
        "relative/path/?q=/x",
    ):
        url = URL(original)
        assert str(url) == original
        assert "\x00" not in "".join(url.parts) + url.path + url.query + url.fragment

    assert str(URL("http://example.com/dir/file?q=/x").with_name("new")) == "http://example.com/dir/new"
    assert str(URL("http://example.com/dir/file?q=/x").with_suffix(".txt")) == "http://example.com/dir/file.txt"
    assert str(URL("http://example.com/dir/sub/?q=/x").parent) == "http://example.com/dir"


def test_relative_to_preserves_trailing_sep_query_and_fragment() -> None:
    relative = URL("http://example.com/a/b/").relative_to("http://example.com/a")
    assert str(relative) == "b/"
    assert relative.trailing_sep == "/"

    relative = URL("http://example.com/a/b?q=1/2#f/g").relative_to("http://example.com/a")
    assert str(relative) == "b?q=1/2#f/g"
    assert relative.query == "q=1/2"
    assert relative.fragment == "f/g"

    assert str(URL("http://example.com/a/b/c/?q=1/2").relative_to("http://example.com/")) == "a/b/c/?q=1/2"
    assert str(URL("http://example.com/a/b").relative_to("http://example.com/a")) == "b"


@pytest.mark.parametrize(
    ("call", "message"),
    (
        (lambda url: url.with_query({"a": "1"}, b="2"), "query"),
        (lambda url: url.add_query({"a": "1"}, b="2"), "query"),
        (lambda url: url.with_components(netloc="x", hostname="y"), "netloc"),
        (lambda url: url.with_components(path="/x", name="y"), "path"),
        (lambda url: JailedURL("http://example.com/app", root="/relative"), "root"),
    ),
)
def test_invalid_arguments_raise_value_error(call: Any, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        call(URL("http://example.com/"))


def test_get_json_with_jmespath_filtering() -> None:
    """Test get_json method with JMESPath query filtering."""
    from unittest.mock import patch

    url = URL("http://api.example.com/data")

    # Mock response with JSON data
    mock_response = Mock()
    mock_response.json.return_value = {
        "users": [
            {"name": "Alice", "age": 30},
            {"name": "Bob", "age": 25},
        ],
        "total": 2,
    }

    # Patch requests.get to avoid actual network calls
    with patch("requests.get", return_value=mock_response):
        # Test without JMESPath filtering
        result = url.get_json()
        assert result == mock_response.json.return_value

        # Test with JMESPath string query
        result = url.get_json(keys="users[0].name")
        assert result == "Alice"

        # Test with compiled JMESPath expression
        compiled_expr = jmespath.compile("users[*].age")
        result = url.get_json(keys=compiled_expr)
        assert result == [30, 25]

        # Test with query parameters
        result = url.get_json(query={"filter": "active"}, keys="total")
        assert result == 2
