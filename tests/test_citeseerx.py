import unittest
import requests
import pytest
from unittest.mock import Mock, patch

from paper_search_mcp.academic_platforms.citeseerx import CiteSeerXSearcher


def check_api_accessible() -> bool:
    """Check whether CiteSeerX search API is reachable and *not* redirecting to archive."""
    try:
        response = requests.get(
            "https://citeseerx.ist.psu.edu/api/search",
            params={"q": "test", "max": 1, "start": 0},
            timeout=10,
        )
        return response.status_code == 200 and "web.archive.org" not in response.url
    except Exception:
        return False


class TestCiteSeerXSearcher(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api_accessible = check_api_accessible()
        if not cls.api_accessible:
            print("\nWarning: CiteSeerX API is not accessible, network tests will be skipped")

    def setUp(self):
        self.searcher = CiteSeerXSearcher()

    def test_search_basic(self):
        if not self.api_accessible:
            self.skipTest("CiteSeerX API is not accessible")

        papers = self.searcher.search("machine learning", max_results=3)
        self.assertIsInstance(papers, list)
        self.assertTrue(len(papers) >= 0)

        if papers:
            first = papers[0]
            self.assertTrue(first.title)
            self.assertEqual(first.source, "citeseerx")

    def test_parse_citeseerx_result_minimal(self):
        result = {
            "info": {
                "id": "12345",
                "title": "A Test Paper",
                "authors": [{"name": "Alice"}, {"name": "Bob"}],
                "abstract": "Test abstract for parser.",
                "year": "2024",
                "venue": "TestConf",
                "doi": "10.1000/test-doi",
                "url": "https://citeseerx.ist.psu.edu/viewdoc/summary?doi=10.1.1.1",
                "pdf": "https://example.org/test.pdf",
            }
        }

        paper = self.searcher._parse_citeseerx_result(result)
        self.assertIsNotNone(paper)
        if paper:
            self.assertEqual(paper.title, "A Test Paper")
            self.assertEqual(paper.source, "citeseerx")
            self.assertEqual(paper.doi, "10.1000/test-doi")
            self.assertEqual(paper.authors, ["Alice", "Bob"])

    def test_parse_citeseerx_result_invalid(self):
        paper = self.searcher._parse_citeseerx_result({"info": {}})
        self.assertIsNone(paper)

    def test_archive_redirect_raises(self):
        """An API redirected to web.archive.org is an outage, not zero results."""
        archive_response = Mock(status_code=200, headers={})
        archive_response.url = "https://web.archive.org/web/20251230112235/https://citeseerx.ist.psu.edu/api/search"

        with patch.object(self.searcher.session, "get", return_value=archive_response):
            with self.assertRaisesRegex(requests.HTTPError, "web archive"):
                self.searcher.search("machine learning", max_results=3)


def reply(status=200, json_data=None, content=b"", headers=None):
    response = Mock(status_code=status, content=content, text=content.decode(), url="https://example.org/api")
    response.headers = headers or {}
    if json_data is None:
        response.json.side_effect = requests.JSONDecodeError("Expecting value", "", 0)
    else:
        response.json.return_value = json_data
    return response


# --- errors must raise, not look like zero results (#5) ---------------------

def test_search_429_raises_with_retry_after():
    searcher = CiteSeerXSearcher()
    searcher.session.get = Mock(return_value=reply(429, headers={"Retry-After": "60"}))
    with pytest.raises(requests.HTTPError, match="Retry-After: 60"):
        searcher.search("graphs")


def test_search_network_error_raises():
    searcher = CiteSeerXSearcher()
    searcher.session.get = Mock(side_effect=requests.ConnectionError("down"))
    with pytest.raises(requests.ConnectionError):
        searcher.search("graphs")


def test_search_non_json_raises():
    searcher = CiteSeerXSearcher()
    searcher.session.get = Mock(return_value=reply(content=b"<html>", headers={"Content-Type": "text/html"}))
    with pytest.raises(ValueError, match="non-JSON.*text/html"):
        searcher.search("graphs")


def test_search_genuine_empty_is_empty():
    searcher = CiteSeerXSearcher()
    searcher.session.get = Mock(return_value=reply(json_data={"result": {"hits": {"hit": []}}}))
    assert searcher.search("graphs") == []


if __name__ == "__main__":
    unittest.main()
