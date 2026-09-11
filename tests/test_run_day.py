import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from src import run_day as runner


@pytest.fixture
def paths(tmp_path):
    data, output = tmp_path / "src", tmp_path / "docs"
    data.mkdir()
    for name in ("state.json", "events.jsonl", "history.md"):
        (data / name).write_bytes((runner.ROOT / "src" / name).read_bytes())
    state = json.loads((data / "state.json").read_text(encoding="utf-8"))
    state.pop("last_run_date", None)
    (data / "state.json").write_text(json.dumps(state), encoding="utf-8")
    return data, output


def test_daily_idempotency_preserves_history_and_makes_no_second_call(paths, monkeypatch):
    data, output = paths
    before = runner.load_state(data / "state.json")
    old_history = (data / "history.md").read_text(encoding="utf-8")
    first = runner.run_day(date(2026, 9, 11), data, output)
    assert first["day"] == before["day"]
    assert (data / "history.md").read_text(encoding="utf-8").startswith(old_history.rstrip())
    assert runner.load_state(data / "state.json")["day"] == before["day"] + 1
    monkeypatch.setattr(runner, "select_event", lambda _: pytest.fail("second selection"))
    snapshots = {path: path.read_bytes() for path in [data / "state.json", data / "history.md", data / "events.jsonl", output / "index.html"]}
    assert runner.run_day(date(2026, 9, 11), data, output) is None
    assert snapshots == {path: path.read_bytes() for path in snapshots}
    with pytest.raises(ValueError, match="before the last"):
        runner.run_day(date(2026, 9, 10), data, output)


def test_interrupted_commit_recovers_exactly_once(paths, monkeypatch):
    data, output = paths
    before = runner.load_state(data / "state.json")
    count_before = len((data / "events.jsonl").read_text().splitlines())
    original_write = runner.atomic_write
    calls = 0

    def interrupted(path: Path, text: str):
        nonlocal calls
        calls += 1
        if calls == 4:
            raise OSError("simulated disk interruption")
        original_write(path, text)

    monkeypatch.setattr(runner, "atomic_write", interrupted)
    with pytest.raises(OSError, match="interruption"):
        runner.run_day(date(2026, 9, 11), data, output)
    assert (data / ".pending-day.json").exists()
    monkeypatch.setattr(runner, "atomic_write", original_write)
    monkeypatch.setattr(runner, "select_event", lambda _: pytest.fail("recovery must not pay again"))
    assert runner.run_day(date(2026, 9, 11), data, output) is None
    assert not (data / ".pending-day.json").exists()
    assert runner.load_state(data / "state.json")["day"] == before["day"] + 1
    assert len((data / "events.jsonl").read_text().splitlines()) == count_before + 1
    assert (output / "index.html").exists()
    assert (output / "history.md").read_bytes() == (data / "history.md").read_bytes()


def test_lock_rejects_overlap_and_releases(paths):
    data, _ = paths
    with runner.colony_lock(data):
        with pytest.raises(RuntimeError, match="active"):
            with runner.colony_lock(data):
                pass
    with runner.colony_lock(data):
        pass


def test_render_only_leaves_world_and_ledger_unchanged(paths):
    data, output = paths
    original = {path: path.read_bytes() for path in data.iterdir()}
    runner.render_only(data, output)
    assert all(path.read_bytes() == content for path, content in original.items())
    assert (output / "colony.svg").exists()


def test_gap_advances_only_one_day(paths):
    data, output = paths
    runner.run_day(date(2026, 9, 11), data, output)
    before = runner.load_state(data / "state.json")["day"]
    runner.run_day(date(2026, 9, 11) + timedelta(days=60), data, output)
    assert runner.load_state(data / "state.json")["day"] == before + 1
