from copy import deepcopy
from unittest.mock import MagicMock, patch

import pytest

from src import selector
from src.constants import CHAOS_GODS_EVENT_TYPE, SELECTABLE_EVENT_TYPES
from src.selector import MissingConfigError, SelectorError, _choose_with_claude

BASE_STATE = {
    "day": 1,
    "colony_name": "Varenhold",
    "population": 100,
    "food": 120,
    "wood": 60,
    "morale": 7,
    "security": 5,
    "health": 8,
    "known_threats": ["wolves", "winter"],
    "recent_events": [],
}


# --- choose_event (public API) ---

def test_choose_event_returns_valid_event(monkeypatch):
    monkeypatch.setattr(selector, "load_local_env", lambda: None)
    monkeypatch.setattr(selector, "_choose_with_claude", lambda s: "discovery")
    assert selector.choose_event(deepcopy(BASE_STATE)) == "discovery"


def test_missing_api_key_raises_loudly(monkeypatch):
    monkeypatch.setattr(selector, "load_local_env", lambda: None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(MissingConfigError, match="ANTHROPIC_API_KEY is not set"):
        selector.choose_event(deepcopy(BASE_STATE))


def test_api_failure_falls_back_to_chaos_gods(monkeypatch):
    monkeypatch.setattr(selector, "load_local_env", lambda: None)

    def boom(state):
        raise SelectorError("transient failure")

    monkeypatch.setattr(selector, "_choose_with_claude", boom)
    assert selector.choose_event(deepcopy(BASE_STATE)) == CHAOS_GODS_EVENT_TYPE


def test_api_failure_emits_github_warning(monkeypatch, capsys):
    monkeypatch.setattr(selector, "load_local_env", lambda: None)

    def boom(state):
        raise SelectorError("connection timed out")

    monkeypatch.setattr(selector, "_choose_with_claude", boom)
    selector.choose_event(deepcopy(BASE_STATE))
    out = capsys.readouterr().out
    assert "::warning title=Selector failed::" in out
    assert "connection timed out" in out


# --- _choose_with_claude internals ---

def _make_tool_response(event_type: str) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.input = {"event_type": event_type, "reasoning": "test"}
    response = MagicMock()
    response.content = [block]
    return response


def test_claude_returns_valid_event(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-test")

    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_tool_response("good_harvest")

    with patch("src.selector.anthropic") as mock_anthropic:
        mock_anthropic.Anthropic.return_value = mock_client
        result = _choose_with_claude(deepcopy(BASE_STATE))

    assert result == "good_harvest"


def test_claude_retries_on_transient_error(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(selector.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def create_side_effect(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("temporary")
        return _make_tool_response("quiet_day")

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = create_side_effect

    with patch("src.selector.anthropic") as mock_anthropic:
        mock_anthropic.Anthropic.return_value = mock_client
        result = _choose_with_claude(deepcopy(BASE_STATE))

    assert result == "quiet_day"
    assert calls["n"] == 2


def test_claude_raises_after_max_attempts(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(selector.time, "sleep", lambda s: None)

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = ConnectionError("always fails")

    with patch("src.selector.anthropic") as mock_anthropic:
        mock_anthropic.Anthropic.return_value = mock_client
        with pytest.raises(SelectorError, match="failed after"):
            _choose_with_claude(deepcopy(BASE_STATE))


def test_claude_raises_on_invalid_event_type(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_tool_response("volcano_eruption")

    with patch("src.selector.anthropic") as mock_anthropic:
        mock_anthropic.Anthropic.return_value = mock_client
        with pytest.raises(SelectorError, match="invalid event type"):
            _choose_with_claude(deepcopy(BASE_STATE))
