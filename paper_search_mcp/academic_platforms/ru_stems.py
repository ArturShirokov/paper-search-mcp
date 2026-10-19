"""Word-stem filter for sites whose own search matches any query word.

Keeps a hit only if its title or abstract has every query word, matched as
a word-start prefix so Russian inflections ("лёд", "льда") still count.
"""

from __future__ import annotations

import re
from typing import List

from ..paper import Paper

# One inflectional ending plus trailing vowels; what's left is matched as a
# word prefix, so "распознавание" and "распознавания" both give "распознаван".
_ENDING_RE = re.compile(
    r"(?:ами|ями|ого|его|ому|ему|ыми|ими|ов|ев|ам|ям|ах|ях|ом|ем|ой|ей|ый|ий|ых|их|ым|им|ую|юю|ть)?[аеиоуыэюяьй]*$"
)
# A stem ending in е/о plus one consonant may lose that vowel when inflected
# (лёд/льда, сон/сна, отец/отца).
_FLEETING_RE = re.compile(r"^(.+)[ео]([бвгджзклмнпрстфхцчшщ])$")


def fold(text: str) -> str:
    return text.lower().replace("ё", "е")


def query_stems(query: str) -> List[str]:
    """Lowercased word stems of a query; Cyrillic words lose their ending."""
    stems = []
    for word in re.findall(r"\w+", fold(query)):
        stem = _ENDING_RE.sub("", word) if re.search("[а-я]", word) else word
        # ponytail: crude stemmer, swap in Snowball if recall complaints come in.
        stems.append(stem if len(stem) >= 3 else word[:3])
    return stems


def _stem_pattern(stem: str) -> str:
    fleeting = _FLEETING_RE.match(stem)
    if fleeting:
        return re.escape(fleeting.group(1)) + "[еоь]?" + fleeting.group(2)
    return re.escape(stem)


def matches_stems(paper: Paper, stems: List[str]) -> bool:
    text = fold(f"{paper.title} {paper.abstract}")
    return all(re.search(r"\b" + _stem_pattern(stem), text) for stem in stems)
