import unittest
import os
import requests
from unittest.mock import Mock
from paper_search_mcp.academic_platforms.medrxiv import MedRxivSearcher

def check_api_accessible():
    """检查 medRxiv API 是否可访问"""
    try:
        response = requests.get("https://api.medRxiv.org/details/medrxiv/0/1", timeout=5)
        return response.status_code == 200
    except:
        return False

class TestMedRxivSearchErrors(unittest.TestCase):
    """Failed requests must raise, not look like zero results (#5)."""

    def setUp(self):
        self.searcher = MedRxivSearcher()

    def test_http_error_raises_with_retry_after(self):
        self.searcher.session.get = Mock(
            return_value=Mock(status_code=429, headers={"Retry-After": "60"})
        )
        with self.assertRaisesRegex(requests.HTTPError, r"medRxiv returned HTTP 429 \(Retry-After: 60\)"):
            self.searcher.search("epidemiology")
        self.assertEqual(self.searcher.session.get.call_count, self.searcher.max_retries)

    def test_network_error_raises(self):
        self.searcher.session.get = Mock(side_effect=requests.ConnectionError("down"))
        with self.assertRaises(requests.ConnectionError):
            self.searcher.search("epidemiology")

    def test_non_json_reply_raises(self):
        bad = Mock(status_code=200, headers={"Content-Type": "text/html"})
        bad.json.side_effect = requests.JSONDecodeError("Expecting value", "", 0)
        self.searcher.session.get = Mock(return_value=bad)
        with self.assertRaisesRegex(ValueError, "medRxiv returned a non-JSON reply"):
            self.searcher.search("epidemiology")

    def test_genuine_empty_result_is_empty(self):
        ok = Mock(status_code=200, headers={})
        ok.json.return_value = {"collection": []}
        self.searcher.session.get = Mock(return_value=ok)
        self.assertEqual(self.searcher.search("epidemiology"), [])


class TestMedRxivQueryModes(unittest.TestCase):
    """Free text must not be sent as a category (#7)."""

    def setUp(self):
        self.searcher = MedRxivSearcher()
        ok = Mock(status_code=200, headers={})
        ok.json.return_value = {"collection": [{
            "doi": "10.1101/2024.01.01.24300001", "title": "T", "authors": "A; B",
            "abstract": "", "date": "2024-01-01", "version": "2",
            "category": "cardiovascular medicine",
        }]}
        self.searcher.session.get = Mock(return_value=ok)

    def test_unknown_category_raises_naming_valid_ones(self):
        with self.assertRaisesRegex(ValueError, "not a medRxiv category.*cardiovascular medicine"):
            self.searcher.search("machine learning")
        self.searcher.session.get.assert_not_called()

    def test_known_category_filters_medrxiv(self):
        papers = self.searcher.search("Cardiovascular Medicine", max_results=1)
        url = self.searcher.session.get.call_args.args[0]
        self.assertIn("/details/medrxiv/", url)
        self.assertIn("?category=cardiovascular_medicine", url)
        self.assertEqual(papers[0].source, "medrxiv")
        self.assertEqual(papers[0].url, "https://www.medrxiv.org/content/10.1101/2024.01.01.24300001v2")

    def test_doi_lookup(self):
        self.searcher.search("10.1101/2024.01.01.24300001")
        self.assertEqual(
            self.searcher.session.get.call_args.args[0],
            "https://api.biorxiv.org/details/medrxiv/10.1101/2024.01.01.24300001/na/json",
        )

    def test_slash_in_category_name(self):
        self.searcher.search("HIV/AIDS", max_results=1)
        self.assertIn("?category=hiv_aids", self.searcher.session.get.call_args.args[0])


class TestMedRxivSearcher(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api_accessible = check_api_accessible()
        if not cls.api_accessible:
            print("\nWarning: medRxiv API is not accessible, some tests will be skipped")

    def setUp(self):
        self.searcher = MedRxivSearcher()

    def test_search(self):
        if not self.api_accessible:
            self.skipTest("medRxiv API is not accessible")
        
        papers = self.searcher.search("health informatics", max_results=10)
        print(f"Found {len(papers)} papers for query 'health informatics':")
        for i, paper in enumerate(papers, 1):
            print(f"{i}. {paper.title} (ID: {paper.paper_id})")
        self.assertTrue(len(papers) > 0)
        self.assertTrue(papers[0].title)

    def test_download_and_read(self):
        if not self.api_accessible:
            self.skipTest("medRxiv API is not accessible")
            
        papers = self.searcher.search("health informatics", max_results=1)
        if not papers:
            self.skipTest("No papers found for testing download")
            
        save_path = "./downloads"
        os.makedirs(save_path, exist_ok=True)
        paper = papers[0]
        pdf_path = None
        
        try:
            pdf_path = self.searcher.download_pdf(paper.paper_id, save_path)
            self.assertTrue(os.path.exists(pdf_path))
            
            text_content = self.searcher.read_paper(paper.paper_id, save_path)
            self.assertTrue(len(text_content) > 0)
        finally:
            if pdf_path and os.path.exists(pdf_path):
                os.remove(pdf_path)
            if os.path.exists(save_path):
                os.rmdir(save_path)

if __name__ == '__main__':
    unittest.main()