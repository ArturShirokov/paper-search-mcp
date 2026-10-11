from datetime import datetime
from unittest.mock import MagicMock

import pytest
import requests

from paper_search_mcp.academic_platforms.cyberleninka import CyberLeninkaSearcher

SEARCH_JSON = {
    "found": 1000,
    "articles": [
        {
            "name": "<b>КВАНТОВАЯ</b> КРИПТОГРАФИЯ &amp; <b>ВЫЧИСЛЕНИЯ</b>",
            "annotation": "Рассматриваются <b>квантовые</b> вычисления.",
            "link": "/article/n/kvantovaya-kriptografiya",
            "authors": ["Булатова Алина Рустемовна"],
            "year": 2025,
            "journal": "Вестник Пензенского государственного университета",
        }
    ],
}

OAI_PAGE_1 = """<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"><ListRecords>
  <record>
    <header>
      <identifier>https://cyberleninka.ru/article/n/first-article</identifier>
      <datestamp>2026-10-09T04:12:00.150863Z</datestamp>
    </header>
    <metadata>
      <oai_dc:dc xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/"
                 xmlns:dc="http://purl.org/dc/elements/1.1/">
        <dc:title>Первая статья</dc:title>
        <dc:creator>Фарходжон Боратов</dc:creator>
        <dc:publisher>ООО «in Science»</dc:publisher>
        <dc:identifier>https://cyberleninka.ru/article/n/first-article</dc:identifier>
      </oai_dc:dc>
    </metadata>
  </record>
  <resumptionToken cursor="1">TOKEN</resumptionToken>
</ListRecords></OAI-PMH>"""

OAI_PAGE_2 = OAI_PAGE_1.replace("first-article", "second-article").replace(
    "Первая", "Вторая"
).replace('<resumptionToken cursor="1">TOKEN</resumptionToken>', "")


def _response(json_data=None, content=b""):
    response = MagicMock()
    response.json.return_value = json_data
    response.content = content
    response.raise_for_status.return_value = None
    return response


@pytest.fixture
def searcher(monkeypatch):
    s = CyberLeninkaSearcher()
    monkeypatch.setattr("time.sleep", lambda _: None)
    return s


def test_search_parses_api_results(searcher):
    searcher.session.post = MagicMock(return_value=_response(SEARCH_JSON))

    papers = searcher.search("квантовые вычисления", max_results=3)

    payload = searcher.session.post.call_args.kwargs["json"]
    assert payload == {"mode": "articles", "q": "квантовые вычисления", "size": 3, "from": 0}
    [paper] = papers
    assert paper.source == "cyberleninka"
    assert paper.paper_id == "kvantovaya-kriptografiya"
    assert paper.title == "КВАНТОВАЯ КРИПТОГРАФИЯ & ВЫЧИСЛЕНИЯ"
    assert paper.abstract == "Рассматриваются квантовые вычисления."
    assert paper.authors == ["Булатова Алина Рустемовна"]
    assert paper.url == "https://cyberleninka.ru/article/n/kvantovaya-kriptografiya"
    assert paper.pdf_url == paper.url + "/pdf"
    assert paper.published_date == datetime(2025, 1, 1)
    assert paper.extra["journal"] == "Вестник Пензенского государственного университета"


def test_search_raises_on_http_error(searcher):
    failing = _response()
    failing.raise_for_status.side_effect = requests.HTTPError("503")
    searcher.session.post = MagicMock(return_value=failing)

    with pytest.raises(requests.HTTPError):
        searcher.search("anything")


def test_list_new_harvests_oai_pages_since_date(searcher):
    searcher.session.get = MagicMock(side_effect=[
        _response(content=OAI_PAGE_1.encode()),
        _response(content=OAI_PAGE_2.encode()),
    ])

    papers = searcher.list_new("2026-10-09", max_results=10, set="scopus")

    first_params = searcher.session.get.call_args_list[0].kwargs["params"]
    assert first_params == {
        "verb": "ListRecords", "metadataPrefix": "oai_dc",
        "from": "2026-10-09", "set": "scopus",
    }
    assert searcher.session.get.call_args_list[1].kwargs["params"] == {
        "verb": "ListRecords", "resumptionToken": "TOKEN",
    }
    assert [p.paper_id for p in papers] == ["first-article", "second-article"]
    first = papers[0]
    assert first.source == "cyberleninka"
    assert first.title == "Первая статья"
    assert first.authors == ["Фарходжон Боратов"]
    assert first.url == "https://cyberleninka.ru/article/n/first-article"
    assert first.pdf_url == first.url + "/pdf"
    assert first.updated_date == datetime(2026, 10, 9, 4, 12, 0)


def test_download_pdf_accepts_slug(searcher, tmp_path):
    searcher.session.get = MagicMock(return_value=_response(content=b"%PDF-1.4 test"))

    path = searcher.download_pdf("first-article", str(tmp_path))

    assert searcher.session.get.call_args.args[0] == (
        "https://cyberleninka.ru/article/n/first-article/pdf"
    )
    assert open(path, "rb").read() == b"%PDF-1.4 test"


def test_registered_in_server_and_cli():
    from paper_search_mcp import cli, server

    assert "cyberleninka" in server.ALL_SOURCES
    assert "cyberleninka" in cli.ALL_SOURCES
    assert isinstance(cli._get_searcher("cyberleninka"), CyberLeninkaSearcher)


def test_search_papers_dispatches_to_cyberleninka():
    import asyncio
    from unittest.mock import AsyncMock, patch

    from paper_search_mcp import server

    paper = {"paper_id": "x", "title": "T", "authors": "", "doi": "", "source": "cyberleninka"}
    with patch.object(server, "search_cyberleninka", new=AsyncMock(return_value=[paper])):
        result = asyncio.run(server.search_papers("q", sources="cyberleninka"))

    assert result["source_results"] == {"cyberleninka": 1}


def test_list_new_tool_returns_dicts(monkeypatch):
    import asyncio

    from paper_search_mcp import server

    calls = {}

    def fake_list_new(since, max_results, **kwargs):
        calls.update(since=since, max_results=max_results, **kwargs)
        return [CyberLeninkaSearcher()._parse_article(SEARCH_JSON["articles"][0])]

    monkeypatch.setattr(server.cyberleninka_searcher, "list_new", fake_list_new)
    result = asyncio.run(server.list_new_cyberleninka("2026-10-09", max_results=5, oai_set="wos"))

    assert calls == {"since": "2026-10-09", "max_results": 5, "set": "wos"}
    assert result[0]["paper_id"] == "kvantovaya-kriptografiya"
