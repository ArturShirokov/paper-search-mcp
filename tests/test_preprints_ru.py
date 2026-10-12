from datetime import datetime
from unittest.mock import MagicMock

import pytest
import requests

from paper_search_mcp.academic_platforms.preprints_ru import PreprintsRuSearcher

SITE = "https://preprints.ru"


def _search_page(*ids, found=None):
    items = "".join(
        f"""<div class="result article-content">
              <div class="title">
                  <a href="{SITE}/article/{i}">
                      Title {i}...
                  </a>
              </div>
            </div>"""
        for i in ids
    )
    found = len(ids) if found is None else found
    return (
        f'<html><body><a href="{SITE}/article/new">submit</a>'
        f"<span>найдено: {found}</span>"
        f'<div class="result-list">{items}</div></body></html>'
    )


def _article_page(aid, doi=True, pdf=True, abstract="Первая строка &amp; формула.\nВторая строка."):
    return f"""<html><head>
<meta name="citation_publication_date" content="2026/10/05" />
<meta name="citation_title" content="ИНВАРИАНТНОЕ УСРЕДНЕНИЕ &quot;ядра&quot; {aid}">
<meta name="citation_author" content="Михаил Семенович Батанов">
<meta name="citation_author" content="Ирина Петровна Смирнова">
</head><body>
<div class="article-content col main-block">
  <div class="title">ИНВАРИАНТНОЕ УСРЕДНЕНИЕ</div>
  <div class="date" style="margin-bottom: 10px"><span>2026-08-08</span></div>
  {f'<div class="doi"><a href="https://doi.org/10.24108/preprints-311{aid}">https://doi.org/10.24108/preprints-311{aid}</a></div>' if doi else ''}
  {f'<div class="file"><a href="{SITE}/files/60{aid}" target="_blank"><button>PDF</button></a></div>' if pdf else ''}
  <div class="abstract">
      <p>{abstract}</p>
  </div>
  <div class="ref"><p><i>PREPRINTS.RU. https://doi.org/10.24108/preprints-0000000</i></p></div>
</div></body></html>"""


def _response(text="", content=b""):
    response = MagicMock()
    response.text = text
    response.content = content
    response.raise_for_status.return_value = None
    return response


def _article(aid, **kwargs):
    return _response(text=_article_page(aid, **kwargs))


@pytest.fixture
def searcher():
    return PreprintsRuSearcher()


def test_search_fetches_article_pages_for_search_hits(searcher):
    searcher.session.get = MagicMock(side_effect=[
        _response(text=_search_page(4414, 1160)),
        _article(4414),
        _article(1160),
    ])

    papers = searcher.search("ядро", max_results=2)

    calls = searcher.session.get.call_args_list
    assert calls[0].args[0] == f"{SITE}/search"
    assert calls[0].kwargs["params"] == {"page": 1, "search_query": "ядро"}
    assert calls[1].args[0] == f"{SITE}/article/4414"
    assert [p.paper_id for p in papers] == ["4414", "1160"]
    paper = papers[0]
    assert paper.source == "preprints_ru"
    assert paper.title == 'ИНВАРИАНТНОЕ УСРЕДНЕНИЕ "ядра" 4414'
    assert paper.authors == ["Михаил Семенович Батанов", "Ирина Петровна Смирнова"]
    assert paper.abstract == "Первая строка & формула.\nВторая строка."
    # The page's visible date is submission; the citation date is publication.
    assert paper.published_date == datetime(2026, 10, 5)
    assert paper.url == f"{SITE}/article/4414"
    assert paper.doi == "10.24108/preprints-3114414"
    assert paper.pdf_url == f"{SITE}/files/604414"


def test_search_pages_until_enough_hits(searcher):
    searcher.session.get = MagicMock(side_effect=[
        _response(text=_search_page(1, found=30)),
        _article(1),
        _response(text=_search_page(2, found=30)),
        _article(2),
    ])

    papers = searcher.search("ядро", max_results=2)

    assert searcher.session.get.call_args_list[2].kwargs["params"]["page"] == 2
    assert [p.paper_id for p in papers] == ["1", "2"]


def test_search_stops_at_the_reported_total(searcher):
    # A page past the end has no result list, so it must never be requested.
    searcher.session.get = MagicMock(side_effect=[
        _response(text=_search_page(1, 2)),
        _article(1),
        _article(2),
    ])

    papers = searcher.search("ядро", max_results=10)

    assert [p.paper_id for p in papers] == ["1", "2"]


def test_search_with_zero_hits_returns_empty(searcher):
    searcher.session.get = MagicMock(return_value=_response(text=_search_page()))

    assert searcher.search("zzqqxx") == []
    assert searcher.session.get.call_count == 1


@pytest.mark.parametrize("query", [
    "ядро",  # inflected: the title has "ядра"
    "Усреднение ядра",
    "формулы",  # abstract only
    '"инвариантные усреднения"',
])
def test_search_keeps_hits_containing_the_query_stems(searcher, query):
    searcher.session.get = MagicMock(side_effect=[
        _response(text=_search_page(1)),
        _article(1),
    ])

    assert [p.paper_id for p in searcher.search(query)] == ["1"]


@pytest.mark.parametrize("query", [
    "OCR",
    "ядро OCR",  # every word must match
    "ядерный",
    "среднее",  # "усреднение" contains it, but not at a word start
])
def test_search_drops_hits_without_the_query_stems(searcher, query):
    # The site's search never comes back empty; its filler must not pass.
    searcher.session.get = MagicMock(side_effect=[
        _response(text=_search_page(1)),
        _article(1),
    ])

    assert searcher.search(query) == []


