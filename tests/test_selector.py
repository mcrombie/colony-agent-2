from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src import selector
from src.constants import SELECTABLE_EVENT_TYPES
from src.run_day import load_state


def sample():
    state = deepcopy(load_state())
    state["day"] = 7
    return state


def sdk(monkeypatch, event="river_market", error=None):
    client = MagicMock()
    client.__enter__.return_value = client
    client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", name="select_event", input={"event_type": event})],
        usage=SimpleNamespace(input_tokens=210, output_tokens=30))
    client.messages.create.side_effect = error
    module = SimpleNamespace(Anthropic=MagicMock(return_value=client))
    monkeypatch.setitem(__import__("sys").modules, "anthropic", module)
    monkeypatch.setenv("COLONY_DIRECTOR", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-secret")
    return module, client


def test_default_never_calls_api_even_with_a_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-secret")
    monkeypatch.setattr(selector, "_choose_with_claude", lambda _: pytest.fail("paid call"))
    event, metadata = selector.select_event(sample())
    assert event in SELECTABLE_EVENT_TYPES
    assert metadata == {"source": "local", "api_attempts": 0}
    assert event == selector.choose_local_event(sample())


def test_missing_key_falls_back_without_punishing_colony(monkeypatch):
    monkeypatch.setenv("COLONY_DIRECTOR", "claude")
    event, metadata = selector.select_event(sample())
    assert event == selector.choose_local_event(sample())
    assert metadata["reason"] == "missing_key"
    assert metadata["api_attempts"] == 0


def test_one_bounded_request_records_usage(monkeypatch):
    module, client = sdk(monkeypatch)
    event, metadata = selector.select_event(sample())
    assert event == "river_market"
    assert metadata == {"source": "claude", "api_attempts": 1, "input_tokens": 210, "output_tokens": 30}
    assert client.messages.create.call_count == 1
    assert client.messages.create.call_args.kwargs["max_tokens"] == 160
    assert module.Anthropic.call_args.kwargs["max_retries"] == 0
    assert module.Anthropic.call_args.kwargs["timeout"] == 20


def test_weekly_cadence_skips_other_days(monkeypatch):
    _, client = sdk(monkeypatch)
    state = sample()
    state["day"] = 8
    _, metadata = selector.select_event(state)
    assert metadata["api_attempts"] == 0
    client.messages.create.assert_not_called()


@pytest.mark.parametrize("event,error", [("volcano", None), (None, ConnectionError("test-secret request body"))])
def test_failure_never_retries_or_prints_secret(monkeypatch, capsys, event, error):
    _, client = sdk(monkeypatch, event, error)
    chosen, metadata = selector.select_event(sample())
    assert chosen == selector.choose_local_event(sample())
    assert chosen != "chaos_gods"
    assert metadata["source"] == "local_fallback"
    assert client.messages.create.call_count == 1
    assert "test-secret" not in capsys.readouterr().out


@pytest.mark.parametrize("interval", ["0", "-2", "oops"])
def test_invalid_cadence_fails_before_paid_call(monkeypatch, interval):
    _, client = sdk(monkeypatch)
    monkeypatch.setenv("COLONY_AI_INTERVAL", interval)
    with pytest.raises(ValueError, match="positive integer"):
        selector.select_event(sample())
    client.messages.create.assert_not_called()
