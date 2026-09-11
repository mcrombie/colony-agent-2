import pytest

from src import selector


@pytest.fixture(autouse=True)
def no_real_api_or_local_secrets(monkeypatch):
    monkeypatch.setattr(selector, "load_local_env", lambda: None)
    monkeypatch.setenv("COLONY_DIRECTOR", "local")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("COLONY_AI_INTERVAL", raising=False)
