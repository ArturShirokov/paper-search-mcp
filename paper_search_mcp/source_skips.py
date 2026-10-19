"""Sources the unified "all" search skips, shared by the MCP server and the CLI.

Naming a source explicitly always runs it, so its real error still surfaces.
"""

from __future__ import annotations

from .academic_platforms.biorxiv import BioRxivSearcher
from .academic_platforms.medrxiv import MedRxivSearcher

# Sources that can't answer at all right now: {name: reason}.
SKIP_UNDER_ALL: dict[str, str] = {
    "dblp": "dblp API is behind a bot wall (Anubis proof-of-work page); name dblp explicitly to try it",
    "citeseerx": "CiteSeerX service is retired (redirects to the Wayback Machine); name citeseerx explicitly to try it",
    "base": "BASE API needs IP registration with Bielefeld University Library; name base explicitly to try it",
}

# Sources that can't answer some queries: {name: searcher with skip_reason(query)}.
_QUERY_SKIPS = {"biorxiv": BioRxivSearcher, "medrxiv": MedRxivSearcher}


def skipped_under_all(query: str, selected: list[str]) -> dict[str, str]:
    """Return {source: reason} for the selected sources "all" should skip."""
    skipped = {name: reason for name, reason in SKIP_UNDER_ALL.items() if name in selected}
    for name, searcher_cls in _QUERY_SKIPS.items():
        reason = searcher_cls.skip_reason(query)
        if reason and name in selected:
            skipped[name] = reason
    return skipped
