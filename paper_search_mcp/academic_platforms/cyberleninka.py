"""CyberLeninka connector for paper-search-mcp.

CyberLeninka is Russia's largest open-access archive of journal articles
(mostly Russian-language, also English and other CIS languages). It exposes
an undocumented JSON search API used by its own site, and a standard OAI-PMH
endpoint for harvesting records added since a date.

OAI-PMH: https://cyberleninka.ru/oai?verb=Identify
"""

from __future__ import annotations

import html
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import List, Optional

from ..paper import Paper
from .oaipmh import OAI_NS, OAIPMHSearcher

BASE_URL = "https://cyberleninka.ru"
ARTICLE_PREFIX = f"{BASE_URL}/article/n/"

_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text: Optional[str]) -> str:
    """Strip the search API's <b> highlight tags and HTML entities."""
    return html.unescape(_TAG_RE.sub("", text or "")).strip()


def _slug(paper_id_or_url: str) -> str:
    return paper_id_or_url.rstrip("/").rsplit("/", 1)[-1]


class CyberLeninkaSearcher(OAIPMHSearcher):
    """Keyword search via the site API; date harvesting via OAI-PMH."""

    SEARCH_URL = f"{BASE_URL}/api/search"
    # ponytail: one request, the API's page size; page with "from" if feeds need more.
    MAX_PAGE_SIZE = 100

    def __init__(self) -> None:
        super().__init__(base_url=f"{BASE_URL}/oai")

    def search(self, query: str, max_results: int = 10, **kwargs) -> List[Paper]:
        """Search CyberLeninka articles. Russian queries match far more records."""
        size = max(1, min(max_results, self.MAX_PAGE_SIZE))
        response = self.session.post(
            self.SEARCH_URL,
            json={"mode": "articles", "q": query, "size": size, "from": 0},
            headers={"Accept": "application/json"},
            timeout=20,
        )
        response.raise_for_status()
        articles = response.json().get("articles") or []
        return [self._parse_article(a) for a in articles if a.get("link")][:max_results]

    def list_new(self, since: str, max_results: int = 100, **kwargs) -> List[Paper]:
        """List records added since a date (YYYY-MM-DD) via OAI-PMH.

        Pass ``set="scopus"`` or ``set="wos"`` to keep only journals indexed there.
        """
        return super().search("", max_results=max_results, from_date=since, **kwargs)

    def download_pdf(self, paper_id: str, save_path: str = "./downloads") -> str:
        slug = _slug(paper_id)
        response = self.session.get(f"{ARTICLE_PREFIX}{slug}/pdf", timeout=30)
        response.raise_for_status()
        if not response.content.startswith(b"%PDF"):
            raise ValueError(f"CyberLeninka returned no PDF for {slug}")
        os.makedirs(save_path, exist_ok=True)
        output_file = os.path.join(save_path, f"cyberleninka_{slug}.pdf")
        with open(output_file, "wb") as f:
            f.write(response.content)
        return output_file

    def _parse_article(self, article: dict) -> Paper:
        url = BASE_URL + article["link"].rstrip("/")
        year = str(article.get("year") or "")
        return Paper(
            paper_id=_slug(url),
            title=_clean(article.get("name")),
            authors=[a for a in article.get("authors") or [] if a],
            abstract=_clean(article.get("annotation")),
            doi="",
            published_date=datetime(int(year), 1, 1) if year.isdigit() else None,
            pdf_url=f"{url}/pdf",
            url=url,
            source="cyberleninka",
            extra={"journal": article.get("journal") or ""},
        )

    def _parse_oai_record(self, record: ET.Element) -> Optional[Paper]:
        paper = super()._parse_oai_record(record)
        if paper is None or not paper.url.startswith(ARTICLE_PREFIX):
            return None
        paper.url = paper.url.rstrip("/")
        paper.paper_id = _slug(paper.url)
        paper.pdf_url = f"{paper.url}/pdf"
        # Records carry no dc:date; the datestamp is when CyberLeninka added it.
        datestamp = record.findtext(f"{{{OAI_NS}}}header/{{{OAI_NS}}}datestamp") or ""
        try:
            paper.updated_date = datetime.strptime(datestamp[:19], "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            pass  # Keep the record; only the added-date is unknown.
        return paper
