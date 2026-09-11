"""A reproducible civic director, with explicitly opted-in, bounded Claude advice."""

from __future__ import annotations

import json
import os
import random
from typing import Any

from src.config import load_local_env
from src.constants import SELECTABLE_EVENT_TYPES

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
MAX_OUTPUT_TOKENS = 160
API_TIMEOUT_SECONDS = 20


class SelectorError(RuntimeError):
    """Claude advice was unavailable; local simulation can still continue."""


class MissingConfigError(SelectorError):
    """Optional Claude advice has no API key."""


def choose_local_event(state: dict[str, Any]) -> str:
    """Use needs, season and recent history without network or paid dependencies."""
    weights = {event: 2.0 for event in SELECTABLE_EVENT_TYPES}
    weights.update(river_market=5, craft_fair=4, council_forum=3,
                   woodland_stewardship=4, good_harvest=4, discovery=1,
                   poor_harvest=1, illness=1, dispute=1, quiet_day=1)
    if state["food"] < 55:
        weights.update(good_harvest=35, river_market=20, poor_harvest=0.2)
    if state["wood"] < 20:
        weights.update(woodland_stewardship=35, construction=0.1)
    if state["health"] < 6:
        weights["public_clinic"] = 28
    if state["morale"] < 5:
        weights["lantern_festival"] = 24
    if state["security"] < 4:
        weights["construction"] = 20 if state["wood"] >= 10 else 0
        weights["council_forum"] = 12
    season = (state["day"] // 12) % 4
    weights["river_flood"] = 4 if season == 0 else 0.5
    weights["poor_harvest"] *= 3 if season == 3 else 1
    mandate = state.get("commons", {}).get("council", {}).get("guild", "Keepers")
    favored = {"Keepers": "woodland_stewardship", "Makers": "craft_fair",
               "Riverfolk": "river_market"}[mandate]
    weights[favored] *= 1.7
    for event in state.get("recent_events", [])[-3:]:
        key = event.get("event_type")
        if key in weights:
            weights[key] *= 0.35
    rng = random.Random(f"varenhold-commons-v1:{state['colony_name']}:{state['day']}")
    return rng.choices(list(weights), weights=list(weights.values()), k=1)[0]


def select_event(state: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    load_local_env()
    mode = os.getenv("COLONY_DIRECTOR", "local").strip().lower()
    if mode not in {"local", "claude"}:
        raise ValueError("COLONY_DIRECTOR must be 'local' or 'claude'")
    if mode == "local":
        return choose_local_event(state), {"source": "local", "api_attempts": 0}
    try:
        interval = int(os.getenv("COLONY_AI_INTERVAL", "7"))
        if interval < 1:
            raise ValueError
    except ValueError as exc:
        raise ValueError("COLONY_AI_INTERVAL must be a positive integer") from exc
    if state["day"] % interval:
        return choose_local_event(state), {"source": "local", "api_attempts": 0}
    if not os.getenv("ANTHROPIC_API_KEY"):
        return choose_local_event(state), {
            "source": "local_fallback", "api_attempts": 0, "reason": "missing_key"}
    try:
        event, usage = _choose_with_claude(state)
        return event, {"source": "claude", "api_attempts": 1, **usage}
    except SelectorError as exc:
        # Exception bodies can contain credentials or request content. Log only our category.
        print(f"::warning title=Claude unavailable::{exc}; using the local civic director.")
        return choose_local_event(state), {
            "source": "local_fallback", "api_attempts": 1, "reason": str(exc)}


def choose_event(state: dict[str, Any]) -> str:
    return select_event(state)[0]


def _choose_with_claude(state: dict[str, Any]) -> tuple[str, dict[str, int]]:
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise MissingConfigError("missing_key")
    try:
        import anthropic

        with anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"],
                                 max_retries=0, timeout=API_TIMEOUT_SECONDS) as client:
            response = client.messages.create(
                model=os.getenv("ANTHROPIC_MODEL") or DEFAULT_MODEL,
                max_tokens=MAX_OUTPUT_TOKENS,
                tools=[{"name": "select_event", "description": "Choose the day's civic event.",
                        "input_schema": {"type": "object", "properties": {
                            "event_type": {"type": "string", "enum": list(SELECTABLE_EVENT_TYPES)}},
                            "required": ["event_type"], "additionalProperties": False}}],
                tool_choice={"type": "tool", "name": "select_event"},
                messages=[{"role": "user", "content": _build_prompt(state)}],
            )
        for block in response.content:
            if block.type == "tool_use" and block.name == "select_event":
                event = block.input.get("event_type")
                if event in SELECTABLE_EVENT_TYPES:
                    return event, {"input_tokens": int(response.usage.input_tokens),
                                   "output_tokens": int(response.usage.output_tokens)}
        raise SelectorError("invalid_response")
    except SelectorError:
        raise
    except Exception as exc:
        raise SelectorError(type(exc).__name__) from None


def _build_prompt(state: dict[str, Any]) -> str:
    payload = {key: state[key] for key in (
        "day", "colony_name", "population", "food", "wood", "morale", "security", "health")}
    payload["colony_name"] = payload["colony_name"][:80]
    payload["recent_events"] = [event.get("event_type", "")[:40]
                                for event in state.get("recent_events", [])[-3:]]
    return ("Direct a river city of guild politics, public works, culture and seasonal trade. "
            "Choose one plausible varied event, balancing hardship with recovery. "
            "The engine applies all effects.\n" + json.dumps(payload, separators=(",", ":")))
