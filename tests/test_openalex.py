import asyncio
import io
import os
import tempfile
import unittest

import requests
from unittest.mock import AsyncMock, Mock, patch
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from paper_search_mcp import server
from paper_search_mcp.academic_platforms.openalex import OpenAlexSearcher


class TestOpenAlexSearcher(unittest.TestCase):
    def setUp(self):
        self.searcher = OpenAlexSearcher(api_key="")

    @staticmethod
    def _response(results=None, status_code=200):
        response = Mock(status_code=status_code)
        response.json.return_value = {"results": results or []}
        return response

    def test_api_key_from_env_uses_authorization_header(self):
        with patch.dict(
            os.environ,
            {
                "PAPER_SEARCH_MCP_ENV_FILE": "/missing/paper-search-mcp.env",
                "PAPER_SEARCH_MCP_OPENALEX_API_KEY": " test-openalex-key ",
            },
            clear=True,
        ):
            searcher = OpenAlexSearcher()

        self.assertEqual(searcher.api_key, "test-openalex-key")
        self.assertEqual(
            searcher.session.headers.get("Authorization"),
            "Bearer test-openalex-key",
        )

        searcher.session.get = Mock(return_value=self._response())
        searcher.search("graph neural networks", max_results=7)
        params = searcher.session.get.call_args.kwargs["params"]
        self.assertNotIn("api_key", params)
        self.assertEqual(params["per_page"], 7)

    def test_explicit_api_key_overrides_environment(self):
        with patch.dict(
            os.environ,
            {"PAPER_SEARCH_MCP_OPENALEX_API_KEY": "environment-key"},
            clear=True,
        ):
            searcher = OpenAlexSearcher(api_key=" explicit-key ")

        self.assertEqual(searcher.api_key, "explicit-key")
        self.assertEqual(
            searcher.session.headers.get("Authorization"),
            "Bearer explicit-key",
        )

    def test_empty_api_key_omits_authorization(self):
        searcher = OpenAlexSearcher(api_key="")

        self.assertNotIn("Authorization", searcher.session.headers)

    def test_email_customizes_user_agent(self):
        searcher = OpenAlexSearcher(api_key="", email=" researcher@example.com ")

        self.assertEqual(searcher.email, "researcher@example.com")
        self.assertIn(
            "mailto:researcher@example.com",
            searcher.session.headers["User-Agent"],
        )

    def test_search_passes_filter_and_uses_supported_page_limit(self):
        response = self._response()
        self.searcher.session.get = Mock(return_value=response)

        papers = self.searcher.search(
            "artificial intelligence",
            max_results=250,
            filter=" publication_year:2024,open_access.is_oa:true ",
        )

        self.assertEqual(papers, [])
        self.searcher.session.get.assert_called_once_with(
            self.searcher.BASE_URL,
            params={
                "search": "artificial intelligence",
                "per_page": 100,
                "filter": "publication_year:2024,open_access.is_oa:true",
            },
            timeout=30,
        )

    def test_search_omits_empty_filter(self):
        response = self._response()
        self.searcher.session.get = Mock(return_value=response)

        self.searcher.search("machine learning", max_results=5, filter="  ")

        request_params = self.searcher.session.get.call_args.kwargs["params"]
        self.assertEqual(
            request_params,
            {"search": "machine learning", "per_page": 5},
        )

    def test_search_parses_filtered_result(self):
        response = self._response(
            [
                {
                    "id": "https://openalex.org/W123",
                    "title": "A filtered paper",
                    "authorships": [
                        {"author": {"display_name": "Ada Lovelace"}}
                    ],
                    "abstract_inverted_index": {
                        "Filtered": [0],
                        "abstract": [1],
                    },
                    "doi": "https://doi.org/10.1000/example",
                    "primary_location": {
                        "landing_page_url": "https://example.org/paper",
                        "pdf_url": "https://example.org/paper.pdf",
                    },
                    "open_access": {"is_oa": True},
                    "publication_date": "2024-02-03",
                    "concepts": [{"display_name": "Computer science"}],
                    "cited_by_count": 7,
                }
            ]
        )
        self.searcher.session.get = Mock(return_value=response)

        papers = self.searcher.search(
            "filtered",
            filter="publication_year:2024",
        )

        self.assertEqual(len(papers), 1)
        paper = papers[0]
        self.assertEqual(paper.paper_id, "W123")
        self.assertEqual(paper.title, "A filtered paper")
        self.assertEqual(paper.authors, ["Ada Lovelace"])
        self.assertEqual(paper.abstract, "Filtered abstract")
        self.assertEqual(paper.doi, "10.1000/example")
        self.assertEqual(paper.published_date.year, 2024)
        self.assertEqual(paper.citations, 7)

    def test_non_success_response_raises(self):
        response = self._response(status_code=429)
        response.headers = {}
        self.searcher.session.get = Mock(return_value=response)

        with self.assertRaises(requests.HTTPError):
            self.searcher.search("machine learning", filter="publication_year:2024")

    def test_user_agent_header(self):
        user_agent = self.searcher.session.headers.get("User-Agent", "")
        self.assertIn("paper-search-mcp", user_agent)
        self.assertIn("mailto:", user_agent)


