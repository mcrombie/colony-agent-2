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
    for stat in ("day",) + _CAPPED_STATS + _FLOOR_STATS:
        if type(state[stat]) is not int:
            raise ValueError(f"State field '{stat}' must be an integer")
    if state["day"] < 0:
        raise ValueError("State field 'day' must not be negative")
    if not isinstance(state["colony_name"], str) or not state["colony_name"].strip():
        raise ValueError("State field 'colony_name' must be a nonempty string")
    for field in ("known_threats", "recent_events"):
        if not isinstance(state[field], list):
            raise ValueError(f"State field '{field}' must be a list")
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
        "river_market": "River barges exchanged grain, timber and news at the quay.",
        "lantern_festival": "The Lantern Ward opened its courtyards for a night of music.",
        "public_clinic": "Grove healers held a free clinic for every district.",
        "woodland_stewardship": "The Keepers coppiced the woodland and renewed its paths.",
        "council_forum": "Citizens argued their priorities in an open council forum.",
        "river_flood": "High water damaged the quay and soaked the communal stores.",
        "guild_rivalry": "Competing guilds halted work over the allocation of public funds.",
        "craft_fair": "The Makers displayed river glass, pottery and carved instruments.",
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
    civic_effects = {
        "river_market": {"food": 8, "wood": 4},
        "lantern_festival": {"food": -6, "morale": 2},
        "public_clinic": {"food": -4, "health": 2},
        "woodland_stewardship": {"wood": 12, "health": 1},
        "council_forum": {"morale": 1, "security": 1},
        "river_flood": {"food": -16, "wood": -6, "security": -1},
        "guild_rivalry": {"morale": -1, "wood": -4},
        "craft_fair": {"wood": -6, "morale": 1},
    }
    if event_type in civic_effects:
        return civic_effects[event_type]
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
