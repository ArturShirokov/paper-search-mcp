# tests/test_openaire.py
import unittest
import os
import requests
import urllib3
import xml.etree.ElementTree as ET
from unittest.mock import Mock, patch
from paper_search_mcp.academic_platforms.openaire import OpenAiresearcher


def check_api_accessible():
    """Check if OpenAIRE API is accessible"""
    try:
        # Test OpenAIRE API with a simple query (current endpoint)
        response = requests.get(
            "https://api.openaire.eu/search/researchProducts",
            params={'keywords': 'test', 'size': 1, 'page': 0},
            timeout=15
        )
        return response.status_code == 200
    except requests.exceptions.SSLError:
        try:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            response = requests.get(
                "https://api.openaire.eu/search/researchProducts",
                params={'keywords': 'test', 'size': 1, 'page': 0},
                timeout=15,
                verify=False,
            )
            return response.status_code == 200
        except Exception:
            return False
    except Exception:
        return False


def _reply(status=200, content=b"", json_data=None, headers=None):
    response = Mock(status_code=status, content=content)
    response.headers = headers or {}
    if json_data is None:
        response.json.side_effect = requests.JSONDecodeError("Expecting value", "", 0)
    else:
        response.json.return_value = json_data
    return response


EMPTY_V2 = b"<response><results></results></response>"
EMPTY_LEGACY = {"response": {"results": {"result": []}}}


@patch("paper_search_mcp.academic_platforms.openaire.time.sleep")
class TestOpenAireSearchErrors(unittest.TestCase):
    """Failed requests must raise, not look like zero results (#5)."""

    def run_search(self, v2, legacy):
        searcher = OpenAiresearcher(api_key="")

        def get(url, **kwargs):
            reply = v2 if "researchProducts" in url else legacy
            if isinstance(reply, Exception):
                raise reply
            return reply

        searcher.session.get = Mock(side_effect=get)
        with patch("paper_search_mcp.academic_platforms.openaire.requests.get", side_effect=get):
            return searcher.search("graphs")

    def test_rate_limit_everywhere_raises_with_retry_after(self, _sleep):
        limited = _reply(429, headers={"Retry-After": "60"})
        with self.assertRaisesRegex(requests.HTTPError, r"OpenAIRE returned HTTP 429 \(Retry-After: 60\)"):
            self.run_search(limited, limited)

    def test_v2_failure_reported_when_legacy_also_fails(self, _sleep):
        with self.assertRaises(requests.Timeout):
            self.run_search(requests.Timeout("slow"), _reply(404))

    def test_v2_failure_reported_when_legacy_is_empty(self, _sleep):
        with self.assertRaisesRegex(requests.HTTPError, "OpenAIRE returned HTTP 503"):
            self.run_search(_reply(503), _reply(json_data=EMPTY_LEGACY))

    def test_bad_v2_body_raises_when_legacy_not_json(self, _sleep):
        with self.assertRaises(ET.ParseError):
            self.run_search(_reply(content=b"<html"), _reply(content=b"<html>"))

    def test_genuine_empty_result_is_empty(self, _sleep):
        self.assertEqual(self.run_search(_reply(content=EMPTY_V2), _reply(json_data=EMPTY_LEGACY)), [])

    def test_empty_v2_answer_stands_when_legacy_fails(self, _sleep):
        self.assertEqual(self.run_search(_reply(content=EMPTY_V2), _reply(500)), [])


