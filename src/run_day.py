"""Advance at most once per UTC date, with a recoverable multi-file transaction."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from src.commons import advance_commons, migrate_state
from src.constants import RECENT_EVENT_WINDOW
from src.dashboard import render_dashboard
from src.mechanics import validate_state
from src.narrative import write_daily_entry
from src.selector import select_event

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "src" / "state.json"


def load_state(path: Path = STATE_PATH) -> dict[str, Any]:
    state = json.loads(path.read_text(encoding="utf-8"))
    validate_state(state)
    return state


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def colony_lock(data_dir: Path) -> Iterator[None]:
    """OS-managed lock releases even if a process dies; the small lock file remains."""
    data_dir.mkdir(parents=True, exist_ok=True)
    with (data_dir / ".run_day.lock").open("a+b") as stream:
        stream.seek(0)
        if os.fstat(stream.fileno()).st_size == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError("Another colony run is active") from exc
        else:
            import fcntl
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError("Another colony run is active") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _paths(data_dir: Path, output_dir: Path) -> dict[str, Path]:
    return {"history": data_dir / "history.md", "events": data_dir / "events.jsonl",
            "html": output_dir / "index.html", "map": output_dir / "colony.svg",
            "chronicle": output_dir / "history.md", "state": data_dir / "state.json"}


def _recover(data_dir: Path, output_dir: Path) -> None:
    pending = data_dir / ".pending-day.json"
    if not pending.exists():
        return
    payload = json.loads(pending.read_text(encoding="utf-8"))
    targets = _paths(data_dir, output_dir)
    if set(payload) != set(targets) or not all(isinstance(value, str) for value in payload.values()):
        raise ValueError("Invalid pending colony transaction")
    migrate_state(json.loads(payload["state"]))
    for key, path in targets.items():
        atomic_write(path, payload[key])
    pending.unlink()


def _records(data_dir: Path) -> tuple[str, list[dict[str, Any]]]:
    path = data_dir / "events.jsonl"
    raw = path.read_text(encoding="utf-8") if path.exists() else ""
    return raw, [json.loads(line) for line in raw.splitlines() if line.strip()]


def render_only(data_dir: Path = ROOT / "src", output_dir: Path = ROOT / "docs") -> None:
    with colony_lock(data_dir):
        _recover(data_dir, output_dir)
        state = load_state(data_dir / "state.json")
        _, records = _records(data_dir)
        html, svg = render_dashboard(state, records)
        atomic_write(output_dir / "index.html", html)
        atomic_write(output_dir / "colony.svg", svg)
        history = data_dir / "history.md"
        atomic_write(output_dir / "history.md", history.read_text(encoding="utf-8") if history.exists() else "")


def run_day(run_date: date | None = None, data_dir: Path = ROOT / "src",
            output_dir: Path = ROOT / "docs") -> dict[str, Any] | None:
    today = run_date or datetime.now(timezone.utc).date()
    with colony_lock(data_dir):
        _recover(data_dir, output_dir)
        state_before = migrate_state(load_state(data_dir / "state.json"))
        previous_date = state_before.get("last_run_date")
        if previous_date:
            previous = date.fromisoformat(previous_date)
            if previous == today:
                return None
            if previous > today:
                raise ValueError("Cannot advance before the last recorded UTC date")
        event_type, director = select_event(state_before)
        state_after, record = advance_commons(state_before, event_type)
        record.update(run_date=today.isoformat(), director=director)
        state_after["last_run_date"] = today.isoformat()
        state_after["recent_events"] = (state_before.get("recent_events", []) + [record])[-RECENT_EVENT_WINDOW:]
        for metric in ("api_attempts", "input_tokens", "output_tokens"):
            state_after["commons"][metric] += director.get(metric, 0)
        raw_events, records = _records(data_dir)
        records.append(record)
        history_path = data_dir / "history.md"
        raw_history = history_path.read_text(encoding="utf-8") if history_path.exists() else f"# {state_after['colony_name']} — Colony History\n"
        history = raw_history.rstrip() + "\n\n" + write_daily_entry(state_before, record, state_after)
        html, svg = render_dashboard(state_after, records)
        payload = {
            "history": history,
            "events": raw_events.rstrip() + ("\n" if raw_events.strip() else "") + json.dumps(record, ensure_ascii=False) + "\n",
            "html": html, "map": svg, "chronicle": history,
            "state": json.dumps(state_after, indent=2, ensure_ascii=False) + "\n",
        }
        atomic_write(data_dir / ".pending-day.json", json.dumps(payload, ensure_ascii=False))
        _recover(data_dir, output_dir)
        return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--render-only", action="store_true", help="Refresh the atlas without advancing the world")
    parser.add_argument("--date", type=date.fromisoformat, help="UTC date for a reproducible run; defaults to today")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "src")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "docs")
    args = parser.parse_args()
    if args.render_only:
        render_only(args.data_dir, args.output_dir)
        print(f"Atlas refreshed: {args.output_dir / 'index.html'}")
        return
    record = run_day(args.date, args.data_dir, args.output_dir)
    if record is None:
        print("Already advanced for this UTC date; no API calls or new events.")
    else:
        print(f"Day {record['day']}: {record['event_type']} — {record['summary']}")


if __name__ == "__main__":
    main()
