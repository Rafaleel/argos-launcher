"""Story milestones of a game, taken from its RetroAchievements rules and read from the emulator's RAM."""

import json
import re
import sqlite3
from collections.abc import Callable

from app.collectors.ra_flags import Flag, Operand, core_conditions, milestone_flag, parse_operand, read_operand, reached

_BYTE_EQUALS = re.compile(r"^0xH([0-9a-fA-F]+)=(\d+)$")
_TAG = re.compile(r"^\[([^\]]+)\]")
STORY_KINDS = ("progression", "win_condition")


def build(patch: dict, kinds: dict[int, str]) -> tuple[list[dict], dict[str, int]]:
    """Milestones from the achievements typed `progression` or `win_condition` (`kinds`: achievement id -> type),
    one group per scenario: the `[tag]` that starts the description ("[Leon A]"), or "" when there is none.
    Returns (items, undetectable): `undetectable` counts, per scenario, the story achievements whose rule is
    not a plain "flag becomes X" and so cannot be read from the RAM.

    Items follow the order the server lists the achievements (`patch` has no DisplayOrder; for RE2 that order
    follows the story). Several achievements can share one flag (the scenario's end); the first one names it.
    A milestone counts only while its `gates` hold: the plain byte checks every rule of the scenario has in
    common, which in Resident Evil 2 is the scenario in play (0 = Leon A).
    shortcut: "common byte check = scenario" is a guess that fits RE2; confirm it on the next game.
    A scenario with one readable rule has no "common" to take, so it keeps only the bytes the other scenarios
    share; with none to compare against it is left out."""
    picked: dict[str, list] = {}
    undetectable: dict[str, int] = {}
    for a in patch["Achievements"]:
        rule = a.get("MemAddr", "")
        if kinds.get(a.get("ID")) not in STORY_KINDS or not isinstance(rule, str):
            continue
        tag = _TAG.match(str(a.get("Description", "")).strip())
        scenario = tag[1] if tag else ""
        undetectable.setdefault(scenario, 0)
        flag = milestone_flag(rule)
        if flag:
            picked.setdefault(scenario, []).append((a, flag, set(core_conditions(rule))))
        else:
            undetectable[scenario] += 1
    def byte_checks(conditions) -> list[tuple[int, str, int]]:
        return sorted((int(addr, 16), "H", int(v)) for c in conditions if (m := _BYTE_EQUALS.match(c)) for addr, v in [m.groups()])

    common = {sc: byte_checks(set.intersection(*(c for _, _, c in rules))) for sc, rules in picked.items() if len(rules) > 1}
    # the bytes every scenario with several rules agrees on (RE2: the byte that says Leon A, Leon B, Claire A...)
    scenario_bytes = set.intersection(*({a for a, _, _ in g} for g in common.values())) if common else set()
    out = []
    for scenario, rules in picked.items():
        if scenario in common:
            gates = common[scenario]
        else:  # a lone rule: its conditions could be a room or a boss state, so only the scenario byte is trusted
            gates = byte_checks(rules[0][2]) if scenario_bytes else []
            gates = [g for g in gates if g[0] in scenario_bytes]
            if not gates:
                undetectable[scenario] += len(rules)
                continue
        seen: dict[tuple, dict] = {}
        for a, flag, _ in rules:
            key = (flag.operand, flag.value)
            kind = kinds.get(a.get("ID"), "progression")
            if key in seen:
                if kind == "win_condition":
                    seen[key]["kind"] = "win_condition"
                continue
            item = {"ra_achievement_id": a["ID"], "name": a["Title"], "scenario": scenario, "kind": kind,
                    "address": flag.operand.address, "size": flag.operand.size, "value": flag.value,
                    "gates": [g for g in gates if g[0] != flag.operand.address]}
            seen[key] = item
            out.append(item)
    return out, undetectable


def save(conn: sqlite3.Connection, game_id: int, items: list[dict], undetectable: dict[str, int]) -> None:
    with conn:
        conn.execute("DELETE FROM milestones WHERE game_id = ?", (game_id,))
        conn.execute("DELETE FROM milestone_groups WHERE game_id = ?", (game_id,))
        conn.executemany(
            "INSERT INTO milestones (game_id, position, name, ra_achievement_id, address, size, value, gates, scenario, kind)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(game_id, i, m["name"], m["ra_achievement_id"], m["address"], m["size"], m["value"], json.dumps(m["gates"]),
              m["scenario"], m.get("kind") or "progression")
             for i, m in enumerate(items)])
        conn.executemany(
            "INSERT INTO milestone_groups (game_id, scenario, position, undetectable) VALUES (?, ?, ?, ?)",
            [(game_id, scenario, i, n) for i, (scenario, n) in enumerate(undetectable.items())])


def load(conn: sqlite3.Connection, game_id: int) -> list[dict]:
    """The stored milestones. Rows without a scenario were saved before scenarios existed, so they also lack the
    in-game gate; they are not returned (the game is rebuilt on its next session)."""
    rows = conn.execute("SELECT * FROM milestones WHERE game_id = ? AND address IS NOT NULL AND scenario IS NOT NULL ORDER BY position", (game_id,))
    return [{"name": r["name"], "ra_achievement_id": r["ra_achievement_id"], "scenario": r["scenario"],
             "kind": r["kind"] or "progression", "address": r["address"], "size": r["size"], "value": r["value"],
             "gates": json.loads(r["gates"] or "[]")} for r in rows]


def legacy(conn: sqlite3.Connection, game_id: int) -> bool:
    """True when the game only has rows from before scenarios existed (`load` ignores them until a rebuild)."""
    return conn.execute("SELECT 1 FROM milestones WHERE game_id = ? AND scenario IS NULL", (game_id,)).fetchone() is not None


def groups(conn: sqlite3.Connection, game_id: int) -> list[dict]:
    rows = conn.execute("SELECT scenario, undetectable FROM milestone_groups WHERE game_id = ? ORDER BY position", (game_id,))
    return [{"scenario": r["scenario"], "undetectable": r["undetectable"]} for r in rows]


def _holds(gate: list | tuple, mem_read: Callable[[int, int], bytes]) -> bool:
    address, size, value, *differ = gate  # a 4th element means "must differ from value"
    return (read_operand(Operand(address, size), mem_read) == value) != bool(differ)


def read(items: list[dict], mem_read: Callable[[int, int], bytes]) -> tuple[str, list[bool]] | None:
    """(scenario in play, which of its milestones are reached right now), or None when no scenario's gates hold
    (a menu, the title screen), since the flags mean something else there."""
    by_scenario: dict[str, list[dict]] = {}
    for m in items:
        by_scenario.setdefault(m["scenario"], []).append(m)
    for scenario, group in by_scenario.items():
        if all(_holds(g, mem_read) for m in group for g in m["gates"]):
            return scenario, [reached(Flag(Operand(m["address"], m["size"]), m["value"]), mem_read) for m in group]
    return None
