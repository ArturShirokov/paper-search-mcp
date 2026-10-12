import unittest
from unittest.mock import Mock, patch

import requests

from paper_search_mcp.academic_platforms.pubmed import PubMedSearcher


class TestPubMedSearcher(unittest.TestCase):
    def test_search(self):
        searcher = PubMedSearcher()
        papers = searcher.search("machine learning", max_results=10)
        print(f"Found {len(papers)} papers for query 'machine learning':")
        for i, paper in enumerate(papers, 1):
            print(f"{i}. {paper.title} (ID: {paper.paper_id})")
        self.assertEqual(len(papers), 10)
        self.assertTrue(papers[0].title)

    def test_pdf_unsupported(self):
        searcher = PubMedSearcher()
        with self.assertRaises(NotImplementedError):
            searcher.download_pdf("12345678", "./downloads")

    def test_read_paper_message(self):
        searcher = PubMedSearcher()
        message = searcher.read_paper("12345678")
        self.assertIn("PubMed papers cannot be read directly", message)


def _reply(status=200, content=b"", headers=None):
    response = Mock(status_code=status, content=content)
    response.headers = headers or {}
    return response


EMPTY_ESEARCH = (b"<eSearchResult><Count>0</Count><RetMax>0</RetMax><IdList/>"
                 b"<ErrorList><PhraseNotFound>zzqxqzv</PhraseNotFound></ErrorList></eSearchResult>")
ONE_ESEARCH = b"<eSearchResult><Count>1</Count><IdList><Id>1</Id></IdList></eSearchResult>"


class TestPubMedSearchErrors(unittest.TestCase):
    """Failed or unreadable searches must raise, not look like zero results (#5)."""

    def _search(self, *replies):
        with patch("paper_search_mcp.academic_platforms.pubmed.requests.get",
                   side_effect=list(replies)):
            return PubMedSearcher().search("test")

    def test_esearch_http_error_raises_with_retry_after(self):
        with self.assertRaisesRegex(requests.HTTPError, "PubMed returned HTTP 429 .Retry-After: 1"):
            self._search(_reply(429, b'{"error":"API rate limit exceeded"}', {"Retry-After": "1"}))

    def test_efetch_http_error_raises(self):
        with self.assertRaisesRegex(requests.HTTPError, "PubMed returned HTTP 502"):
            self._search(_reply(content=ONE_ESEARCH), _reply(502, b"<html>Bad Gateway</html>"))

    def test_network_error_raises(self):
        with self.assertRaises(requests.ConnectionError):
            self._search(requests.ConnectionError("down"))

    def test_esearch_error_element_raises(self):
        with self.assertRaisesRegex(RuntimeError, "PubMed.*Invalid db name"):
            self._search(_reply(content=b"<eSearchResult><ERROR>Invalid db name</ERROR></eSearchResult>"))

    def test_non_xml_body_raises(self):
        with self.assertRaisesRegex(ValueError, "PubMed returned a non-XML reply"):
            self._search(_reply(content=b"<html><body>oops"))

    def test_wrong_xml_root_raises(self):
        with self.assertRaisesRegex(ValueError, "PubMed returned an unexpected reply"):
            self._search(_reply(content=b"<html><body>maintenance</body></html>"))

    def test_efetch_error_reply_raises(self):
        with self.assertRaisesRegex(RuntimeError, "PubMed returned an error: busy"):
            self._search(_reply(content=ONE_ESEARCH),
                         _reply(content=b"<eFetchResult><ERROR>busy</ERROR></eFetchResult>"))

    def test_genuine_empty_is_empty(self):
        self.assertEqual(self._search(_reply(content=EMPTY_ESEARCH)), [])


if __name__ == "__main__":
    unittest.main()
