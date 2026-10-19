import pytest

from paper_search_mcp.academic_platforms.ru_stems import matches_stems, query_stems
from paper_search_mcp.paper import Paper


def _matches(query, text):
    paper = Paper(paper_id="1", title=text, authors=[], abstract="", doi="",
                  published_date=None, pdf_url="", url="", source="test")
    return matches_stems(paper, query_stems(query))


@pytest.mark.parametrize("query,text", [
    ("лёд", "запасы льда"),
    ("лёд", "лёд на полюсах"),
    ("сон", "фазы сна"),
    ("сон", "во сне"),
    ("отец", "роль отца"),
    ("отец", "с отцом"),
])
def test_fleeting_vowel_inflections_match(query, text):
    assert _matches(query, text)


@pytest.mark.parametrize("query,text", [
    ("лёд", "лодка"),
    ("сон", "снег"),
    ("сон", "сено"),
])
def test_fleeting_vowel_does_not_match_unrelated_words(query, text):
    assert not _matches(query, text)
