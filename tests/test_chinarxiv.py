import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import requests

from paper_search_mcp.academic_platforms.chinarxiv import ChinaRxivSearcher

RECORD = {
    "_links": {"pdf": "/api/v1/papers/chinaxiv-202604.00249/pdf"},
    "abstract": "Abstract: Treating the graphene-reinforced hinged beam...",
    "abstract_source": "source",
    "authors": ["ZHANG Kairui, WANG Aiwen, FAN Xudong"],
    "date": "2026-04-21",
    "has_pdf": True,
    "id": "chinaxiv-202604.00249",
    "source": "chinaxiv",
    "source_language": "mixed",
    "source_url": "https://chinaxiv.org/abs/202604.00249",
    "subjects": ["Mechanics"],
    "title": "Nonlinear Modal Analysis of Graphene-Reinforced Hinged Beam Structures",
}


def _response(json_data=None, content=b""):
    response = MagicMock()
    response.json.return_value = json_data
    response.content = content
    response.raise_for_status.return_value = None
    return response


@pytest.fixture
def searcher():
    return ChinaRxivSearcher(email="")


def test_search_parses_records(searcher):
    searcher.session.get = MagicMock(return_value=_response({"data": [RECORD], "next_cursor": None}))

    [paper] = searcher.search("graphene", max_results=5)

    params = searcher.session.get.call_args.kwargs["params"]
    assert params == {"q": "graphene", "source": "chinaxiv", "limit": 5}
    assert paper.source == "chinarxiv"
    assert paper.paper_id == "chinaxiv-202604.00249"
    assert paper.title.startswith("Nonlinear Modal Analysis")
    assert paper.authors == ["ZHANG Kairui", "WANG Aiwen", "FAN Xudong"]
    assert paper.published_date == datetime(2026, 4, 21)
    assert paper.url == "https://chinarxiv.org/items/chinaxiv-202604.00249"
    assert paper.pdf_url == "https://chinarxiv.org/api/v1/papers/chinaxiv-202604.00249/pdf"
    assert paper.categories == ["Mechanics"]
    assert paper.extra == {
        "original_url": "https://chinaxiv.org/abs/202604.00249",
        "corpus": "chinaxiv",
        "source_language": "mixed",
        "abstract_source": "source",
    }


def test_search_pages_with_cursor_until_max_results(searcher):
    second = dict(RECORD, id="chinaxiv-2")
    searcher.session.get = MagicMock(side_effect=[
        _response({"data": [RECORD], "next_cursor": "C2"}),
        _response({"data": [second, dict(RECORD, id="chinaxiv-3")], "next_cursor": "C3"}),
    ])

    papers = searcher.search("graphene", max_results=2)

    assert [p.paper_id for p in papers] == ["chinaxiv-202604.00249", "chinaxiv-2"]
    assert searcher.session.get.call_args_list[1].kwargs["params"]["cursor"] == "C2"


def test_list_new_filters_by_date_and_corpus(searcher):
    searcher.session.get = MagicMock(return_value=_response({"data": [], "next_cursor": None}))

    assert searcher.list_new("2026-09-01", max_results=50, corpus="russiarxiv") == []

    params = searcher.session.get.call_args.kwargs["params"]
    assert params == {"from_date": "2026-09-01", "source": "russiarxiv", "limit": 50}


def test_missing_pdf_and_http_errors(searcher):
    paper = searcher._parse(dict(RECORD, has_pdf=False))
    assert paper.pdf_url == ""

    failing = _response()
    failing.raise_for_status.side_effect = requests.HTTPError("422")
    searcher.session.get = MagicMock(return_value=failing)
    with pytest.raises(requests.HTTPError):
        searcher.search("x")


def test_read_paper_returns_translated_markdown(searcher):
    searcher.session.get = MagicMock(return_value=_response({"body_md": "# Title\n\nBody"}))

    assert searcher.read_paper("chinaxiv-202604.00249") == "# Title\n\nBody"
    assert searcher.session.get.call_args.args[0] == (
        "https://chinarxiv.org/api/v1/papers/chinaxiv-202604.00249/text"
    )


def test_download_pdf(searcher, tmp_path):
    searcher.session.get = MagicMock(return_value=_response(content=b"%PDF-1.7 x"))

    path = searcher.download_pdf("chinaxiv-202604.00249", str(tmp_path))

    assert open(path, "rb").read() == b"%PDF-1.7 x"


def test_email_goes_in_polite_pool_header():
    assert ChinaRxivSearcher(email="me@example.org").session.headers["X-API-Email"] == "me@example.org"
    assert "X-API-Email" not in ChinaRxivSearcher(email="").session.headers


def test_registered_in_server_and_cli():
    from paper_search_mcp import cli, server

    assert "chinarxiv" in server.ALL_SOURCES
    assert "chinarxiv" in cli.ALL_SOURCES
    assert isinstance(cli._get_searcher("chinarxiv"), ChinaRxivSearcher)
    for tool in ("search_chinarxiv", "list_new_chinarxiv", "download_chinarxiv", "read_chinarxiv_paper"):
        assert callable(getattr(server, tool))

    paper = {"paper_id": "x", "title": "T", "authors": "", "doi": "", "source": "chinarxiv"}
    with patch.object(server, "search_chinarxiv", new=AsyncMock(return_value=[paper])):
        result = asyncio.run(server.search_papers("q", sources="chinarxiv"))
    assert result["source_results"] == {"chinarxiv": 1}


def test_list_new_tool_passes_corpus(monkeypatch):
    from paper_search_mcp import server

    calls = {}

    def fake(since, max_results, corpus):
        calls.update(since=since, max_results=max_results, corpus=corpus)
        return [ChinaRxivSearcher(email="")._parse(RECORD)]

    monkeypatch.setattr(server.chinarxiv_searcher, "list_new", fake)
    result = asyncio.run(server.list_new_chinarxiv("2026-09-01", max_results=5, corpus="russiarxiv"))

    assert calls == {"since": "2026-09-01", "max_results": 5, "corpus": "russiarxiv"}
    assert result[0]["paper_id"] == "chinaxiv-202604.00249"
