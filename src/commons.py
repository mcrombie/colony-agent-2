"""Varenhold's river commons: seasons, rival guilds and visible public works."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from src.mechanics import apply_event, clamp_state, validate_state

GUILDS = ("Keepers", "Makers", "Riverfolk")
DISTRICTS = (
    ("grove", "Grove Ward", "Keepers", "Orchard terraces", "food"),
    ("lantern", "Lantern Ward", "Makers", "Public atelier", "culture"),
    ("harbor", "River Quay", "Riverfolk", "Covered market", "trade"),
    ("forum", "Commons Square", "Keepers", "Assembly gardens", "trust"),
)
SEASONS = ("Spring thaw", "High summer", "Amber autumn", "Deep winter")
STATS = ("population", "food", "wood", "morale", "security", "health")


def season_for(day: int) -> str:
    return SEASONS[(day // 12) % 4]


def migrate_state(state: dict[str, Any]) -> dict[str, Any]:
    """Add a charter; never erase or reset legacy stats and history."""
    validate_state(state)
    result = deepcopy(state)
    if "commons" not in result:
        result["commons"] = {
            "charter_day": state["day"], "treasury": 24, "trust": 52, "culture": 8,
            "guilds": {guild: 50 for guild in GUILDS},
            "council": {"guild": "Keepers", "term_start": state["day"], "term": 1},
            "districts": {key: {"level": 0, "progress": 0} for key, *_ in DISTRICTS},
            "active_project": "grove", "completed_projects": [],
            "api_attempts": 0, "input_tokens": 0, "output_tokens": 0,
        }
    result["schema_version"] = 2
    validate_commons(result)
    return result


def validate_commons(state: dict[str, Any]) -> None:
    validate_state(state)
    commons = state["commons"]
    for key, limit in (("treasury", 500), ("trust", 100), ("culture", 100)):
        if type(commons[key]) is not int or not 0 <= commons[key] <= limit:
            raise ValueError(f"Invalid commons {key}")
    if set(commons["guilds"]) != set(GUILDS):
        raise ValueError("Invalid commons guilds")
    for support in commons["guilds"].values():
        if type(support) is not int or not 0 <= support <= 100:
            raise ValueError("Invalid guild support")
    if commons["council"]["guild"] not in GUILDS:
        raise ValueError("Invalid council guild")
    if set(commons["districts"]) != {row[0] for row in DISTRICTS}:
        raise ValueError("Invalid districts")
    if commons["active_project"] not in commons["districts"]:
        raise ValueError("Invalid active project")
    for district in commons["districts"].values():
        if type(district["level"]) is not int or not 0 <= district["level"] <= 4:
            raise ValueError("Invalid district level")
        if type(district["progress"]) is not int or not 0 <= district["progress"] < 6:
            raise ValueError("Invalid project progress")


def advance_commons(state: dict[str, Any], event_type: str) -> tuple[dict[str, Any], dict[str, Any]]:
    before = migrate_state(state)
    after, record = apply_event(before, event_type)
    city = after["commons"]
    day = before["day"]
    notes: list[str] = []
    ledger: dict[str, int] = {}
    charter_age = day - city["charter_day"]
    if charter_age == 0:
        notes.append("Varenhold ratified its River Commons charter: three guilds share four districts.")
    if charter_age > 0 and charter_age % 7 == 0:
        previous = city["council"]["guild"]
        candidates = [guild for guild in GUILDS if guild != previous]
        next_guild = min(candidates, key=lambda guild: (city["guilds"][guild],
                         (GUILDS.index(guild) - city["council"]["term"]) % 3))
        city["council"] = {"guild": next_guild, "term_start": day,
                           "term": city["council"]["term"] + 1}
        city["trust"] += 4
        notes.append(f"The council passed to the {next_guild} for a seven-day term.")
    governing = city["council"]["guild"]
    season = (day // 12) % 4
    upkeep = max(1, (after["population"] + 11) // 12)
    production = (9, 12, 10, 5)[season] + city["districts"]["grove"]["level"]
    timber = 3 + (governing == "Keepers")
    if after["population"] == 0:
        production = timber = upkeep = 0
    after["food"] += production - upkeep
    after["wood"] += timber
    ledger.update(food_produced=production, food_consumed=upkeep, timber_gathered=timber)
    revenue = 3 + city["districts"]["harbor"]["level"] + (governing == "Riverfolk")
    maintenance = 2 + sum(d["level"] for d in city["districts"].values()) // 4
    if after["population"]:
        city["treasury"] += revenue - maintenance
    ledger.update(tax_revenue=revenue if after["population"] else 0,
                  maintenance=maintenance if after["population"] else 0)
    civic = {
        "river_market": {"treasury": 8, "trust": 1},
        "lantern_festival": {"culture": 7, "trust": 3, "treasury": -5},
        "public_clinic": {"trust": 4, "treasury": -4},
        "woodland_stewardship": {"trust": 2},
        "council_forum": {"trust": 5},
        "river_flood": {"treasury": -7, "trust": -4},
        "guild_rivalry": {"trust": -7, "culture": -1},
        "craft_fair": {"culture": 5, "treasury": 6},
        "dispute": {"trust": -3},
        "discovery": {"culture": 2},
    }
    for key, delta in civic.get(record["event_type"], {}).items():
        city[key] += delta
    favored = {"good_harvest": "Keepers", "woodland_stewardship": "Keepers",
               "public_clinic": "Keepers", "craft_fair": "Makers", "construction": "Makers",
               "lantern_festival": "Makers", "river_market": "Riverfolk"}.get(record["event_type"])
    for guild in GUILDS:
        city["guilds"][guild] += (3 if favored == guild else 0) - (1 if governing == guild else 0)
        if record["event_type"] == "council_forum":
            city["guilds"][guild] += 2
        if record["event_type"] == "guild_rivalry":
            city["guilds"][guild] -= 3
    if after["population"] > 0:
        _work_on_project(after, notes, ledger)
    if day % 5 == 0:
        city["culture"] -= 2
        city["trust"] -= 2
    if day % 7 == 0:
        after["security"] -= 1
    if day % 9 == 0:
        after["health"] -= 1
    if day % 11 == 0:
        after["morale"] -= 1
    food_surplus = max(0, after["food"] - (180 + city["districts"]["harbor"]["level"] * 15))
    wood_surplus = max(0, after["wood"] - 150)
    if food_surplus or wood_surplus:
        after["food"] -= food_surplus
        after["wood"] -= wood_surplus
        sold = (food_surplus + wood_surplus) // 3
        city["treasury"] += sold
        ledger.update(surplus_food_exported=food_surplus, surplus_timber_exported=wood_surplus,
                      export_income=sold)
    if after["food"] <= 0 and after["population"] > 0:
        after["morale"] -= 2
        after["health"] -= 1
        after["population"] -= 1
        notes.append("Empty stores forced a household to leave; the council must secure food.")
    elif day % 12 == 0 and after["health"] >= 6 and city["trust"] >= 50 and after["food"] > 50:
        after["population"] += 1
        notes.append("A new household joined the river commons.")
    if city["treasury"] < 0:
        city["trust"] -= 3
        notes.append("The treasury could not cover every obligation; public confidence fell.")
    after = clamp_state(after)
    for key, limit in (("treasury", 500), ("trust", 100), ("culture", 100)):
        city[key] = max(0, min(limit, city[key]))
    for guild in GUILDS:
        city["guilds"][guild] = max(0, min(100, city["guilds"][guild]))
    after["commons"] = city
    record.update(
        effects={key: after[key] - before[key] for key in STATS if after[key] != before[key]},
        civic_effects={key: city[key] - before["commons"][key]
                       for key in ("treasury", "trust", "culture") if city[key] != before["commons"][key]},
        season=season_for(day), council=governing, notes=notes, ledger=ledger,
        snapshot={**{key: after[key] for key in STATS},
                  **{key: city[key] for key in ("treasury", "trust", "culture")}},
    )
    validate_commons(after)
    return after, record


def _work_on_project(state: dict[str, Any], notes: list[str], ledger: dict[str, int]) -> None:
    city = state["commons"]
    key = city["active_project"]
    district = city["districts"][key]
    if state["wood"] < 3 or city["treasury"] < 2:
        notes.append("Public works paused until timber and treasury recover.")
        return
    state["wood"] -= 3
    city["treasury"] -= 2
    ledger.update(project_timber=3, project_coins=2)
    district["progress"] += 1
    if district["progress"] < 6:
        return
    row = next(row for row in DISTRICTS if row[0] == key)
    district["progress"] = 0
    maintaining = district["level"] == 4
    district["level"] = min(4, district["level"] + 1)
    action = "restored" if maintaining else "completed"
    title = f"{row[3]} {action} in {row[1]}"
    city["completed_projects"] = (city["completed_projects"] + [{
        "day": state["day"] - 1, "district": key, "title": title,
        "level": district["level"]}])[-24:]
    city["culture"] += 3 if key == "lantern" else 1
    city["trust"] += 3
    city["guilds"][row[2]] += 5
    notes.append(title + ".")
    keys = [row[0] for row in DISTRICTS]
    city["active_project"] = keys[(keys.index(key) + 1) % len(keys)]
