"""Explain empty results from sources that require every query word."""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional

# Sources whose keyword search ANDs every query word.
STRICT_AND_SOURCES = ("arxiv", "chinarxiv", "preprints_ru", "cyberleninka")

_SYNTAX_WORDS = {"AND", "OR", "ANDNOT", "NOT"}


def shorter_query(query: str) -> Optional[str]:
    """Drop the last word of a 3+ word plain query; None for anything else."""
    words = (query or "").split()
    if len(words) < 3 or '"' in query or ":" in query or _SYNTAX_WORDS & set(words):
        return None
    return " ".join(words[:-1])


async def strict_and_notes(
    query: str,
    source_counts: Dict[str, int],
    errors: Dict[str, str],
    retry: Callable[[str, str], Awaitable[List[Dict[str, Any]]]],
) -> Dict[str, str]:
    """Retry each empty strict-AND source once with a shorter query and say what it found.

    The retry results are never returned; they only decide the note's wording.
    """
    shorter = shorter_query(query)
    if shorter is None:
        return {}
    empty = [s for s in STRICT_AND_SOURCES if source_counts.get(s) == 0 and s not in errors]
    if not empty:
        return {}
    retried = await asyncio.gather(*(retry(s, shorter) for s in empty), return_exceptions=True)
    notes: Dict[str, str] = {}
    for source, output in zip(empty, retried):
        if isinstance(output, list) and output:
            notes[source] = (
                f"No result matched every word of '{query}' (this source requires all of them). "
                f"The shorter query '{shorter}' does match."
            )
        elif isinstance(output, BaseException):
            # The retry failed, so we don't know whether fewer words would help.
            notes[source] = (
                f"No result matched every word of '{query}'; this source requires every query word."
            )
        else:
            notes[source] = (
                f"No result matched every word of '{query}'; this source requires every query word. "
                "Try 2-3 words."
            )
    return notes
