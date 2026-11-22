"""Automatic milestones against the real RE2 set (fixtures taken once from RetroAchievements)."""
import json
from pathlib import Path

import pytest

from app import milestones
from app.collectors import ra_store, ram_milestones
from app.db import connect
from app.emulators import dolphin

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def re2(monkeypatch, tmp_path):
    patch = json.loads((FIXTURES / "re2_patch.json").read_text())
    conn = connect()
    conn.execute("INSERT INTO games (key, title, platform, identified) VALUES ('re2', 'RE2', 'Nintendo - GameCube', 1)")
    ra_store.save_catalog(conn, 3176, [{"id": a["ID"], "title": a["Title"], "description": a["Description"], "points": a["Points"],
                                        "type": a.get("Type") or ""} for a in patch["Achievements"]])
    conn.commit()
    (tmp_path / "RetroAchievements.ini").write_text("[Achievements]\nUsername = u\nApiToken = abc12345\n")
    monkeypatch.setattr(ram_milestones, "fetch_patch", lambda *a: patch)
    return ram_milestones.ensure(conn, 1, 3176, dolphin.Install(False, tmp_path, tmp_path))


def ram(**bits):
    img = bytearray(0x700000)
    img[0x163DA4] = 0x40  # bit S: not on the title screen
    for address, value in bits.items():
        img[int(address[1:], 16)] = value
    return lambda a, n: bytes(img[a:a + n])


def test_leon_a_has_every_milestone_the_hand_written_story_had(re2):
    leon = {m["ra_achievement_id"] for m in re2 if m["scenario"] == "Leon A"}
    assert set(json.loads((FIXTURES / "re2_leon_a_ids.json").read_text())) <= leon


def test_each_scenario_is_a_group_and_every_milestone_carries_the_in_game_gate(re2):
    assert {m["scenario"] for m in re2} >= {"Leon A", "Claire A"}
    for m in re2:
        assert [0x163DA4, "S", 1] in m["gates"] and [0x163DA6, "R", 0] in m["gates"]


def test_the_derived_gate_is_closed_on_the_title_screen_a_demo_and_cheats_and_open_in_play(re2):
    assert milestones.read(re2, ram())[0] == "Leon A"  # in play, scenario byte 0
    assert milestones.read(re2, ram(a163DA4=0)) is None  # title screen
    assert milestones.read(re2, ram(a163DA6=0x20)) is None  # a demo (bit R)
    assert milestones.read(re2, ram(a163E09=0x80)) is None  # special weapons (bit T)
