from datetime import datetime
from unittest.mock import MagicMock

import pytest
import requests

from paper_search_mcp.academic_platforms.oaipmh import OAIPMHError
from paper_search_mcp.academic_platforms.ops import JxivSearcher, SciELOPreprintsSearcher

SITE = "https://jxiv.jst.go.jp/index.php/jxiv"


def _search_page(*ids):
    items = "".join(
        f'<h3 class="title"><a id="preprint-{i}" href="{SITE}/preprint/view/{i}">T{i}</a></h3>'
        for i in ids
    )
    return (
        f'<html><body><ul class="search_results">{items}</ul>'
        f'<a href="{SITE}/preprint/view/999">sidebar</a></body></html>'
    )


def _record(pid, datestamp="2026-10-06T09:33:54Z"):
    return f"""
<record>
  <header>
    <identifier>oai:ops.160.74.73.116:preprint/{pid}</identifier>
    <datestamp>{datestamp}</datestamp>
  </header>
  <metadata>
    <oai_dc:dc xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/"
               xmlns:dc="http://purl.org/dc/elements/1.1/">
      <dc:title xml:lang="en-US">Orbit determination {pid}</dc:title>
      <dc:title xml:lang="ja-JP">軌道決定</dc:title>
      <dc:creator>尾崎, 直哉</dc:creator>
      <dc:description xml:lang="en-US">

        Small spacecraft &amp;lt;5 kg.  </dc:description>
      <dc:description xml:lang="ja-JP">超小型宇宙機</dc:description>
      <dc:date>2026-10-09</dc:date>
      <dc:format>application/pdf</dc:format>
      <dc:identifier>{SITE}/preprint/view/{pid}</dc:identifier>
      <dc:identifier>10.51094/jxiv.{pid}</dc:identifier>
      <dc:relation>{SITE}/article/view/{pid}/14733</dc:relation>  <!-- Jxiv's legacy path -->
    </oai_dc:dc>
  </metadata>
</record>"""


def _oai(body):
    return f'<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">{body}</OAI-PMH>'.encode()


def _get_record(pid):
    return _oai(f"<GetRecord>{_record(pid)}</GetRecord>")


def _response(text="", content=b""):
    response = MagicMock()
    response.text = text
    response.content = content
    response.raise_for_status.return_value = None
    return response


@pytest.fixture
def searcher(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _: None)
    return JxivSearcher()


def test_search_fetches_full_records_for_search_hits(searcher):
    searcher.session.get = MagicMock(side_effect=[
        _response(text=_search_page(6732, 924)),
        _response(content=_get_record(6732)),
        _response(content=_get_record(924)),
    ])

    papers = searcher.search("orbit", max_results=2)

    calls = searcher.session.get.call_args_list
    assert calls[0].args[0] == f"{SITE}/search/search"
    assert calls[0].kwargs["params"]["query"] == "orbit"
    assert calls[1].kwargs["params"] == {
        "verb": "GetRecord", "metadataPrefix": "oai_dc",
        "identifier": "oai:ops.160.74.73.116:preprint/6732",
    }
    assert [p.paper_id for p in papers] == ["6732", "924"]
    paper = papers[0]
    assert paper.source == "jxiv"
    assert paper.title == "Orbit determination 6732"
    assert paper.abstract == "Small spacecraft <5 kg."  # OPS double-escapes HTML
    assert paper.authors == ["尾崎, 直哉"]
    assert paper.published_date == datetime(2026, 10, 9)
    assert paper.url == f"{SITE}/preprint/view/6732"
    assert paper.doi == "10.51094/jxiv.6732"
    assert paper.pdf_url == f"{SITE}/preprint/download/6732/14733"


def test_search_pages_until_enough_hits(searcher):
    searcher.session.get = MagicMock(side_effect=[
        _response(text=_search_page(1)),
        _response(text=_search_page(2)),
        _response(content=_get_record(1)),
        _response(content=_get_record(2)),
    ])

    papers = searcher.search("orbit", max_results=2)

    assert searcher.session.get.call_args_list[1].kwargs["params"]["searchPage"] == 2
    assert [p.paper_id for p in papers] == ["1", "2"]


