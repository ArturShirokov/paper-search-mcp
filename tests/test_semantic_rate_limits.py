"""Deterministic Semantic Scholar retry/fallback coverage adapted from PR #71."""

from unittest.mock import Mock

import pytest
import requests

from paper_search_mcp.academic_platforms import semantic


def response(status, headers=None):
    return Mock(status_code=status, headers=headers or {})


@pytest.fixture
def searcher(monkeypatch):
    instance = semantic.SemanticSearcher()
    monkeypatch.setattr(instance, "get_api_key", lambda: None)
    return instance


@pytest.mark.parametrize("exception_path", [False, True])
def test_anonymous_rate_limit_fails_fast(searcher, monkeypatch, exception_path):
    limited = response(429)
    if exception_path:
        upstream = response(200)
        upstream.raise_for_status.side_effect = requests.HTTPError(response=limited)
    else:
        upstream = limited
    get = Mock(return_value=upstream)
    sleep = Mock()
    monkeypatch.setattr(searcher.session, "get", get)
    monkeypatch.setattr(semantic.time, "sleep", sleep)
    result = searcher.request_api("paper/search", {"query": "test"})
    assert result["error"] == "rate_limited"
    assert result["status_code"] == 429
    get.assert_called_once()
    sleep.assert_not_called()


def test_authenticated_rate_limit_retries_with_retry_after(searcher, monkeypatch):
    monkeypatch.setattr(searcher, "get_api_key", lambda: "test-key")
    success = response(200)
    get = Mock(side_effect=[response(429, {"Retry-After": "4"}), success])
    sleep = Mock()
    monkeypatch.setattr(searcher.session, "get", get)
    monkeypatch.setattr(semantic.time, "sleep", sleep)
    assert searcher.request_api("paper/search", {}) is success
    assert get.call_count == 2
    assert all(call.kwargs["headers"] == {"x-api-key": "test-key"} for call in get.call_args_list)
    sleep.assert_called_once_with(4)


def test_authenticated_retries_are_bounded(searcher, monkeypatch):
    monkeypatch.setattr(searcher, "get_api_key", lambda: "test-key")
    get = Mock(return_value=response(429))
    sleep = Mock()
    monkeypatch.setattr(searcher.session, "get", get)
    monkeypatch.setattr(semantic.time, "sleep", sleep)
    assert searcher.request_api("paper/search", {})["error"] == "rate_limited"
    assert get.call_count == 3
    assert [call.args[0] for call in sleep.call_args_list] == [2, 4]


@pytest.mark.parametrize("fallback_status", [200, 429])
def test_rejected_key_falls_back_without_retrying_anonymous_429(searcher, monkeypatch, fallback_status):
    monkeypatch.setattr(searcher, "get_api_key", lambda: "rejected-key")
    fallback = response(fallback_status)
    get = Mock(side_effect=[response(403), fallback])
    sleep = Mock()
    monkeypatch.setattr(searcher.session, "get", get)
    monkeypatch.setattr(semantic.time, "sleep", sleep)
    result = searcher.request_api("paper/search", {})
    if fallback_status == 200:
        assert result is fallback
    else:
        assert result["error"] == "rate_limited"
    assert get.call_count == 2
    assert get.call_args_list[0].kwargs["headers"] == {"x-api-key": "rejected-key"}
    assert get.call_args_list[1].kwargs["headers"] == {}
    sleep.assert_not_called()


def test_rate_limit_error_carries_retry_after(searcher, monkeypatch):
    monkeypatch.setattr(searcher.session, "get", Mock(return_value=response(429, {"Retry-After": "30"})))
    with pytest.raises(semantic.SemanticScholarRequestError, match=r"Retry-After: 30"):
        searcher.search("test")


def test_search_surfaces_rate_limit_as_error(searcher, monkeypatch):
    monkeypatch.setattr(searcher.session, "get", Mock(return_value=response(429)))
    monkeypatch.setattr(semantic.time, "sleep", Mock(side_effect=AssertionError("Unexpected retry")))
    with pytest.raises(semantic.SemanticScholarRequestError, match="rate_limited, HTTP 429"):
        searcher.search("test")


# --- Failed or unreadable replies must raise, not look like zero results (#5) ---

def ok_reply(json_data=None, headers=None):
    reply = response(200, headers)
    if json_data is None:
        reply.json.side_effect = requests.JSONDecodeError("Expecting value", "", 0)
    else:
        reply.json.return_value = json_data
    return reply


def test_search_non_json_reply_raises(searcher, monkeypatch):
    monkeypatch.setattr(
        searcher.session, "get", Mock(return_value=ok_reply(headers={"Content-Type": "text/html"}))
    )
    with pytest.raises(ValueError, match="Semantic Scholar returned a non-JSON reply"):
        searcher.search("test")


def test_search_reply_without_data_raises(searcher, monkeypatch):
    monkeypatch.setattr(searcher.session, "get", Mock(return_value=ok_reply({"message": "oops"})))
    with pytest.raises(ValueError, match="Semantic Scholar reply has no 'data' list"):
        searcher.search("test")


def test_search_network_error_raises(searcher, monkeypatch):
    monkeypatch.setattr(searcher.session, "get", Mock(side_effect=requests.ConnectionError("down")))
    with pytest.raises(semantic.SemanticScholarRequestError, match="down"):
        searcher.search("test")


@pytest.mark.parametrize("body", [{"total": 0, "offset": 0}, {"total": 0, "data": []}])
def test_search_genuine_empty_is_empty(searcher, monkeypatch, body):
    monkeypatch.setattr(searcher.session, "get", Mock(return_value=ok_reply(body)))
    assert searcher.search("test") == []
