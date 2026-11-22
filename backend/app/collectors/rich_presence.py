"""The in-game gate of a game, read from its RetroAchievements rich presence script.

The script's `Display:` section is a list of `?conditions?text` lines; the first line whose conditions hold
is shown. A line whose text has no `@Macro(...)` is a fixed message ("On the Title Screen"), which describes a
state where the RAM flags mean nothing. Playing is every other state, so the gate is the negation of those
conditions, in the `(address, size, value)` form of `milestones` gates (a 4th element `"ne"` means "must differ").
"""
import re

from app.collectors.ra_flags import parse_operand

_BRANCH = re.compile(r"^\?([^?]*)\?(.*)$")
_CONDITION = re.compile(r"^(0x[0-9A-Za-z]+)=(h[0-9A-Fa-f]+|\d+)$")  # one operand equal to a number (`h` = hex)
_BITS = "MNOPQRST"


def in_game_gates(script: str | None) -> list[tuple] | None:
    """The gates that say a game is being played, or None when they cannot be derived: no `Display:` section,
    no fixed message, or a fixed message whose condition is not a single `operand=number`.
    shortcut: only `=` is understood (rich presence also has `!=`, `<`, `>`); extend when a game needs it."""
    gates = set()
    for line in (script or "").partition("Display:")[2].splitlines():
        branch = _BRANCH.match(line.strip())
        if not branch or "@" in branch[2]:  # not a conditional line, or a line that shows game data
            continue
        condition = _CONDITION.match(branch[1])
        if not condition:
            return None
        try:
            operand = parse_operand(condition[1])
        except ValueError:
            return None
        value = int(condition[2][1:], 16) if condition[2][0] == "h" else int(condition[2])
        if operand.size in _BITS and value in (0, 1):
            gates.add((operand.address, operand.size, 1 - value))
        else:
            gates.add((operand.address, operand.size, value, "ne"))
    return sorted(gates) if gates else None