def test_search_matches_russian_inflection(searcher):
    searcher.session.get = MagicMock(side_effect=[
        _response(text=_search_page(1)),
        _article(1, abstract="Методы распознавания кириллических текстов."),
    ])

    assert len(searcher.search("распознавание текста")) == 1


def test_search_matches_inflection_of_short_stems(searcher):
    # Stripping "ть" from "сеть" leaves two letters; keep a 3-letter prefix.
    searcher.session.get = MagicMock(side_effect=[
        _response(text=_search_page(1)),
        _article(1, abstract="Свёрточные нейронные сети."),
    ])

    assert len(searcher.search("нейронная сеть")) == 1


def test_search_skips_misses_until_enough_matches(searcher):
    searcher.session.get = MagicMock(side_effect=[
        _response(text=_search_page(1, 2, 3)),
        _article(1, abstract="Другое."),
        _article(2),
        _article(3),
    ])

    papers = searcher.search("формула", max_results=1)

    assert [p.paper_id for p in papers] == ["2"]
    assert searcher.session.get.call_count == 3


def test_search_gives_up_after_ten_misses_in_a_row(searcher):
    ids = range(1, 31)
    searcher.session.get = MagicMock(side_effect=[
        _response(text=_search_page(*ids)),
        *[_article(i, abstract="Другое.") for i in range(1, 10)],
        _article(10),  # a match resets the streak
        *[_article(i, abstract="Другое.") for i in range(11, 21)],
    ])

    papers = searcher.search("формула")

    assert [p.paper_id for p in papers] == ["10"]
    assert searcher.session.get.call_count == 1 + 20


def test_search_raises_on_a_page_without_results_count(searcher):
    # A 200 maintenance or redesigned page must not pass as "no results".
    searcher.session.get = MagicMock(return_value=_response(text="<html>Технические работы</html>"))

    with pytest.raises(ValueError, match="preprints_ru"):
        searcher.search("ядро")


def test_search_raises_on_http_errors(searcher):
    response = _response()
    response.raise_for_status.side_effect = requests.HTTPError("503")
    searcher.session.get = MagicMock(return_value=response)

    with pytest.raises(requests.HTTPError):
        searcher.search("ядро")


def test_article_without_doi_or_pdf_keeps_empty_strings(searcher):
    searcher.session.get = MagicMock(side_effect=[
        _response(text=_search_page(7)),
        _article(7, doi=False, pdf=False),
    ])

    paper = searcher.search("ядро")[0]

    # The citation block's DOI is a different element; don't pick it up.
    assert paper.doi == ""
    assert paper.pdf_url == ""


def test_removed_article_redirecting_home_is_skipped(searcher):
    searcher.session.get = MagicMock(side_effect=[
        _response(text=_search_page(7, 8)),
        _response(text="<html>home</html>"),
        _article(8),
    ])

    assert [p.paper_id for p in searcher.search("ядро")] == ["8"]


def test_list_new_filters_by_publication_date(searcher):
    searcher.session.get = MagicMock(side_effect=[
        _response(text=_search_page(4939)),
        _article(4939),
    ])

    papers = searcher.list_new("2026-10-05")

    assert searcher.session.get.call_args_list[0].kwargs["params"] == {
        "page": 1, "search_query": "", "filters[gte][]": "2026-10-05",
    }
    assert [p.paper_id for p in papers] == ["4939"]


@pytest.mark.parametrize("since", ["", "2026-13-01", "05.10.2026"])
def test_list_new_rejects_malformed_dates(searcher, since):
    searcher.session.get = MagicMock()

    with pytest.raises(ValueError):
        searcher.list_new(since)
    searcher.session.get.assert_not_called()


def test_download_pdf_saves_the_article_file(searcher, tmp_path):
    searcher.session.get = MagicMock(side_effect=[
        _article(4939),
        _response(content=b"%PDF-1.6 body"),
    ])

    path = searcher.download_pdf(f"{SITE}/article/4939/", str(tmp_path))

    assert searcher.session.get.call_args_list[1].args[0] == f"{SITE}/files/604939"
    assert path == str(tmp_path / "preprints_ru_4939.pdf")
    assert (tmp_path / "preprints_ru_4939.pdf").read_bytes() == b"%PDF-1.6 body"


def test_download_pdf_rejects_non_pdf(searcher, tmp_path):
    searcher.session.get = MagicMock(side_effect=[
        _article(4939),
        _response(content=b"<html>login</html>"),
    ])

    with pytest.raises(ValueError, match="no PDF"):
        searcher.download_pdf("4939", str(tmp_path))


def test_download_pdf_raises_when_article_has_no_file(searcher, tmp_path):
    searcher.session.get = MagicMock(return_value=_article(4939, pdf=False))

    with pytest.raises(ValueError, match="no PDF"):
        searcher.download_pdf("4939", str(tmp_path))


def test_download_pdf_takes_the_article_id_from_a_version_url(searcher, tmp_path):
    searcher.session.get = MagicMock(side_effect=[
        _article(4414),
        _response(content=b"%PDF-1.6 body"),
    ])

    path = searcher.download_pdf(f"{SITE}/article/4414/version/1", str(tmp_path))

    assert searcher.session.get.call_args_list[0].args[0] == f"{SITE}/article/4414"
    assert path.endswith("preprints_ru_4414.pdf")
