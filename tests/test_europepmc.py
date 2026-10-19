"""Europe PMC search failures must raise, not look like zero results (#5)."""
from datetime import datetime
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


def _hit(**fields):
    # Trimmed from a recorded Europe PMC search reply (2026-10-19).
    return {"hitCount": 1, "resultList": {"result": [
        {"id": "42829072", "source": "MED", "pubYear": "2026",
         "title": "CRISPR-based genome editing of smooth muscle cells", **fields}
    ]}}


def test_uses_first_publication_date():
    searcher = EuropePMCSearcher()
    searcher.session.get = Mock(return_value=_reply(json_data=_hit(firstPublicationDate="2026-10-03")))
    [paper] = searcher.search("CRISPR")
    assert paper.published_date == datetime(2026, 10, 3)


def test_falls_back_to_pub_year():
    searcher = EuropePMCSearcher()
    searcher.session.get = Mock(return_value=_reply(json_data=_hit()))
    [paper] = searcher.search("CRISPR")
    assert paper.published_date == datetime(2026, 1, 1)