# Trimmed from api.openalex.org/works/W7213893935 as fetched on 2026-10-19.
TITLE = "A comprehensive review of machine learning and deep learning approaches for fungal classification in plants"
PDF_URL = "https://horizonepublishing.com/journals/index.php/PST/article/download/11225/16175"
WORK = {
    "id": "https://openalex.org/W7213893935",
    "doi": "https://doi.org/10.14719/pst.11225",
    "display_name": TITLE,
    "best_oa_location": {
        "is_oa": True,
        "landing_page_url": "https://doi.org/10.14719/pst.11225",
        "pdf_url": PDF_URL,
    },
    "locations": [
        {"is_oa": True, "landing_page_url": "https://doi.org/10.14719/pst.11225", "pdf_url": PDF_URL},
        {"is_oa": True, "landing_page_url": "https://horizonepublishing.com/journals/index.php/PST/article/view/11225", "pdf_url": None},
    ],
}


def _pdf(text):
    writer = PdfWriter()
    page = writer.add_blank_page(612, 792)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 8 Tf 20 700 Td ({text}) Tj ET".encode())
    page[NameObject("/Contents")] = writer._add_object(stream)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _reply(json_data=None, body=b"", status=200):
    response = Mock(status_code=status, headers={})
    response.json.return_value = json_data
    response.iter_content.return_value = iter([body])
    return response


