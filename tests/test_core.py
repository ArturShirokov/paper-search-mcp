"""CORE search failures must raise, not look like zero results (#5)."""
from unittest.mock import Mock, patch

import pytest
import requests

from paper_search_mcp.academic_platforms.core import CORESearcher


def _reply(status=200, json_data=None, headers=None):
    response = Mock(status_code=status)
    response.headers = headers or {}
    if json_data is None:
        response.json.side_effect = requests.JSONDecodeError("Expecting value", "", 0)
    else:
        response.json.return_value = json_data
    return response


@pytest.fixture(autouse=True)
def no_sleep():
    with patch("paper_search_mcp.academic_platforms.core.time.sleep"):
        yield


def test_429_after_retries_raises_with_retry_after():
    searcher = CORESearcher(api_key="secret-key")
    searcher.session.get = Mock(return_value=_reply(429, headers={"Retry-After": "60"}))
    with pytest.raises(requests.HTTPError) as excinfo:
        searcher.search("graphs")
    assert str(excinfo.value) == "CORE returned HTTP 429 (Retry-After: 60)"
    assert searcher.session.get.call_count == 3


def test_timeouts_after_retries_raise():
    searcher = CORESearcher(api_key="k")
    searcher.session.get = Mock(side_effect=requests.Timeout("slow"))
    with pytest.raises(requests.Timeout):
        searcher.search("graphs")
    assert searcher.session.get.call_count == 3


def test_retry_then_success():
    searcher = CORESearcher(api_key="k")
    searcher.session.get = Mock(side_effect=[_reply(503), _reply(json_data={"results": []})])
    assert searcher.search("graphs") == []


def test_rejected_key_fallback_failure_raises():
    searcher = CORESearcher(api_key="secret-key")
    searcher.session.get = Mock(return_value=_reply(401))
    with patch("paper_search_mcp.academic_platforms.core.requests.get", return_value=_reply(403)):
        with pytest.raises(requests.HTTPError, match="CORE returned HTTP 403"):
            searcher.search("graphs")


def test_non_json_raises():
    searcher = CORESearcher(api_key="k")
    searcher.session.get = Mock(return_value=_reply(headers={"Content-Type": "text/html"}))
    with pytest.raises(ValueError, match="CORE returned a non-JSON reply"):
        searcher.search("graphs")


def test_wrong_shape_raises():
    searcher = CORESearcher(api_key="k")
    searcher.session.get = Mock(return_value=_reply(json_data={"message": "oops"}))
    with pytest.raises(ValueError, match="CORE"):
        searcher.search("graphs")


def test_genuine_empty_is_empty():
    searcher = CORESearcher(api_key="k")
    searcher.session.get = Mock(return_value=_reply(json_data={"totalHits": 0, "results": []}))
    assert searcher.search("graphs") == []
