"""Preprints.ru connector (Russian preprint server run by NEICON).

The site has no OAI-PMH feed and no data API; its search page is
server-rendered HTML. Search and "posted or revised since" both use that page for
article ids, then read each article page's Highwire citation_* tags.
Records are CC BY 4.0.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from ..paper import Paper
from .base import PaperSource

BASE_URL = "https://preprints.ru"

_FOUND_RE = re.compile(r"найдено:\s*(\d+)")
_ID_RE = re.compile(r'class="title">\s*<a href="https://preprints\.ru/article/(\d+)"')
_URL_ID_RE = re.compile(r"/article/(\d+)")


class PreprintsRuSearcher(PaperSource):
    SOURCE = "preprints_ru"

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "paper-search-mcp (https://github.com/openags/paper-search-mcp)",
        })

    def search(self, query: str, max_results: int = 10, **kwargs) -> List[Paper]:
        """Keyword search (Russian morphology, matches abstracts too)."""
        return self._get_articles(self._article_ids({"search_query": query}, max_results))

    def list_new(self, since: str, max_results: int = 100, **kwargs) -> List[Paper]:
        """List preprints posted or revised on or after a date (YYYY-MM-DD).

        The site's date filter, like citation_publication_date, is the date
        of the latest version, so a revised old preprint counts as new.
        """
        datetime.strptime(since, "%Y-%m-%d")  # ValueError; "" would list everything
        params = {"search_query": "", "filters[gte][]": since}
        return self._get_articles(self._article_ids(params, max_results))

    def download_pdf(self, paper_id: str, save_path: str = "./downloads") -> str:
        # Version URLs (/article/<id>/version/<n>) end in the version number.
        match = _URL_ID_RE.search(paper_id)
        aid = match.group(1) if match else paper_id.strip()
        paper = self._get_article(aid)
        if paper is None or not paper.pdf_url:
            raise ValueError(f"{self.SOURCE} has no PDF for article {aid}")
        response = self.session.get(paper.pdf_url, timeout=60)
        response.raise_for_status()
        if not response.content.startswith(b"%PDF"):
            raise ValueError(f"{self.SOURCE} returned no PDF for article {aid}")
        os.makedirs(save_path, exist_ok=True)
        output_file = os.path.join(save_path, f"{self.SOURCE}_{aid}.pdf")
        with open(output_file, "wb") as f:
            f.write(response.content)
        return output_file

    def read_paper(self, paper_id: str, save_path: str = "./downloads") -> str:
        from pypdf import PdfReader

        reader = PdfReader(self.download_pdf(paper_id, save_path))
        return "\n".join(page.extract_text() or "" for page in reader.pages).strip()

    def _article_ids(self, params: Dict[str, str], max_results: int) -> List[str]:
        ids: List[str] = []
        page = 1
        while len(ids) < max_results:
            response = self.session.get(
                f"{BASE_URL}/search", params={"page": page, **params}, timeout=30
            )
            response.raise_for_status()
            # Real result pages, even with zero hits, show the count; a 200
            # maintenance or redesigned page must not pass as "no results".
            found = _FOUND_RE.search(response.text)
            if not found:
                raise ValueError(f"{self.SOURCE} search page has no result count")
            new_ids = [i for i in dict.fromkeys(_ID_RE.findall(response.text)) if i not in ids]
            ids += new_ids
            # Stop on the count: a page past the end has no result list at all.
            if not new_ids or len(ids) >= int(found.group(1)):
                break
            page += 1
        return ids[:max_results]

    def _get_articles(self, ids: List[str]) -> List[Paper]:
        # ponytail: one article page per hit, sequential; thread it if latency matters.
        papers = [self._get_article(i) for i in ids]
        return [p for p in papers if p is not None]

    def _get_article(self, aid: str) -> Optional[Paper]:
        url = f"{BASE_URL}/article/{aid}"
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        def meta(name: str) -> List[str]:
            return [m.get("content", "").strip() for m in soup.find_all("meta", attrs={"name": name})]

        title = meta("citation_title")
        if not title:
            return None  # Removed articles redirect to the home page.
        date = (meta("citation_publication_date") or [""])[0]
        doi = soup.select_one("div.doi a")
        pdf = soup.select_one('div.file a[href*="/files/"]')
        abstract = soup.select_one("div.abstract")
        return Paper(
            paper_id=aid,
            title=title[0],
            authors=[a for a in meta("citation_author") if a],
            abstract=abstract.get_text().strip() if abstract else "",
            doi=doi.get_text().strip().removeprefix("https://doi.org/") if doi else "",
            published_date=datetime.strptime(date, "%Y/%m/%d") if date else None,
            pdf_url=pdf["href"] if pdf else "",
            url=url,
            source=self.SOURCE,
        )
