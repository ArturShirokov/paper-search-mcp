"""PMC search failures must raise, not look like zero results (#5)."""
from datetime import datetime
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


def _summary(pub_date, epub_date):
    # Trimmed from a recorded esummary reply for PMC13677170 (2026-10-19).
    return _reply(content=(
        "<eSummaryResult><DocSum><Id>123</Id>"
        f'<Item Name="PubDate" Type="Date">{pub_date}</Item>'
        f'<Item Name="EPubDate" Type="Date">{epub_date}</Item>'
        '<Item Name="Title" Type="String">Human iPSC-derived fetal granulosa-like cells</Item>'
        "</DocSum></eSummaryResult>"
    ).encode())


@pytest.mark.parametrize("pub_date, epub_date, expected", [
    ("2026 Oct 1", "2026 Jul 24", datetime(2026, 7, 24)),  # EPubDate wins
    ("2026 Oct 18", "", datetime(2026, 10, 18)),
    ("2026 Sep-Oct", "", datetime(2026, 9, 1)),  # range: first month
    ("2026 Fall", "", datetime(2026, 1, 1)),  # season: year only
])
def test_summary_dates(pub_date, epub_date, expected):
    searcher = PMCSearcher()
    searcher.session.get = Mock(
        side_effect=[_reply(content=ESEARCH_ONE), _summary(pub_date, epub_date)]
    )
    [paper] = searcher.search("graphs")
    assert paper.published_date == expected
