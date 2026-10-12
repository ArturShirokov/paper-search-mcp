import unittest
import requests
from unittest.mock import Mock

import pytest

from paper_search_mcp.academic_platforms.zenodo import ZenodoSearcher


def check_api_accessible() -> bool:
    """Check whether Zenodo API is reachable."""
    try:
        response = requests.get(
            "https://zenodo.org/api/records",
            params={"q": "machine learning", "size": 1},
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False


class TestZenodoSearcher(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api_accessible = check_api_accessible()
        if not cls.api_accessible:
            print("\nWarning: Zenodo API is not accessible, network tests will be skipped")

    def setUp(self):
        self.searcher = ZenodoSearcher()

    def test_search_basic(self):
        if not self.api_accessible:
            self.skipTest("Zenodo API is not accessible")

        papers = self.searcher.search("machine learning", max_results=3)
        self.assertIsInstance(papers, list)
        self.assertTrue(len(papers) >= 0)

        if papers:
            first = papers[0]
            self.assertTrue(first.title)
            self.assertEqual(first.source, "zenodo")

    def test_extract_record_id(self):
        self.assertEqual(self.searcher._extract_record_id("10.5281/zenodo.1234567"), "1234567")
        self.assertEqual(self.searcher._extract_record_id("1234567"), "1234567")
        self.assertEqual(self.searcher._extract_record_id("not-a-zenodo-id"), "")

    def test_parse_record_minimal(self):
        hit = {
            "id": 12345,
            "doi": "10.5281/zenodo.12345",
            "metadata": {
                "title": "Zenodo Parser Test",
                "creators": [{"name": "Alice Example"}, {"name": "Bob Example"}],
                "description": "<p>Test abstract</p>",
                "publication_date": "2024-01-15",
            },
            "files": [
                {
                    "key": "paper.pdf",
                    "links": {"self": "https://zenodo.org/records/12345/files/paper.pdf"},
                }
            ],
            "links": {"html": "https://zenodo.org/record/12345"},
        }

        paper = self.searcher._parse_record(hit)
        self.assertIsNotNone(paper)
        if paper:
            self.assertEqual(paper.source, "zenodo")
            self.assertEqual(paper.title, "Zenodo Parser Test")
            self.assertEqual(paper.doi, "10.5281/zenodo.12345")
            self.assertTrue(paper.pdf_url.endswith("paper.pdf"))

    def test_parse_record_invalid(self):
        paper = self.searcher._parse_record({"metadata": {}})
        self.assertIsNone(paper)


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
    searcher = ZenodoSearcher()
    searcher.session.get = Mock(return_value=reply(429, headers={"Retry-After": "60"}))
    with pytest.raises(requests.HTTPError, match="Retry-After: 60"):
        searcher.search("graphs")


def test_search_network_error_raises():
    searcher = ZenodoSearcher()
    searcher.session.get = Mock(side_effect=requests.ConnectionError("down"))
    with pytest.raises(requests.ConnectionError):
        searcher.search("graphs")


def test_search_non_json_raises():
    searcher = ZenodoSearcher()
    searcher.session.get = Mock(return_value=reply(content=b"<html>", headers={"Content-Type": "text/html"}))
    with pytest.raises(ValueError, match="non-JSON.*text/html"):
        searcher.search("graphs")


def test_search_genuine_empty_is_empty():
    searcher = ZenodoSearcher()
    searcher.session.get = Mock(return_value=reply(json_data={"hits": {"hits": [], "total": 0}}))
    assert searcher.search("graphs") == []


def test_search_wrong_shape_raises():
    searcher = ZenodoSearcher()
    searcher.session.get = Mock(return_value=reply(json_data={"status": 400, "message": "Invalid query"}))
    with pytest.raises(ValueError, match="Zenodo"):
        searcher.search("graphs")


if __name__ == "__main__":
    unittest.main()
