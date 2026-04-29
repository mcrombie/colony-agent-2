"""Run one day of the colony simulation."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from src.constants import RECENT_EVENT_WINDOW
from src.mechanics import apply_event, validate_state
from src.narrative import write_daily_entry
from src.selector import choose_event

_SRC_DIR = Path(__file__).resolve().parent
STATE_PATH = _SRC_DIR / "state.json"
HISTORY_PATH = _SRC_DIR / "history.md"
EVENT_LOG_PATH = _SRC_DIR / "events.jsonl"


def load_state(path: Path = STATE_PATH) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        state = json.load(f)
    validate_state(state)
    return state


def save_state(state: dict[str, Any], path: Path = STATE_PATH) -> None:
    # Keep only the most recent events inline; full history lives in events.jsonl.
    trimmed = deepcopy(state)
    trimmed["recent_events"] = trimmed.get("recent_events", [])[-RECENT_EVENT_WINDOW:]
    with path.open("w", encoding="utf-8") as f:
        json.dump(trimmed, f, indent=2)
        f.write("\n")


def append_history(entry: str, path: Path = HISTORY_PATH) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write("\n" + entry)


def log_event(event_record: dict[str, Any], path: Path = EVENT_LOG_PATH) -> None:
    """Append one event record as a JSON line to events.jsonl."""
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event_record) + "\n")


def run_day() -> dict[str, Any]:
    """Advance the colony by one day and persist the result."""
    state_before = load_state()
    event_type = choose_event(state_before)
    state_after, event_record = apply_event(deepcopy(state_before), event_type)

    # Keep recent_events in state for context window on next call.
    state_after.setdefault("recent_events", [])
    state_after["recent_events"] = (
        state_before.get("recent_events", []) + [event_record]
    )[-RECENT_EVENT_WINDOW:]

    entry = write_daily_entry(state_before, event_record, state_after)
    append_history(entry)
    log_event(event_record)
    save_state(state_after)
    return event_record


def main() -> None:
    event_record = run_day()
    print(f"Day {event_record['day']}: {event_record['event_type']} — {event_record['summary']}")


if __name__ == "__main__":
    main()
