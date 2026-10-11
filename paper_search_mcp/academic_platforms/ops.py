"""Open Preprint Systems (OPS/OJS) connector: Jxiv and SciELO Preprints.

OPS servers have no search API, so keyword search scrapes preprint ids from
the site search page and fetches each record over OAI-PMH. Date harvesting
uses OAI-PMH ListRecords directly.
"""

from __future__ import annotations

import html
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import List, Optional

from ..paper import Paper
from .oaipmh import DC_NS, OAI_NS, OAIPMHSearcher

_RESULT_RE = re.compile(r'id="preprint-(\d+)"')


class OPSSearcher(OAIPMHSearcher):
    """One OPS server; subclasses set the three class attributes."""

    SOURCE = ""
    SITE_URL = ""  # https://<host>/index.php/<server path>
    OAI_REPO_ID = ""  # from Identify; GetRecord ids are oai:<repo id>:preprint/<n>

    def __init__(self) -> None:
        super().__init__(base_url=f"{self.SITE_URL}/oai")

    def search(self, query: str, max_results: int = 10, **kwargs) -> List[Paper]:
        """Keyword search via the site search page; full records via OAI-PMH."""
        ids: List[str] = []
        page = 1
        while len(ids) < max_results:
            response = self.session.get(
                f"{self.SITE_URL}/search/search",
                params={"query": query, "searchPage": page},
                timeout=30,
            )
            response.raise_for_status()
            # Real result pages, even with zero hits, carry this list; a 200
            # maintenance or redesigned page must not pass as "no results".
            if 'class="search_results"' not in response.text:
                raise ValueError(f"{self.SOURCE} search page has no result list")
            new_ids = [i for i in dict.fromkeys(_RESULT_RE.findall(response.text)) if i not in ids]
            if not new_ids:
                break
            ids += new_ids
            page += 1
        # ponytail: one GetRecord per hit, sequential; thread it if search latency matters.
        papers = [self._get_record(i) for i in ids[:max_results]]
        return [p for p in papers if p is not None]

    def list_new(self, since: str, max_results: int = 100, **kwargs) -> List[Paper]:
        """List records added or updated since a date (YYYY-MM-DD) via OAI-PMH."""
        datetime.strptime(since, "%Y-%m-%d")  # ValueError; "" would harvest everything
        return super().search("", max_results=max_results, from_date=since, **kwargs)

    def download_pdf(self, paper_id: str, save_path: str = "./downloads") -> str:
        pid = paper_id.rstrip("/").rsplit("/", 1)[-1]
        paper = self._get_record(pid)
        if paper is None or not paper.pdf_url:
            raise ValueError(f"{self.SOURCE} has no PDF for preprint {pid}")
        response = self.session.get(paper.pdf_url, timeout=60)
        response.raise_for_status()
        if not response.content.startswith(b"%PDF"):
            raise ValueError(f"{self.SOURCE} returned no PDF for preprint {pid}")
        os.makedirs(save_path, exist_ok=True)
        output_file = os.path.join(save_path, f"{self.SOURCE}_{pid}.pdf")
        with open(output_file, "wb") as f:
            f.write(response.content)
        return output_file

    def _get_record(self, pid: str) -> Optional[Paper]:
        root = self._oai_request({
            "verb": "GetRecord",
            "metadataPrefix": self.metadata_prefix,
            "identifier": f"oai:{self.OAI_REPO_ID}:preprint/{pid}",
        })
        record = root.find(f".//{{{OAI_NS}}}record")
        return self._parse_oai_record(record) if record is not None else None

    def _parse_oai_record(self, record: ET.Element) -> Optional[Paper]:
        paper = super()._parse_oai_record(record)
        if paper is None:
            return None
        identifiers = [e.text.strip() for e in record.iter(f"{{{DC_NS}}}identifier") if e.text]
        view_prefix = f"{self.SITE_URL}/preprint/view/"
        paper.url = next((i for i in identifiers if i.startswith(view_prefix)), "")
        if not paper.url:
            return None
        paper.paper_id = paper.url[len(view_prefix):]
        # OPS lists the DOI bare (10.x/...); don't fall back to DOIs cited in the abstract.
        paper.doi = next((i for i in identifiers if i.startswith("10.")), "")
        # OPS stores these as HTML, so OAI-PMH double-escapes entities (&amp;lt;).
        paper.title = html.unescape(paper.title).strip()
        paper.abstract = html.unescape(paper.abstract).strip()
        paper.source = self.SOURCE
        # The galley link ends in <id>/<galley>; its path prefix is unreliable
        # (Jxiv emits a dead article/view/...), so rebuild the download URL.
        galley = (record.findtext(f".//{{{DC_NS}}}relation") or "").strip().split("/")[-2:]
        paper.pdf_url = (
            f"{self.SITE_URL}/preprint/download/{galley[0]}/{galley[1]}"
            if len(galley) == 2 and galley[0] == paper.paper_id else ""
        )
        datestamp = record.findtext(f"{{{OAI_NS}}}header/{{{OAI_NS}}}datestamp") or ""
        try:
            paper.updated_date = datetime.strptime(datestamp[:19], "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            pass
        return paper


class JxivSearcher(OPSSearcher):
    """Jxiv, the JST preprint server (Japan)."""

    SOURCE = "jxiv"
    SITE_URL = "https://jxiv.jst.go.jp/index.php/jxiv"
    OAI_REPO_ID = "ops.160.74.73.116"


class SciELOPreprintsSearcher(OPSSearcher):
    """SciELO Preprints (Latin America)."""

    SOURCE = "scielo_preprints"
    SITE_URL = "https://preprints.scielo.org/index.php/scielo"
    OAI_REPO_ID = "ops.preprints.scielo.org"
