#!/usr/bin/env python3
import pytest

try:
    import webob
except ImportError:
    webob = None

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


@pytest.mark.skipif(webob is None, reason="webob not installed")
def test_webob() -> None:
    base_url = "http://www.example.com"
    url = URL(webob.Request.blank("/webob/request", base_url=base_url))

    assert str(url) == "http://www.example.com/webob/request"
    assert str(url / webob.Request.blank("/replaced/path", base_url=base_url)) == "http://www.example.com/replaced/path"
    assert str(url / webob.Request.blank("/replaced/path")) == "http://localhost/replaced/path"


@pytest.mark.skipif(webob is None, reason="webob not installed")
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


def test_init_with_empty_string() -> None:
    url = URL("")

    assert str(url) == ""


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
