"""Story milestones of a game, taken from its RetroAchievements rules and read from the emulator's RAM."""

import json
import re
import sqlite3
from collections.abc import Callable

from app.collectors.ra_flags import Flag, Operand, core_conditions, milestone_flag, parse_operand, read_operand, reached

_BYTE_EQUALS = re.compile(r"^0xH([0-9a-fA-F]+)=(\d+)$")


def build(patch: dict, prefix: str) -> list[dict]:
    """Milestones from the achievements whose description starts with `prefix` (e.g. "[Leon A]"), in the
    order the server lists them (`patch` has no DisplayOrder; for RE2 that order follows the story). Several achievements can share one flag (the scenario's end); the first one names it.

    A milestone counts only while its `gates` hold: the plain byte checks every selected rule has in
    common, which in Resident Evil 2 is the scenario in play (0 = Leon A).
    shortcut: "common byte check = game mode" is a guess that fits RE2; confirm it on the next game."""
    picked = []
    for a in patch["Achievements"]:
        rule = a.get("MemAddr", "")
        if not str(a.get("Description", "")).startswith(prefix) or not isinstance(rule, str):
            continue
        flag = milestone_flag(rule)
        if flag:
            picked.append((a, flag, set(core_conditions(rule))))
    common = set.intersection(*(c for _, _, c in picked)) if picked else set()
    gates = sorted(m.groups() for c in common if (m := _BYTE_EQUALS.match(c)))
    out, seen = [], set()
    for a, flag, _ in picked:
        key = (flag.operand, flag.value)
        if key in seen:
            continue
        seen.add(key)
        gates_here = [(int(addr, 16), "H", int(v)) for addr, v in gates if int(addr, 16) != flag.operand.address]
        out.append({"ra_achievement_id": a["ID"], "name": a["Title"], "address": flag.operand.address,
                    "size": flag.operand.size, "value": flag.value, "gates": gates_here})
    return out


def save(conn: sqlite3.Connection, game_id: int, items: list[dict]) -> None:
    with conn:
        conn.execute("DELETE FROM milestones WHERE game_id = ?", (game_id,))
        conn.executemany(
            "INSERT INTO milestones (game_id, position, name, ra_achievement_id, address, size, value, gates)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(game_id, i, m["name"], m["ra_achievement_id"], m["address"], m["size"], m["value"], json.dumps(m["gates"]))
             for i, m in enumerate(items)])


def load(conn: sqlite3.Connection, game_id: int) -> list[dict]:
    rows = conn.execute("SELECT * FROM milestones WHERE game_id = ? AND address IS NOT NULL ORDER BY position", (game_id,))
    return [{"name": r["name"], "ra_achievement_id": r["ra_achievement_id"], "address": r["address"], "size": r["size"],
             "value": r["value"], "gates": json.loads(r["gates"] or "[]")} for r in rows]


def read(items: list[dict], mem_read: Callable[[int, int], bytes]) -> list[bool] | None:
    """Which milestones are reached right now, or None when the game is in another mode (a gate fails),
    since those flags mean something else there."""
    for m in items:
        for address, size, value in m["gates"]:
            if read_operand(Operand(address, size), mem_read) != value:
                return None
    return [reached(Flag(Operand(m["address"], m["size"]), m["value"]), mem_read) for m in items]
