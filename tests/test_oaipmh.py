import xml.etree.ElementTree as ET

import pytest
import requests

from paper_search_mcp.academic_platforms.oaipmh import OAIPMHError, OAIPMHSearcher

RECORD = """
<record xmlns="http://www.openarchives.org/OAI/2.0/">
  <header>
    <identifier>https://example.org/article/1</identifier>
    <datestamp>2026-10-09T04:12:00Z</datestamp>
  </header>
  <metadata>
    <oai_dc:dc xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/"
               xmlns:dc="http://purl.org/dc/elements/1.1/">
      <dc:title>Leaf title</dc:title>
      <dc:creator>Ada Lovelace</dc:creator>
      <dc:description>Leaf abstract</dc:description>
      <dc:date>2026-10-09</dc:date>
      <dc:publisher>Example Press</dc:publisher>
      <dc:language>ru</dc:language>
    </oai_dc:dc>
  </metadata>
</record>
"""


def test_parse_oai_record_reads_childless_dc_elements():
    # ElementTree elements without children are falsy, so `find(a) or find(b)`
    # used to discard every leaf field.
    paper = OAIPMHSearcher("https://example.org/oai")._parse_oai_record(ET.fromstring(RECORD))

    assert paper.title == "Leaf title"
    assert paper.abstract == "Leaf abstract"
    assert paper.published_date.year == 2026
    assert paper.url == "https://example.org/article/1"
    assert paper.extra["publisher"] == "Example Press"
    assert paper.extra["language"] == "ru"


def test_empty_dc_elements_become_empty_strings():
    record = RECORD.replace("<dc:title>Leaf title</dc:title>", "<dc:title/>").replace(
        "<dc:description>Leaf abstract</dc:description>", "<dc:description/>"
    )
    searcher = OAIPMHSearcher("https://example.org/oai")
    paper = searcher._parse_oai_record(ET.fromstring(record))

    assert paper.title == ""
    assert paper.abstract == ""
    assert searcher._matches_query(paper, "lovelace")


def _oai_reply(body: str) -> str:
    return f'<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">{body}</OAI-PMH>'


def _searcher_returning(monkeypatch, response):
    searcher = OAIPMHSearcher("https://example.org/oai")
    monkeypatch.setattr(searcher.session, "get", lambda *a, **kw: response)
    return searcher


class _Reply:
    def __init__(self, xml: str):
        self.content = xml.encode()

    def raise_for_status(self):
        pass


def test_network_failure_raises(monkeypatch):
    searcher = OAIPMHSearcher("https://example.org/oai")

    def boom(*a, **kw):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(searcher.session, "get", boom)
    monkeypatch.setattr("paper_search_mcp.academic_platforms.oaipmh.time.sleep", lambda s: None)
    with pytest.raises(requests.RequestException):
        searcher.search("", from_date="2026-10-01")


@pytest.mark.parametrize("code", ["badArgument", "badResumptionToken", "cannotDisseminateFormat"])
def test_oai_error_reply_raises(monkeypatch, code):
    reply = _Reply(_oai_reply(f'<error code="{code}">nope</error>'))
    with pytest.raises(OAIPMHError) as excinfo:
        _searcher_returning(monkeypatch, reply).search("")
    assert excinfo.value.code == code


def test_no_records_match_is_empty_result(monkeypatch):
    reply = _Reply(_oai_reply('<error code="noRecordsMatch">none</error>'))
    assert _searcher_returning(monkeypatch, reply).search("", from_date="2026-10-01") == []


def test_records_still_harvested(monkeypatch):
    reply = _Reply(_oai_reply(f"<ListRecords>{RECORD}</ListRecords>"))
    papers = _searcher_returning(monkeypatch, reply).search("")
    assert [p.title for p in papers] == ["Leaf title"]


def test_non_oai_reply_raises(monkeypatch):
    # BASE answers an unlisted IP with a bare <error>, outside the OAI namespace.
    reply = _Reply("<error>Access denied for IP address 192.0.2.1.</error>")
    with pytest.raises(OAIPMHError, match="Access denied"):
        _searcher_returning(monkeypatch, reply).search("")


class _Status:
    """An HTTP failure reply, as requests would build it."""

    def __init__(self, status: int, retry_after: str = ""):
        self.status_code = status
        self.headers = {"Retry-After": retry_after} if retry_after else {}

    def raise_for_status(self):
        raise requests.HTTPError(f"{self.status_code} error", response=self)


TOKEN_PAGE = _Reply(_oai_reply(
    f'<ListRecords>{RECORD}<resumptionToken cursor="0">page2</resumptionToken></ListRecords>'
))
LAST_PAGE = _Reply(_oai_reply(f"<ListRecords>{RECORD.replace('Leaf title', 'Second')}</ListRecords>"))


def _searcher_replaying(monkeypatch, *replies):
    """Searcher whose GETs answer `replies` in order; records sleeps and calls."""
    searcher = OAIPMHSearcher("https://example.org/oai")
    queue, calls, sleeps = list(replies), [], []

    def get(url, params=None, **kw):
        calls.append(params)
        reply = queue.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(searcher.session, "get", get)
    monkeypatch.setattr("paper_search_mcp.academic_platforms.oaipmh.time.sleep", sleeps.append)
    return searcher, calls, sleeps


@pytest.mark.parametrize("failure", [
    _Status(503),
    _Status(429),
    requests.ConnectionError("reset"),
    requests.Timeout("slow"),
    requests.exceptions.ChunkedEncodingError("dropped mid-body"),
])
def test_transient_failure_on_resumption_page_is_retried(monkeypatch, failure):
    searcher, calls, _ = _searcher_replaying(monkeypatch, TOKEN_PAGE, failure, LAST_PAGE)

    papers = searcher.search("", max_results=10)

    assert [p.title for p in papers] == ["Leaf title", "Second"]
    assert calls[1] == calls[2] == {"verb": "ListRecords", "resumptionToken": "page2"}


def test_short_retry_after_is_honoured(monkeypatch):
    searcher, _, sleeps = _searcher_replaying(monkeypatch, _Status(429, "7"), LAST_PAGE)
    searcher.search("")
    assert 7 in sleeps


def test_long_retry_after_gives_up_at_once(monkeypatch):
    searcher, calls, _ = _searcher_replaying(monkeypatch, _Status(429, "3600"))
    with pytest.raises(requests.HTTPError):
        searcher.search("")
    assert len(calls) == 1


def test_persistent_failure_raises_instead_of_partial_list(monkeypatch):
    searcher, calls, _ = _searcher_replaying(
        monkeypatch, TOKEN_PAGE, *[_Status(503)] * OAIPMHSearcher.MAX_ATTEMPTS
    )
    with pytest.raises(requests.HTTPError):
        searcher.search("", max_results=10)
    assert len(calls) == 1 + OAIPMHSearcher.MAX_ATTEMPTS


@pytest.mark.parametrize("reply", [
    _Status(404),
    _Reply(_oai_reply('<error code="badResumptionToken">expired</error>')),
    _Reply("not xml"),
])
def test_non_transient_failure_is_not_retried(monkeypatch, reply):
    searcher, calls, _ = _searcher_replaying(monkeypatch, TOKEN_PAGE, reply)
    with pytest.raises((requests.HTTPError, OAIPMHError, ET.ParseError)):
        searcher.search("", max_results=10)
    assert len(calls) == 2
