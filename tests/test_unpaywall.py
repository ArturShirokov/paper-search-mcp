import unittest
from unittest.mock import Mock
from datetime import datetime

import requests

from paper_search_mcp.academic_platforms.unpaywall import UnpaywallResolver, UnpaywallSearcher


class TestUnpaywallResolver(unittest.TestCase):
    def test_has_api_access_false_without_email(self):
        resolver = UnpaywallResolver(email="")
        self.assertFalse(resolver.has_api_access())

    def test_resolve_best_pdf_url_without_email(self):
        resolver = UnpaywallResolver(email="")
        self.assertIsNone(resolver.resolve_best_pdf_url("10.1000/test"))

    def test_resolve_best_pdf_url_from_best_location(self):
        resolver = UnpaywallResolver(email="test@example.com")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "best_oa_location": {"url_for_pdf": "https://example.org/paper.pdf"},
            "oa_locations": [],
        }
        mock_response.raise_for_status.return_value = None

        resolver.session.get = Mock(return_value=mock_response)

        pdf_url = resolver.resolve_best_pdf_url("10.1000/test")
        self.assertEqual(pdf_url, "https://example.org/paper.pdf")

    def test_resolve_best_pdf_url_falls_back_to_oa_locations(self):
        resolver = UnpaywallResolver(email="test@example.com")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "best_oa_location": {},
            "oa_locations": [
                {"url": "https://example.org/article"},
                {"url_for_pdf": "https://example.org/final.pdf"},
            ],
        }
        mock_response.raise_for_status.return_value = None

        resolver.session.get = Mock(return_value=mock_response)

        pdf_url = resolver.resolve_best_pdf_url("10.1000/test")
        self.assertEqual(pdf_url, "https://example.org/article")

    def test_get_paper_by_doi_maps_fields(self):
        resolver = UnpaywallResolver(email="test@example.com")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "title": "OA Paper",
            "doi_url": "https://doi.org/10.1000/test",
            "published_date": "2024-01-15",
            "is_oa": True,
            "oa_status": "gold",
            "z_authors": [{"given": "Alice", "family": "Example"}],
            "best_oa_location": {
                "url": "https://example.org/landing",
                "url_for_pdf": "https://example.org/paper.pdf",
                "host_type": "publisher",
                "license": "cc-by",
                "version": "publishedVersion",
            },
        }
        mock_response.raise_for_status.return_value = None

        resolver.session.get = Mock(return_value=mock_response)

        paper = resolver.get_paper_by_doi("10.1000/test")
        self.assertIsNotNone(paper)
        if paper:
            self.assertEqual(paper.source, "unpaywall")
            self.assertEqual(paper.doi, "10.1000/test")
            self.assertEqual(paper.title, "OA Paper")
            self.assertEqual(paper.pdf_url, "https://example.org/paper.pdf")
            self.assertEqual(paper.authors, ["Alice Example"])
            self.assertEqual(paper.published_date, datetime(2024, 1, 15))


class TestUnpaywallSearchErrors(unittest.TestCase):
    """Failed requests must raise, not look like zero results (#5)."""

    def searcher_with(self, **reply):
        searcher = UnpaywallSearcher(email="me@example.org")
        searcher.resolver.session.get = Mock(**reply)
        return searcher

    @staticmethod
    def reply(status, headers=None):
        response = Mock(status_code=status)
        response.headers = headers or {}
        return response

    def test_rate_limit_raises_with_retry_after(self):
        searcher = self.searcher_with(return_value=self.reply(429, {"Retry-After": "60"}))
        with self.assertRaisesRegex(requests.HTTPError, r"Unpaywall returned HTTP 429 \(Retry-After: 60\)"):
            searcher.search("10.1000/test")

    def test_rejected_email_raises_without_leaking_it(self):
        searcher = self.searcher_with(return_value=self.reply(422))
        with self.assertRaisesRegex(requests.HTTPError, "rejected the configured email") as ctx:
            searcher.search("10.1000/test")
        self.assertNotIn("me@example.org", str(ctx.exception))

    def test_network_error_raises(self):
        searcher = self.searcher_with(side_effect=requests.ConnectionError("down"))
        with self.assertRaises(requests.ConnectionError):
            searcher.search("10.1000/test")

    def test_non_json_reply_raises(self):
        bad = self.reply(200, {"Content-Type": "text/html"})
        bad.json.side_effect = requests.JSONDecodeError("Expecting value", "", 0)
        searcher = self.searcher_with(return_value=bad)
        with self.assertRaisesRegex(ValueError, "Unpaywall returned a non-JSON reply"):
            searcher.search("10.1000/test")

    def test_unknown_doi_is_empty(self):
        searcher = self.searcher_with(return_value=self.reply(404))
        self.assertEqual(searcher.search("10.1000/test"), [])

    def test_failed_lookup_leaves_pdf_resolution_best_effort(self):
        resolver = UnpaywallResolver(email="me@example.org")
        resolver.session.get = Mock(side_effect=requests.ConnectionError("down"))
        self.assertIsNone(resolver.resolve_best_pdf_url("10.1000/test"))


if __name__ == "__main__":
    unittest.main()
