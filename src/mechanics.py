"""Mechanical effects for colony events."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from src.constants import ALL_EVENT_TYPES, FAILED_CONSTRUCTION_EVENT_TYPE

# Stats clamped to [0, 10].
_CAPPED_STATS = ("morale", "security", "health")
# Stats clamped to [0, ∞).
_FLOOR_STATS = ("population", "food", "wood")

_REQUIRED_STATE_KEYS = (
    "day", "colony_name", "population", "food", "wood",
    "morale", "security", "health", "known_threats", "recent_events",
)


def validate_state(state: dict[str, Any]) -> None:
    """Raise ValueError if the state is missing required fields or has out-of-range values."""
    missing = [k for k in _REQUIRED_STATE_KEYS if k not in state]
    if missing:
        raise ValueError(f"State is missing required fields: {missing}")
    for stat in _CAPPED_STATS:
        v = state[stat]
        if not (0 <= v <= 10):
            raise ValueError(f"State field '{stat}' is out of range [0, 10]: {v}")
    for stat in _FLOOR_STATS:
        if state[stat] < 0:
            raise ValueError(f"State field '{stat}' is negative: {state[stat]}")


def clamp_state(state: dict[str, Any]) -> dict[str, Any]:
    clamped = deepcopy(state)
    for stat in _CAPPED_STATS:
        clamped[stat] = max(0, min(10, clamped[stat]))
    for stat in _FLOOR_STATS:
        clamped[stat] = max(0, clamped[stat])
    return clamped


def apply_event(state: dict[str, Any], event_type: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply one event and return (next_state, event_record)."""
    if event_type not in ALL_EVENT_TYPES:
        raise ValueError(f"Unknown event type: {event_type!r}")

    before = deepcopy(state)
    after = deepcopy(state)
    event_type = _resolve_event_type(before, event_type)
    effects = _effects_for(before, event_type)

    for stat, delta in effects.items():
        after[stat] += delta

    after = clamp_state(after)
    after["day"] = before["day"] + 1

    event_record = {
        "day": before["day"],
        "event_type": event_type,
        "effects": _actual_effects(before, after, effects),
        "summary": summarize_event(before, event_type),
    }
    return after, event_record


def summarize_event(state: dict[str, Any], event_type: str) -> str:
    summaries = {
        "good_harvest": "A strong harvest added food to the stores.",
        "poor_harvest": "A poor harvest reduced food and dampened morale.",
        "construction": "Colonists spent wood to strengthen the settlement.",
        "illness": "Illness spread through several homes.",
        "dispute": "A dispute unsettled the colony.",
        "quiet_day": "The day passed quietly while food stores were used.",
        "chaos_gods": "The chaos gods struck the colony when the oracle went silent.",
        "failed_construction": "Construction failed because the colony lacked enough wood.",
    }
    if event_type == "discovery":
        details = [
            "a fresh-water spring north of camp",
            "useful clay deposits near the riverbank",
            "old trail markers beyond the fields",
            "a sheltered hollow suitable for storage",
            "edible roots growing along the ridge",
        ]
        return f"Scouts discovered {details[state['day'] % len(details)]}."
    return summaries[event_type]


def _effects_for(state: dict[str, Any], event_type: str) -> dict[str, int]:
    if event_type == "good_harvest":
        return {"food": 15, "morale": 1}
    if event_type == "poor_harvest":
        return {"food": -10, "morale": -1}
    if event_type == "construction":
        return {"wood": -10, "security": 1, "morale": 1}
    if event_type == "failed_construction":
        return {}
    if event_type == "illness":
        effects: dict[str, int] = {"health": -1, "morale": -1}
        if state["health"] <= 3:
            effects["population"] = -1
        return effects
    if event_type == "dispute":
        return {"morale": -2, "security": -1}
    if event_type == "discovery":
        return {"morale": 1}
    if event_type == "quiet_day":
        return {"food": -5}
    if event_type == "chaos_gods":
        return {"health": -1, "security": -1, "morale": -1}
    raise ValueError(f"Unknown event type: {event_type!r}")


def _resolve_event_type(state: dict[str, Any], event_type: str) -> str:
    if event_type == "construction" and state["wood"] < 10:
        return FAILED_CONSTRUCTION_EVENT_TYPE
    return event_type


def _actual_effects(
    before: dict[str, Any],
    after: dict[str, Any],
    intended: dict[str, int],
) -> dict[str, int]:
    """Return the real deltas after clamping, omitting stats that didn't change."""
    return {
        stat: after[stat] - before[stat]
        for stat in intended
        if after[stat] != before[stat]
    }
