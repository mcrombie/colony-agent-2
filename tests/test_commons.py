from collections import Counter
from copy import deepcopy

from src.commons import advance_commons, migrate_state, validate_commons
from src.dashboard import render_dashboard


def load_state():
    # A stable legacy fixture: daily commits must never change test preconditions.
    return {"day": 1, "colony_name": "Varenhold", "population": 100,
            "food": 120, "wood": 60, "morale": 7, "security": 5,
            "health": 8, "known_threats": ["wolves", "winter"], "recent_events": []}
from src.selector import choose_local_event


def test_migration_preserves_original_and_legacy_history():
    before = load_state()
    original = deepcopy(before)
    after = migrate_state(before)
    assert before == original
    for key in ("day", "population", "food", "wood", "health", "morale", "security", "recent_events"):
        assert after[key] == before[key]
    assert after["commons"]["charter_day"] == before["day"]
    assert migrate_state(after) == after


def test_public_works_spend_real_resources_and_complete():
    state = migrate_state(load_state())
    state["wood"] = 60
    state["commons"]["treasury"] = 60
    for _ in range(6):
        before = deepcopy(state)
        state, record = advance_commons(state, "quiet_day")
        assert record["ledger"]["project_timber"] == 3
        assert record["effects"].get("wood", 0) == state["wood"] - before["wood"]
    assert state["commons"]["districts"]["grove"]["level"] == 1
    assert state["commons"]["active_project"] == "lantern"
    assert "completed" in state["commons"]["completed_projects"][-1]["title"]


def test_unfunded_work_pauses_without_inventing_resources():
    state = migrate_state(load_state())
    state["commons"]["treasury"] = 0
    state, record = advance_commons(state, "river_flood")
    assert state["commons"]["districts"]["grove"]["progress"] == 0
    assert state["commons"]["treasury"] == 0
    assert any("paused" in note for note in record["notes"])


def test_two_year_simulation_stays_viable_varied_and_bounded():
    state = load_state()
    events, councils = Counter(), Counter()
    for _ in range(730):
        state, record = advance_commons(state, choose_local_event(state))
        state["recent_events"] = (state["recent_events"] + [record])[-5:]
        validate_commons(state)
        events[record["event_type"]] += 1
        councils[record["council"]] += 1
        assert state["population"] > 0
        assert 0 <= state["food"] <= 240
        assert 0 <= state["wood"] <= 150
    assert len(events) >= 12
    assert len(councils) == 3
    assert min(d["level"] for d in state["commons"]["districts"].values()) >= 1
    assert state["food"] > 0
    assert state["health"] >= 3
    assert state["commons"]["api_attempts"] == 0


def test_dashboard_escapes_content_and_does_not_invent_trends():
    state = load_state()
    state["colony_name"] = '<script>alert("x")</script>'
    html, svg = render_dashboard(state, [])
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "Trend recording begins" in html
    assert "charter takes effect on the next daily turn" in html
    assert "https://" not in html
    assert "<svg" in svg and 'id="map-title"' in svg


def test_dashboard_season_matches_completed_turn_at_boundary():
    state = load_state()
    state["day"] = 12
    html, _ = render_dashboard(state, [])
    assert '<span class="pill">Spring thaw</span>' in html
    assert "Day 011" in html