def test_search_stops_when_a_page_adds_nothing(searcher):
    searcher.session.get = MagicMock(side_effect=[
        _response(text=_search_page(1)),
        _response(text=_search_page(1)),  # past the last page, or page ignored
        _response(content=_get_record(1)),
    ])

    assert [p.paper_id for p in searcher.search("orbit", max_results=10)] == ["1"]


def test_search_raises_on_http_error(searcher):
    failing = _response()
    failing.raise_for_status.side_effect = requests.HTTPError("503")
    searcher.session.get = MagicMock(return_value=failing)

    with pytest.raises(requests.HTTPError):
        searcher.search("orbit")


def test_search_raises_when_page_is_not_a_search_page(searcher):
    # A maintenance or redesigned page answering 200 must not pass as zero hits.
    searcher.session.get = MagicMock(return_value=_response(text="<html>Down for maintenance</html>"))

    with pytest.raises(ValueError):
        searcher.search("orbit")


def test_search_with_zero_hits_is_empty(searcher):
    searcher.session.get = MagicMock(return_value=_response(text=_search_page()))

    assert searcher.search("zzqx") == []


def test_search_raises_on_oai_error(searcher):
    searcher.session.get = MagicMock(side_effect=[
        _response(text=_search_page(1)),
        _response(content=_oai('<error code="idDoesNotExist">No such record</error>')),
    ])

    with pytest.raises(OAIPMHError):
        searcher.search("orbit", max_results=1)


def test_list_new_harvests_since_date(searcher):
    searcher.session.get = MagicMock(return_value=_response(
        content=_oai(f"<ListRecords>{_record(6732)}</ListRecords>")
    ))

    [paper] = searcher.list_new("2026-10-01")

    assert searcher.session.get.call_args.args[0] == f"{SITE}/oai"
    assert searcher.session.get.call_args.kwargs["params"] == {
        "verb": "ListRecords", "metadataPrefix": "oai_dc", "from": "2026-10-01",
    }
    assert paper.paper_id == "6732"
    assert paper.title == "Orbit determination 6732"
    assert paper.updated_date == datetime(2026, 10, 6, 9, 33, 54)


@pytest.mark.parametrize("since", ["", "yesterday", "2026/10/01"])
def test_list_new_rejects_bad_dates(searcher, since):
    searcher.session.get = MagicMock()

    with pytest.raises(ValueError):
        searcher.list_new(since)
    searcher.session.get.assert_not_called()


def test_list_new_raises_on_network_failure(searcher):
    searcher.session.get = MagicMock(side_effect=requests.ConnectionError("down"))

    with pytest.raises(requests.ConnectionError):
        searcher.list_new("2026-10-01")


def test_download_pdf_uses_record_galley(searcher, tmp_path):
    searcher.session.get = MagicMock(side_effect=[
        _response(content=_get_record(6732)),
        _response(content=b"%PDF-1.7 test"),
    ])

    path = searcher.download_pdf(f"{SITE}/preprint/view/6732", str(tmp_path))

    assert searcher.session.get.call_args.args[0] == f"{SITE}/preprint/download/6732/14733"
    assert path == str(tmp_path / "jxiv_6732.pdf")
    assert open(path, "rb").read() == b"%PDF-1.7 test"


def test_download_pdf_rejects_non_pdf(searcher, tmp_path):
    searcher.session.get = MagicMock(side_effect=[
        _response(content=_get_record(6732)),
        _response(content=b"<html>login</html>"),
    ])

    with pytest.raises(ValueError):
        searcher.download_pdf("6732", str(tmp_path))


def test_scielo_preprints_is_configured():
    s = SciELOPreprintsSearcher()
    assert s.base_url == "https://preprints.scielo.org/index.php/scielo/oai"
    assert s.OAI_REPO_ID == "ops.preprints.scielo.org"
    assert s.SOURCE == "scielo_preprints"