class TestOpenAlexDownload(unittest.TestCase):
    def setUp(self):
        self.searcher = OpenAlexSearcher(api_key="secret-key")
        self.tmp = tempfile.mkdtemp()

    def _serve(self, work=WORK, pdf_body=None):
        def get(url, **kwargs):
            if url.startswith(OpenAlexSearcher.BASE_URL):
                return _reply(work)
            return _reply(body=_pdf(TITLE) if pdf_body is None else pdf_body)
        self.searcher.session.get = Mock(side_effect=get)

    def test_download_by_work_id_saves_best_oa_pdf(self):
        self._serve()
        path = self.searcher.download_pdf("W7213893935", self.tmp)
        self.assertEqual(os.path.basename(path), "openalex_W7213893935.pdf")
        with open(path, "rb") as f:
            self.assertTrue(f.read().startswith(b"%PDF-"))
        lookup, pdf = self.searcher.session.get.call_args_list
        self.assertEqual(lookup.args[0], OpenAlexSearcher.BASE_URL + "/W7213893935")
        self.assertEqual(pdf.args[0], PDF_URL)
        # The OpenAlex API key must not go to the publisher's host.
        self.assertIsNone(pdf.kwargs["headers"]["Authorization"])

    def test_download_accepts_doi(self):
        self._serve()
        path = self.searcher.download_pdf("https://doi.org/10.14719/PST.11225", self.tmp)
        self.assertEqual(os.path.basename(path), "openalex_W7213893935.pdf")
        lookup = self.searcher.session.get.call_args_list[0]
        self.assertEqual(lookup.args[0], OpenAlexSearcher.BASE_URL + "/doi:10.14719/pst.11225")

    def test_html_reply_is_rejected_and_next_location_tried(self):
        mirror = "https://mirror.example.org/paper.pdf"
        work = {**WORK, "locations": WORK["locations"] + [{"pdf_url": mirror}]}
        html = b"<!doctype html><html><body>Article landing page</body></html>"

        def get(url, **kwargs):
            if url.startswith(OpenAlexSearcher.BASE_URL):
                return _reply(work)
            return _reply(body=html if url == PDF_URL else _pdf(TITLE))
        self.searcher.session.get = Mock(side_effect=get)

        path = self.searcher.download_pdf("W7213893935", self.tmp)
        with open(path, "rb") as f:
            self.assertTrue(f.read().startswith(b"%PDF-"))
        self.assertEqual(self.searcher.session.get.call_args_list[-1].args[0], mirror)

    def test_html_only_raises_and_saves_nothing(self):
        self._serve(pdf_body=b"<html><body>Please log in</body></html>")
        with self.assertRaisesRegex(ValueError, "W7213893935.*not a complete PDF"):
            self.searcher.download_pdf("W7213893935", self.tmp)
        self.assertEqual(os.listdir(self.tmp), [])

    def test_pdf_without_the_title_on_page_one_is_still_saved(self):
        # Scanned or translated OA PDFs don't carry the OpenAlex title as text.
        self._serve(pdf_body=_pdf("Obzor metodov mashinnogo obucheniya"))
        path = self.searcher.download_pdf("W7213893935", self.tmp)
        self.assertEqual(os.path.basename(path), "openalex_W7213893935.pdf")

    def test_work_without_oa_pdf_raises_naming_the_work(self):
        work = {**WORK, "best_oa_location": None,
                "locations": [{"is_oa": False, "landing_page_url": "https://x.org", "pdf_url": None}]}
        self._serve(work=work)
        with self.assertRaisesRegex(ValueError, "W7213893935.*no open-access PDF"):
            self.searcher.download_pdf("W7213893935", self.tmp)
        self.assertEqual(len(self.searcher.session.get.call_args_list), 1)

    def test_read_paper_returns_pdf_text(self):
        self._serve()
        text = self.searcher.read_paper("W7213893935", self.tmp)
        self.assertIn("fungal classification in plants", text)

    def test_tools_route_to_searcher(self):
        self._serve()
        with patch.object(server, "openalex_searcher", self.searcher):
            path = asyncio.run(server.download_openalex("W7213893935", self.tmp))
            text = asyncio.run(server.read_openalex_paper("W7213893935", self.tmp))
        self.assertTrue(path.endswith("openalex_W7213893935.pdf"))
        self.assertIn("machine learning", text)


class TestSearchOpenAlexTool(unittest.TestCase):
    def test_tool_forwards_non_empty_filter(self):
        search = AsyncMock(return_value=[])
        with patch.object(server, "async_search", search):
            result = asyncio.run(
                server.search_openalex(
                    "machine learning",
                    max_results=3,
                    filter=" publication_year:2024 ",
                )
            )

        self.assertEqual(result, [])
        search.assert_awaited_once_with(
            server.openalex_searcher,
            "machine learning",
            3,
            filter="publication_year:2024",
        )

    def test_tool_omits_empty_filter(self):
        search = AsyncMock(return_value=[])
        with patch.object(server, "async_search", search):
            asyncio.run(server.search_openalex("machine learning", filter=""))

        search.assert_awaited_once_with(
            server.openalex_searcher,
            "machine learning",
            10,
        )


if __name__ == "__main__":
    unittest.main()
