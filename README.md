# URLPath

URLPath provides URL manipulator class that extends [`pathlib.PurePath`](https://docs.python.org/3/library/pathlib.html#pure-paths).

[![Tests](https://github.com/brandonschabell/urlpath/actions/workflows/test.yml/badge.svg)](https://github.com/brandonschabell/urlpath/actions/workflows/test.yml)
[![PyPI version](https://img.shields.io/pypi/v/urlpath.svg)](https://pypi.python.org/pypi/urlpath)
[![Downloads](https://pepy.tech/badge/urlpath)](https://pepy.tech/project/urlpath)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Versions](https://img.shields.io/pypi/pyversions/urlpath.svg)](https://pypi.org/project/urlpath/)

## Dependencies

* Python 3.9–3.14
* [Requests](http://docs.python-requests.org/)
* [JMESPath](https://pypi.org/project/jmespath/) (Optional)
* [WebOb](http://webob.org/) (Optional)

## Install

```bash
pip install urlpath
```

## Examples

```python
from urlpath import URL

# Create URL object
url = URL(
    'https://username:password@secure.example.com:1234/path/to/file.ext?field1=1&field2=2&field1=3#fragment')

# Representation
assert str(url) == 'https://username:password@secure.example.com:1234/path/to/file.ext?field1=1&field2=2&field1=3#fragment'
assert url.as_uri() == 'https://username:password@secure.example.com:1234/path/to/file.ext?field1=1&field2=2&field1=3#fragment'
assert url.as_posix() == 'https://username:password@secure.example.com:1234/path/to/file.ext?field1=1&field2=2&field1=3#fragment'

# Access pathlib.PurePath compatible properties
assert url.drive == 'https://username:password@secure.example.com:1234'
assert url.root == '/'
assert url.anchor == 'https://username:password@secure.example.com:1234/'
assert url.path == '/path/to/file.ext'
assert url.name == 'file.ext'
assert url.suffix == '.ext'
assert url.suffixes == ['.ext']
assert url.stem == 'file'
assert url.parts == ('https://username:password@secure.example.com:1234/', 'path', 'to', 'file.ext')
assert str(url.parent) == 'https://username:password@secure.example.com:1234/path/to'

# Access scheme
assert url.scheme == 'https'

# Access netloc
assert url.netloc == 'username:password@secure.example.com:1234'
assert url.username == 'username'
assert url.password == 'password'
assert url.hostname == 'secure.example.com'
assert url.port == 1234

# Access query
assert url.query == 'field1=1&field2=2&field1=3'
assert url.form_fields == (('field1', '1'), ('field2', '2'), ('field1', '3'))
assert 'field1' in url.form
assert url.form.get_one('field1') == '1'
assert url.form.get_one('field3') is None

# Access fragment
assert url.fragment == 'fragment'

# Path operations
assert str(url / 'suffix') == 'https://username:password@secure.example.com:1234/path/to/file.ext/suffix'
assert str(url / '../../rel') == 'https://username:password@secure.example.com:1234/path/to/file.ext/../../rel'
assert str((url / '../../rel').resolve()) == 'https://username:password@secure.example.com:1234/path/rel'
assert str(url / '/') == 'https://username:password@secure.example.com:1234/'
assert str(url / 'http://example.com/') == 'http://example.com/'

# Replace components
assert str(url.with_scheme('http')) == 'http://username:password@secure.example.com:1234/path/to/file.ext?field1=1&field2=2&field1=3#fragment'
assert str(url.with_netloc('www.example.com')) == 'https://www.example.com/path/to/file.ext?field1=1&field2=2&field1=3#fragment'
assert str(url.with_userinfo('joe', 'pa33')) == 'https://joe:pa33@secure.example.com:1234/path/to/file.ext?field1=1&field2=2&field1=3#fragment'
assert str(url.with_hostinfo('example.com', 8080)) == 'https://username:password@example.com:8080/path/to/file.ext?field1=1&field2=2&field1=3#fragment'
assert str(url.with_fragment('new fragment')) == 'https://username:password@secure.example.com:1234/path/to/file.ext?field1=1&field2=2&field1=3#new fragment'
assert str(url.with_components(username=None, password=None, query='query', fragment='frag')) == 'https://secure.example.com:1234/path/to/file.ext?query#frag'

# Replace query
assert str(url.with_query({'field3': '3', 'field4': [1, 2, 3]})) == 'https://username:password@secure.example.com:1234/path/to/file.ext?field3=3&field4=1&field4=2&field4=3#fragment'
assert str(url.with_query(field3='3', field4=[1, 2, 3])) == 'https://username:password@secure.example.com:1234/path/to/file.ext?field3=3&field4=1&field4=2&field4=3#fragment'
assert str(url.with_query('query')) == 'https://username:password@secure.example.com:1234/path/to/file.ext?query#fragment'
assert str(url.with_query(None)) == 'https://username:password@secure.example.com:1234/path/to/file.ext#fragment'

# Amend query
assert str(url.with_query(field1='1').add_query(field2=2)) == 'https://username:password@secure.example.com:1234/path/to/file.ext?field1=1&field2=2#fragment'
```

### HTTP requests

URLPath provides convenient methods for making HTTP requests:

```python
from urlpath import URL

# GET request
url = URL('https://httpbin.org/get')
response = url.get()
assert response.status_code == 200

# POST request
url = URL('https://httpbin.org/post')
response = url.post(data={'key': 'value'})
assert response.status_code == 200

# DELETE request
url = URL('https://httpbin.org/delete')
response = url.delete()
assert response.status_code == 200

# PATCH request
url = URL('https://httpbin.org/patch')
response = url.patch(data={'key': 'value'})
assert response.status_code == 200

# PUT request
url = URL('https://httpbin.org/put')
response = url.put(data={'key': 'value'})
assert response.status_code == 200
```

### Jail

```python
from urlpath import URL

root = 'http://www.example.com/app/'
current = 'http://www.example.com/app/path/to/content'
url = URL(root).jailed / current
assert str(url / '/root') == 'http://www.example.com/app/root'
assert str((url / '../../../../../../root').resolve()) == 'http://www.example.com/app/root'
assert str(url / 'http://localhost/') == 'http://www.example.com/app/'
assert str(url / 'http://www.example.com/app/file') == 'http://www.example.com/app/file'
```

### Trailing separator will be retained

```python
from urlpath import URL

url = URL('http://www.example.com/path/with/trailing/sep/')
assert str(url).endswith('/')
assert url.trailing_sep == '/'
assert url.name == 'sep'
assert url.path == '/path/with/trailing/sep/'
assert url.parts[-1] == 'sep'

url = URL('http://www.example.com/path/without/trailing/sep')
assert not str(url).endswith('/')
assert url.trailing_sep == ''
assert url.name == 'sep'
assert url.path == '/path/without/trailing/sep'
assert url.parts[-1] == 'sep'
```
