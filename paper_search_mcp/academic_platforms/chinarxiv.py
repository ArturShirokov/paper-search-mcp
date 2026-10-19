"""ChinaRxiv connector for paper-search-mcp.

ChinaRxiv publishes English machine translations of ChinaXiv preprints (the
Chinese Academy of Sciences preprint server). The same public API also serves
SovietRxiv, translated Soviet-era Russian papers (corpus ``russiarxiv``).
Translations trail ChinaXiv by a few weeks, and ``from_date`` filters by the
original publication date, so date harvests should look back about a month.

API docs: https://chinarxiv.org/api/docs (CC BY 4.0, no key required)
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

from ..config import get_env
from ..paper import Paper
from ..utils import extract_doi
from .base import PaperSource, check_response

BASE_URL = "https://chinarxiv.org"
API_URL = f"{BASE_URL}/api/v1/papers"

# Some records carry the journal's header line as the title: a bare DOI,
# "CN 53-1189/P ISSN 1672-7673", or "Journal, 2025, 66(1): 4".
_HEADER_TITLE = re.compile(
    r"\s*(?:(?:doi:?\s*)?10\.\d{4,9}/\S+|(?:(?:CN|ISSN)\s*\d[\dX/A-Z-]*[\s,;]*)+)\s*"
    r"|.*\b(?:19|20)\d{2}\s*,\s*(?:Vol\.?\s*)?\d+\s*\(\s*\d+\s*\).*",
    re.IGNORECASE,
)


class ChinaRxivSearcher(PaperSource):
    """Search translated ChinaXiv (and SovietRxiv) papers."""

    USER_AGENT = "paper-search-mcp (https://github.com/openags/paper-search-mcp)"
    MAX_PAGE_SIZE = 100

    def __init__(self, email: Optional[str] = None) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.USER_AGENT, "Accept": "application/json"})
        email = get_env("CHINARXIV_EMAIL", "") if email is None else email
        if email:
            # Polite pool: 300 requests/minute instead of 30.
            self.session.headers["X-API-Email"] = email

    def search(self, query: str, max_results: int = 10, corpus: str = "chinaxiv", **kwargs) -> List[Paper]:
        """Search English translations. ``corpus`` is ``chinaxiv`` or ``russiarxiv``."""
        params: Dict[str, Any] = {"q": query} if query else {}
        if kwargs.get("from_date"):
            params["from_date"] = kwargs["from_date"]
        params["source"] = corpus

        papers: List[Paper] = []
        cursor = None
        while len(papers) < max_results:
            page = dict(params, limit=min(max_results - len(papers), self.MAX_PAGE_SIZE))
            if cursor:
                page["cursor"] = cursor
            data = self._get(API_URL, params=page, timeout=30).json()
            papers.extend(self._parse(r) for r in data.get("data") or [] if r.get("id"))
            cursor = data.get("next_cursor")
            if not cursor or not data.get("data"):
                break
        return papers[:max_results]

    def list_new(self, since: str, max_results: int = 100, corpus: str = "chinaxiv") -> List[Paper]:
        """List papers published since a date (YYYY-MM-DD)."""
        return self.search("", max_results=max_results, corpus=corpus, from_date=since)

    def download_pdf(self, paper_id: str, save_path: str = "./downloads") -> str:
        """Download the English PDF."""
        response = self._get(f"{API_URL}/{paper_id}/pdf", timeout=60)
        if not response.content.startswith(b"%PDF"):
            raise ValueError(f"ChinaRxiv returned no PDF for {paper_id}")
        os.makedirs(save_path, exist_ok=True)
        output_file = os.path.join(save_path, f"chinarxiv_{paper_id.replace('/', '_')}.pdf")
        with open(output_file, "wb") as f:
            f.write(response.content)
        return output_file

    def read_paper(self, paper_id: str, save_path: str = "./downloads") -> str:
        """Return the translated full text as Markdown (no PDF parsing)."""
        text = self._get(f"{API_URL}/{paper_id}/text", timeout=60).json().get("body_md")
        if not text:
            raise ValueError(f"ChinaRxiv has no full text for {paper_id}; try download_chinarxiv")
        return text

    def _get(self, url: str, **kwargs) -> requests.Response:
        response = self.session.get(url, **kwargs)
        if response.status_code == 422:
            # The body names the bad parameter; raise_for_status would drop it.
            raise ValueError(f"ChinaRxiv rejected the request: {response.text[:300]}")
        if response.status_code == 404:
            # The detail tells "PDF not available for paper" from "Paper not found".
            try:
                detail = response.json().get("detail")
            except (ValueError, AttributeError):
                detail = None
            raise ValueError(f"ChinaRxiv: {detail or f'nothing at {url}'}")
        check_response(response, "ChinaRxiv")
        return response

    def _parse(self, record: Dict[str, Any]) -> Paper:
        paper_id = record["id"]
        authors = [a for a in record.get("authors") or [] if a]
        if len(authors) == 1:
            # A single entry is a comma-joined list ("A, B, and C et al.");
            # several entries are one person each, sometimes "Surname, Given".
            # ponytail: a lone "Surname, Given" author still splits in two.
            joined = re.sub(r"\s+et al\.?$", "", authors[0])
            authors = [re.sub(r"^and ", "", a.strip()) for a in joined.split(",") if a.strip()]
        date = record.get("date") or ""
        try:
            published = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            published = None
        title = (record.get("title") or "").strip()
        doi = ""
        extra: Dict[str, Any] = {}
        if title and _HEADER_TITLE.fullmatch(title):
            # The API record holds no other title field, so flag it instead.
            doi = extract_doi(title)
            title = ""
            extra["title_unreliable"] = True
        return Paper(
            paper_id=paper_id,
            title=title,
            authors=authors,
            abstract=record.get("abstract") or "",
            doi=doi,
            published_date=published,
            pdf_url=f"{API_URL}/{paper_id}/pdf" if record.get("has_pdf") else "",
            url=f"{BASE_URL}/items/{paper_id}",
            source="chinarxiv",
            categories=record.get("subjects") or [],
            extra={
                "original_url": record.get("source_url") or "",
                "corpus": record.get("source") or "",
                "source_language": record.get("source_language") or "",
                # "machine_generated" means a model wrote the abstract, not the authors.
                "abstract_source": record.get("abstract_source") or "",
                **extra,
            },
        )
