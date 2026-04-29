"""Event selection via the Anthropic Claude API."""

from __future__ import annotations

import json
import os
import time
from typing import Any

from src.config import load_local_env
from src.constants import CHAOS_GODS_EVENT_TYPE, SELECTABLE_EVENT_TYPES

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
MAX_ATTEMPTS = 3

_SELECT_TOOL: dict[str, Any] = {
    "name": "select_event",
    "description": "Select exactly one event type for the colony's current day.",
    "input_schema": {
        "type": "object",
        "properties": {
            "event_type": {
                "type": "string",
                "enum": list(SELECTABLE_EVENT_TYPES),
                "description": "The event type to apply today.",
            },
            "reasoning": {
                "type": "string",
                "description": "Brief explanation of why this event fits the current state.",
            },
        },
        "required": ["event_type", "reasoning"],
    },
}


class SelectorError(RuntimeError):
    """Raised when event selection fails unrecoverably."""


class MissingConfigError(SelectorError):
    """Raised when ANTHROPIC_API_KEY is not set."""


def choose_event(state: dict[str, Any]) -> str:
    """Select a colony event. Falls back to chaos_gods on API failure; re-raises on missing config."""
    load_local_env()
    try:
        return _choose_with_claude(state)
    except MissingConfigError:
        raise
    except SelectorError as exc:
        _emit_warning(str(exc))
        return CHAOS_GODS_EVENT_TYPE


def _choose_with_claude(state: dict[str, Any]) -> str:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise MissingConfigError("ANTHROPIC_API_KEY is not set.")

    import anthropic

    model = os.getenv("ANTHROPIC_MODEL") or DEFAULT_MODEL
    client = anthropic.Anthropic(api_key=api_key)
    prompt = _build_prompt(state)

    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=256,
                tools=[_SELECT_TOOL],
                tool_choice={"type": "any"},
                messages=[{"role": "user", "content": prompt}],
            )
            for block in response.content:
                if block.type == "tool_use":
                    event_type = block.input["event_type"]
                    if event_type not in SELECTABLE_EVENT_TYPES:
                        raise SelectorError(f"Claude returned invalid event type: {event_type!r}")
                    return event_type
            raise SelectorError("Claude response contained no tool call.")
        except (MissingConfigError, SelectorError):
            raise
        except Exception as exc:
            last_error = exc
            if attempt < MAX_ATTEMPTS:
                time.sleep(attempt * 2)

    raise SelectorError(
        f"Claude API call failed after {MAX_ATTEMPTS} attempts: {_safe_error(last_error)}"
    )


def _build_prompt(state: dict[str, Any]) -> str:
    payload = {
        "allowed_event_types": list(SELECTABLE_EVENT_TYPES),
        "current_state": {
            k: state[k]
            for k in ("day", "colony_name", "population", "food", "wood",
                      "morale", "security", "health", "known_threats")
        },
        "recent_events": state.get("recent_events", []),
    }
    return (
        "You are an event selector for a small fictional colony simulation. "
        "Choose exactly one event type that fits the colony's current state. "
        "Consider resource levels, known threats, and recent history — "
        "but do not apply mechanics yourself, only select the event type.\n\n"
        + json.dumps(payload, indent=2)
    )


def _safe_error(error: Exception | None) -> str:
    if error is None:
        return "unknown error"
    api_key = os.getenv("ANTHROPIC_API_KEY") or ""
    message = str(error)
    if api_key:
        message = message.replace(api_key, "[redacted]")
    message = " ".join(message.split())
    if len(message) > 400:
        message = message[:397] + "..."
    return f"{type(error).__name__}: {message}"


def _emit_warning(message: str) -> None:
    escaped = (
        message.replace("%", "%25")
        .replace("\r", "%0D")
        .replace("\n", "%0A")
        .replace(":", "%3A")
        .replace(",", "%2C")
    )
    print(f"::warning title=Selector failed::{escaped}")
