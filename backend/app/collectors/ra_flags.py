"""Milestone flags from RetroAchievements rules.

A story achievement is written as a transition: "flag was 0, now it is 1" (`d0xN00168a90=0_0xN00168a90=1`).
A transition only fires while it happens, so it cannot tell a player who loaded a later save. The flag
itself can, IF it stays at the new value once the event happened. UNVERIFIED: not tested against a loaded
save or a restarted game (see the project notes); check live before trusting it. This does not run
the rule (no hit counts, resets or pauses); it only picks the flag out of it and reads that flag's value.

Addresses are offsets into the console's main RAM, the same numbers `DolphinMemory.read` takes."""

import re
from collections.abc import Callable
from dataclasses import dataclass

# size letter -> (bytes, byte order); the plain `0x1234` form is 16-bit little-endian
_WIDE = {"": (2, "little"), "H": (1, "little"), "W": (3, "little"), "X": (4, "little"),
         "I": (2, "big"), "J": (3, "big"), "G": (4, "big")}
_BITS = "MNOPQRST"  # bit 0..7 of one byte
_OPERAND = re.compile(r"^0x([G-UWXg-uwx]?)([0-9a-fA-F]+)$")
_GROUP_SEP = re.compile(r"(?<![xX])S")  # `S` splits alternative groups, except as the 0xS bit size
_PAIR_OPS = re.compile(r"^(?P<d>[dp])(?P<op>0x\w+)=(?P<a>\d+)$")
_NOW = re.compile(r"^(?P<op>0x\w+)=(?P<b>\d+)$")


@dataclass(frozen=True)
class Operand:
    address: int
    size: str  # RetroAchievements size letter; "" is 16-bit little-endian


@dataclass(frozen=True)
class Flag:
    operand: Operand
    value: int  # the milestone has happened when the operand holds this value


def parse_operand(text: str) -> Operand:
    m = _OPERAND.match(text)
    if not m:
        raise ValueError(f"operando desconhecido: {text!r}")
    size = m[1].upper()
    if size not in _WIDE and size not in _BITS and size not in "LU":
        raise ValueError(f"tamanho sem suporte: {text!r}")
    return Operand(int(m[2], 16), size)


def read_operand(op: Operand, read: Callable[[int, int], bytes]) -> int:
    if op.size in _WIDE:
        n, order = _WIDE[op.size]
        return int.from_bytes(read(op.address, n), order)
    b = read(op.address, 1)[0]
    if op.size == "L":
        return b & 0xF
    if op.size == "U":
        return b >> 4
    return b >> _BITS.index(op.size) & 1


def milestone_flag(rule: str) -> Flag | None:
    """The flag a rule's event sets, or None when the rule is not a simple "flag becomes X" transition.

    Looks in the core group (before the first alternative) for `d<flag>=a` or `p<flag>=a` followed by
    `<flag>=b`. A bit flag wins over a wider value when there are several (a room number often changes too).
    shortcut: transitions to 0 are skipped, as a cleared flag looks the same as one never set; rules
    built on counters or measured values have no such pair and are skipped as well.
    shortcut: a wide value that steps up (a scenario-end byte 4 -> 5) may change back later, unlike a
    bit flag; it needs a live check, and so does the achievement that uses it."""
    core = _GROUP_SEP.split(rule)[0].split("_")
    found = []
    for before, after in zip(core, core[1:]):
        a, b = _PAIR_OPS.match(before), _NOW.match(after)
        if a and b and a["op"] == b["op"] and int(a["a"]) != int(b["b"]) and int(b["b"]) != 0:
            try:
                found.append(Flag(parse_operand(b["op"]), int(b["b"])))
            except ValueError:
                pass
    return next((f for f in found if f.operand.size and f.operand.size in _BITS), found[0] if found else None)


def reached(flag: Flag, read: Callable[[int, int], bytes]) -> bool:
    return read_operand(flag.operand, read) == flag.value
