"""Failed requests and unreadable replies must raise, not look like zero results (#5)."""
import asyncio
import json
from unittest.mock import Mock

import pytest
import requests

from paper_search_mcp import cli
from paper_search_mcp.academic_platforms.base import check_response, json_body
from paper_search_mcp.academic_platforms.dblp import DBLPSearcher
from paper_search_mcp.academic_platforms.openalex import OpenAlexSearcher
from paper_search_mcp.paper import Paper


def reply(status=200, json_data=None, content=b"", headers=None):
    response = Mock(status_code=status, content=content, text=content.decode())
    response.headers = headers or {}
    if json_data is None:
        response.json.side_effect = requests.JSONDecodeError("Expecting value", "", 0)
    else:
        response.json.return_value = json_data
    return response


def test_check_response_passes_2xx():
    check_response(reply(200), "X")


def test_check_response_names_status_and_retry_after_without_url():
    with pytest.raises(requests.HTTPError) as excinfo:
        check_response(reply(429, headers={"Retry-After": "31320"}), "OpenAlex")
    assert str(excinfo.value) == "OpenAlex returned HTTP 429 (Retry-After: 31320)"


def test_json_body_rejects_non_json():
    with pytest.raises(ValueError, match="X returned a non-JSON reply.*text/html"):
        json_body(reply(content=b"<html>", headers={"Content-Type": "text/html"}), "X")


# --- OpenAlex ---------------------------------------------------------------

def test_openalex_429_raises_with_retry_after():
    searcher = OpenAlexSearcher(api_key="")
    searcher.session.get = Mock(return_value=reply(429, headers={"Retry-After": "31320"}))
    with pytest.raises(requests.HTTPError, match="Retry-After: 31320"):
        searcher.search("graphs")


def test_openalex_network_error_raises():
    searcher = OpenAlexSearcher(api_key="")
    searcher.session.get = Mock(side_effect=requests.ConnectionError("down"))
    with pytest.raises(requests.ConnectionError):
        searcher.search("graphs")


def test_openalex_non_json_raises():
    searcher = OpenAlexSearcher(api_key="")
    searcher.session.get = Mock(return_value=reply(content=b"<html>"))
    with pytest.raises(ValueError, match="non-JSON"):
        searcher.search("graphs")


def test_openalex_genuine_empty_is_empty():
    searcher = OpenAlexSearcher(api_key="")
    searcher.session.get = Mock(return_value=reply(json_data={"results": []}))
    assert searcher.search("graphs") == []


# --- dblp ---------------------------------------------------------------------

DBLP_EMPTY = b'<?xml version="1.0"?><result><hits total="0" sent="0"></hits></result>'


def test_dblp_html_reply_raises_when_fallback_finds_nothing():
    searcher = DBLPSearcher()
    page = reply(content=b"<html><body>maintenance</body></html>",
                 headers={"Content-Type": "text/html"})
    searcher.session.get = Mock(return_value=page)
    with pytest.raises(ValueError, match="dblp returned an unexpected reply.*text/html"):
        searcher.search("graphs")


def test_dblp_http_error_raises_when_fallback_fails():
    searcher = DBLPSearcher()
    searcher.session.get = Mock(return_value=reply(429, headers={"Retry-After": "60"}))
    with pytest.raises(requests.HTTPError, match="dblp returned HTTP 429.*Retry-After: 60"):
        searcher.search("graphs")


def test_dblp_genuine_empty_is_empty():
    searcher = DBLPSearcher()
    searcher.session.get = Mock(side_effect=[
        reply(content=DBLP_EMPTY),
        reply(content=b"<html><body><ul class='publ-list'></ul></body></html>"),
    ])
    assert searcher.search("graphs") == []


# --- CLI partial-results contract ---------------------------------------------

def test_cli_reports_source_failure_and_keeps_other_results(monkeypatch, capsys):
    openalex = OpenAlexSearcher(api_key="")
    openalex.session.get = Mock(return_value=reply(429, headers={"Retry-After": "31320"}))
    healthy = Mock()
    healthy.search.return_value = [Paper(paper_id="1", title="Kept", authors=[], abstract="",
                                         doi="", published_date=None, pdf_url="", url="",
                                         source="crossref")]
    monkeypatch.setattr(cli, "SEARCHERS", {"openalex": openalex, "crossref": healthy})

    args = cli.build_parser().parse_args(["search", "graphs", "-s", "openalex,crossref"])
    assert asyncio.run(cli.cmd_search(args)) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["errors"] == {"openalex": "OpenAlex returned HTTP 429 (Retry-After: 31320)"}
    assert output["source_results"] == {"openalex": 0, "crossref": 1}
    assert [p["title"] for p in output["papers"]] == ["Kept"]
