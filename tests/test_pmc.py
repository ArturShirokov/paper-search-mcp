"""PMC search failures must raise, not look like zero results (#5)."""
from unittest.mock import Mock

import pytest
import requests

from paper_search_mcp.academic_platforms.pmc import PMCSearcher


def _reply(status=200, content=b"", headers=None):
    response = Mock(status_code=status, content=content)
    response.headers = headers or {}
    return response


ESEARCH_EMPTY = b"<eSearchResult><Count>0</Count><IdList/></eSearchResult>"
ESEARCH_ONE = b"<eSearchResult><Count>1</Count><IdList><Id>123</Id></IdList></eSearchResult>"


def test_http_error_raises_with_retry_after():
    searcher = PMCSearcher()
    searcher.session.get = Mock(return_value=_reply(429, headers={"Retry-After": "10"}))
    with pytest.raises(requests.HTTPError, match="PMC returned HTTP 429.*Retry-After: 10"):
        searcher.search("graphs")


def test_summary_http_error_raises():
    searcher = PMCSearcher()
    searcher.session.get = Mock(side_effect=[_reply(content=ESEARCH_ONE), _reply(503)])
    with pytest.raises(requests.HTTPError, match="PMC returned HTTP 503"):
        searcher.search("graphs")


def test_network_error_raises():
    searcher = PMCSearcher()
    searcher.session.get = Mock(side_effect=requests.ConnectionError("down"))
    with pytest.raises(requests.ConnectionError):
        searcher.search("graphs")


def test_non_xml_raises():
    searcher = PMCSearcher()
    searcher.session.get = Mock(
        return_value=_reply(content=b"<html><body>down", headers={"Content-Type": "text/html"})
    )
    with pytest.raises(ValueError, match="PMC returned a non-XML reply.*text/html"):
        searcher.search("graphs")


def test_esearch_error_envelope_raises():
    searcher = PMCSearcher()
    searcher.session.get = Mock(
        return_value=_reply(content=b"<eSearchResult><ERROR>Invalid db name</ERROR></eSearchResult>")
    )
    with pytest.raises(RuntimeError, match="PMC search failed: Invalid db name"):
        searcher.search("graphs")


def test_wrong_root_raises():
    searcher = PMCSearcher()
    searcher.session.get = Mock(return_value=_reply(content=b"<html><body>hi</body></html>"))
    with pytest.raises(ValueError, match="PMC"):
        searcher.search("graphs")


def test_genuine_empty_is_empty():
    searcher = PMCSearcher()
    searcher.session.get = Mock(return_value=_reply(content=ESEARCH_EMPTY))
    assert searcher.search("graphs") == []