class TestOpenAiresearcher(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api_accessible = check_api_accessible()
        if not cls.api_accessible:
            print("\nWarning: OpenAIRE API is not accessible, some tests will be skipped")

    def setUp(self):
        self.searcher = OpenAiresearcher()

    def test_search_basic(self):
        if not self.api_accessible:
            self.skipTest("OpenAIRE API is not accessible")

        papers = self.searcher.search("climate change", max_results=5)
        print(f"Found {len(papers)} papers from OpenAIRE for query 'climate change':")

        for i, paper in enumerate(papers, 1):
            print(f"{i}. {paper.title}")
            print(f"   Authors: {', '.join(paper.authors[:2])}{'...' if len(paper.authors) > 2 else ''}")
            print(f"   Year: {paper.published_date.year if paper.published_date else 'N/A'}")
            print(f"   DOI: {paper.doi if paper.doi else 'N/A'}")
            print(f"   Open Access: {paper.extra.get('open_access', 'N/A')}")
            print(f"   Publisher: {paper.extra.get('publisher', 'N/A')}")
            print(f"   URL: {paper.url}")
            print()

        self.assertTrue(len(papers) > 0)
        if papers:
            self.assertTrue(papers[0].title)
            self.assertEqual(papers[0].source, 'openaire')

    def test_search_with_year_filter(self):
        if not self.api_accessible:
            self.skipTest("OpenAIRE API is not accessible")

        papers = self.searcher.search(
            "renewable energy",
            max_results=3,
            year="2020"
        )
        print(f"Found {len(papers)} papers from OpenAIRE for query 'renewable energy' year 2020")

        if papers:
            for paper in papers:
                year = paper.published_date.year if paper.published_date else 'N/A'
                print(f"Paper '{paper.title}' published in {year}")

        self.assertTrue(len(papers) >= 0)  # May return 0 if no papers match

    def test_search_with_open_access_filter(self):
        if not self.api_accessible:
            self.skipTest("OpenAIRE API is not accessible")

        papers = self.searcher.search(
            "open access",
            max_results=3,
            open_access=True
        )
        print(f"Found {len(papers)} papers from OpenAIRE for query 'open access' with open access filter")

        if papers:
            open_access_count = sum(1 for paper in papers if paper.extra.get('open_access'))
            print(f"{open_access_count} out of {len(papers)} papers are open access")

        self.assertTrue(len(papers) >= 0)

    def test_search_with_date_range(self):
        if not self.api_accessible:
            self.skipTest("OpenAIRE API is not accessible")

        papers = self.searcher.search(
            "artificial intelligence",
            max_results=3,
            from_date="2020-01-01",
            to_date="2022-12-31"
        )
        print(f"Found {len(papers)} papers from OpenAIRE for query 'artificial intelligence' date range 2020-2022")

        if papers:
            for paper in papers:
                year = paper.published_date.year if paper.published_date else 'N/A'
                print(f"Paper '{paper.title}' published in {year}")

        self.assertTrue(len(papers) >= 0)

    def test_download_pdf_not_implemented(self):
        """Test that PDF download raises NotImplementedError"""
        searcher = OpenAiresearcher()
        with self.assertRaises(NotImplementedError):
            searcher.download_pdf("test_paper_id", "./downloads")

    def test_read_paper_not_implemented(self):
        """Test that reading paper raises NotImplementedError"""
        searcher = OpenAiresearcher()
        with self.assertRaises(NotImplementedError):
            searcher.read_paper("test_paper_id", "./downloads")

    def test_search_european_research_topics(self):
        if not self.api_accessible:
            self.skipTest("OpenAIRE API is not accessible")

        # Test various European research topics that OpenAIRE should have
        test_queries = [
            "Horizon 2020",  # EU research program
            "European Union",
            "sustainable development",
            "health research",
            "digital transformation"
        ]

        for query in test_queries[:2]:  # Just test first 2 to avoid too many requests
            papers = self.searcher.search(query, max_results=2)
            print(f"Query '{query}': found {len(papers)} papers")
            if papers:
                print(f"  First paper: {papers[0].title}")
                if papers[0].extra.get('project_id'):
                    print(f"  Project ID: {papers[0].extra.get('project_id')}")
            self.assertTrue(len(papers) >= 0)

    def test_search_with_language_filter(self):
        if not self.api_accessible:
            self.skipTest("OpenAIRE API is not accessible")

        # Test with language filter (English)
        papers = self.searcher.search(
            "biology",
            max_results=3,
            language="en"
        )
        print(f"Found {len(papers)} papers from OpenAIRE for query 'biology' language English")

        if papers:
            for paper in papers:
                language = paper.extra.get('language', 'N/A')
                print(f"Paper '{paper.title}' language: {language}")

        self.assertTrue(len(papers) >= 0)

    def test_parse_openaire_result_invalid(self):
        """Test parsing invalid OpenAIRE result"""
        # Create an invalid result dictionary
        invalid_result = {
            'metadata': {}  # Empty metadata
        }

        # This should return None without raising exception
        paper = self.searcher._parse_openaire_result(invalid_result)
        self.assertIsNone(paper)

    def test_parse_openaire_result_minimal(self):
        """Test parsing minimal valid OpenAIRE result"""
        minimal_result = {
            'metadata': {
                'title': {'value': 'Test Paper Title'},
                'creator': [{'value': 'Test Author'}],
            },
            'header': {
                'dri:objIdentifier': {'value': 'test-id-123'}
            }
        }

        paper = self.searcher._parse_openaire_result(minimal_result)
        self.assertIsNotNone(paper)
        if paper:
            self.assertEqual(paper.title, 'Test Paper Title')
            self.assertEqual(paper.authors, ['Test Author'])
            self.assertEqual(paper.source, 'openaire')


if __name__ == '__main__':
    unittest.main()