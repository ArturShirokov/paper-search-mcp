"""Europe PMC search failures must raise, not look like zero results (#5)."""
from unittest.mock import Mock

import pytest
import requests

from paper_search_mcp.academic_platforms.europepmc import EuropePMCSearcher


def _reply(status=200, json_data=None, headers=None):
    response = Mock(status_code=status)
    response.headers = headers or {}
    if json_data is None:
        response.json.side_effect = requests.JSONDecodeError("Expecting value", "", 0)
    else:
        response.json.return_value = json_data
    return response


def test_http_error_raises_with_retry_after():
    searcher = EuropePMCSearcher()
    searcher.session.get = Mock(return_value=_reply(503, headers={"Retry-After": "30"}))
    with pytest.raises(requests.HTTPError, match="Europe PMC returned HTTP 503.*Retry-After: 30"):
        searcher.search("graphs")


def test_network_error_raises():
    searcher = EuropePMCSearcher()
    searcher.session.get = Mock(side_effect=requests.ConnectionError("down"))
    with pytest.raises(requests.ConnectionError):
        searcher.search("graphs")


def test_non_json_raises():
    searcher = EuropePMCSearcher()
    searcher.session.get = Mock(return_value=_reply(headers={"Content-Type": "text/html"}))
    with pytest.raises(ValueError, match="Europe PMC returned a non-JSON reply"):
        searcher.search("graphs")


def test_wrong_shape_raises():
    searcher = EuropePMCSearcher()
    searcher.session.get = Mock(return_value=_reply(json_data={"errMsg": "bad query"}))
    with pytest.raises(ValueError, match="Europe PMC"):
        searcher.search("graphs")


def test_genuine_empty_is_empty():
    searcher = EuropePMCSearcher()
    searcher.session.get = Mock(
        return_value=_reply(json_data={"hitCount": 0, "resultList": {"result": []}})
    )
    assert searcher.search("graphs") == []
