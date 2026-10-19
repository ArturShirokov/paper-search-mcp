import pytest

from paper_search_mcp.academic_platforms.arxiv import ArxivSearcher


@pytest.fixture(autouse=True)
def _arxiv_rate_file_in_tmp(tmp_path, monkeypatch):
    """Keep arXiv's cross-process rate stamp out of the user's real cache."""
    monkeypatch.setattr(ArxivSearcher, "RATE_FILE", tmp_path / "arxiv-rate")
    # CLI subprocesses compute RATE_FILE from XDG_CACHE_HOME at import.
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
