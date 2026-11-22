import json
from pathlib import Path

import pytest

from app.collectors.rich_presence import in_game_gates

SCRIPT = """Format:Val
FormatType=VALUE

Display:
?0xS163DA4=0?On the Title Screen
?0xR163DA6=1?Watching a demo
?0xH163DB6=5?Playing as @Char(0xH168A5D) | LV.@Val(0xH168A5B)
Welcome to Raccoon City...
"""


def test_static_branches_become_the_gates_that_say_a_game_is_being_played():
    # title screen is bit S = 0 and a demo is bit R = 1, so play needs S = 1 and R = 0
    assert in_game_gates(SCRIPT) == [(0x163DA4, "S", 1), (0x163DA6, "R", 0)]


def test_a_static_branch_on_a_wider_value_must_differ_from_it():
    script = "Display:\n?0xX1688FC=hFFFFFF00?Sorry, cheaters\n?0xH1=1?Playing @Val(0xH2)\n"
    assert in_game_gates(script) == [(0x1688FC, "X", 0xFFFFFF00, "ne")]


@pytest.mark.parametrize("script", [
    None,
    "",
    "Format:Val\nFormatType=VALUE\n",  # no Display section
    "Display:\n?0xH1=1?Playing @Val(0xH2)\n",  # only dynamic branches: nothing says what is not play
    "Display:\n?0xH1=1_0xH2=2?On a menu\n",  # a static branch with two conditions cannot be negated
    "Display:\n?S0xH1=1S0xH1=2?On a menu\n",  # nor one with alternatives
    "Display:\n?0xH1>3?On a menu\n",  # only equality is understood
    "Display:\n?banana=1?On a menu\n",
])
def test_a_gate_that_cannot_be_derived_is_none(script):
    assert in_game_gates(script) is None


def test_the_real_re2_script_gives_the_hand_written_bits_plus_the_cheat_gates():
    patch = json.loads((Path(__file__).parent / "fixtures" / "re2_patch.json").read_text())
    gates = in_game_gates(patch["RichPresencePatch"])
    assert gates is not None
    assert (0x163DA4, "S", 1) in gates and (0x163DA6, "R", 0) in gates  # title screen and demo, as written by hand
    assert (0x1688FC, "X", 0xFFFFFF00, "ne") in gates and (0x163E09, "T", 0) in gates  # cheat branches
