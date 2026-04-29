from copy import deepcopy

import pytest

from src.mechanics import apply_event, clamp_state, validate_state

BASE_STATE = {
    "day": 1,
    "colony_name": "Varenhold",
    "population": 100,
    "food": 120,
    "wood": 60,
    "morale": 7,
    "security": 5,
    "health": 8,
    "known_threats": ["wolves", "winter"],
    "recent_events": [],
}


def state_with(**overrides):
    s = deepcopy(BASE_STATE)
    s.update(overrides)
    return s


# --- validate_state ---

def test_validate_state_passes_for_valid_state():
    validate_state(BASE_STATE)  # should not raise


def test_validate_state_raises_on_missing_key():
    bad = deepcopy(BASE_STATE)
    del bad["food"]
    with pytest.raises(ValueError, match="missing required fields"):
        validate_state(bad)


def test_validate_state_raises_on_out_of_range_morale():
    with pytest.raises(ValueError, match="morale"):
        validate_state(state_with(morale=11))


def test_validate_state_raises_on_negative_food():
    with pytest.raises(ValueError, match="food"):
        validate_state(state_with(food=-1))


# --- clamp_state ---

def test_clamp_caps_limited_stats_at_10():
    clamped = clamp_state(state_with(morale=15, security=12, health=99))
    assert clamped["morale"] == 10
    assert clamped["security"] == 10
    assert clamped["health"] == 10


def test_clamp_floors_limited_stats_at_0():
    clamped = clamp_state(state_with(morale=-5, security=-1))
    assert clamped["morale"] == 0
    assert clamped["security"] == 0


def test_clamp_floors_non_negative_stats_at_0():
    clamped = clamp_state(state_with(food=-20, wood=-5))
    assert clamped["food"] == 0
    assert clamped["wood"] == 0


# --- apply_event ---

def test_day_increments():
    after, _ = apply_event(state_with(day=5), "quiet_day")
    assert after["day"] == 6


def test_good_harvest_adds_food_and_morale():
    after, record = apply_event(state_with(food=100, morale=5), "good_harvest")
    assert after["food"] == 115
    assert after["morale"] == 6
    assert record["effects"]["food"] == 15
    assert record["effects"]["morale"] == 1


def test_food_clamped_to_zero_on_quiet_day():
    after, record = apply_event(state_with(food=3), "quiet_day")
    assert after["food"] == 0
    assert record["effects"]["food"] == -3  # actual delta, not intended


def test_construction_consumes_wood_and_raises_security():
    after, record = apply_event(state_with(wood=20, security=4), "construction")
    assert after["wood"] == 10
    assert after["security"] == 5
    assert record["effects"]["wood"] == -10
    assert record["effects"]["security"] == 1


def test_construction_without_wood_becomes_failed_construction():
    after, record = apply_event(state_with(wood=5, security=4, morale=7), "construction")
    assert record["event_type"] == "failed_construction"
    assert after["wood"] == 5
    assert after["security"] == 4
    assert after["morale"] == 7
    assert record["effects"] == {}


def test_illness_reduces_health_and_morale():
    after, record = apply_event(state_with(health=6, morale=7), "illness")
    assert after["health"] == 5
    assert after["morale"] == 6


def test_illness_reduces_population_when_health_critical():
    after, record = apply_event(state_with(health=3, population=100), "illness")
    assert after["population"] == 99
    assert record["effects"]["population"] == -1


def test_chaos_gods_reduce_health_security_morale():
    after, record = apply_event(state_with(health=6, security=5, morale=7), "chaos_gods")
    assert after["health"] == 5
    assert after["security"] == 4
    assert after["morale"] == 6
    assert record["effects"] == {"health": -1, "security": -1, "morale": -1}


def test_unknown_event_type_raises():
    with pytest.raises(ValueError, match="Unknown event type"):
        apply_event(BASE_STATE, "volcano_eruption")


def test_actual_effects_omits_zeroed_stats():
    # morale is already at 10; good_harvest tries +1 but it's clamped to 0 actual change
    after, record = apply_event(state_with(food=0, morale=10), "good_harvest")
    assert "morale" not in record["effects"]
    assert record["effects"]["food"] == 15
