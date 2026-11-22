import urllib.parse
from pathlib import Path

import pytest

from app import milestones
from app.collectors import retroachievements as ra
from app.emulators import dolphin

TAIL = "_R:0xG001688fc=4294967040_R:0xR00163da7=1_R:0xT00163e09=1"
GATE = "0xR00163da7=0_0xH00163db6=0_"
MARVIN = GATE + "d0xN00168a90=0_0xN00168a90=1_0xW00168a4d=1_0xH00168a51=4" + TAIL
G2 = GATE + "d0xM00168ace=0_0xM00168ace=1_0xW00168a4d=589828" + TAIL
END = GATE + "d0xH0062203f=4_0xH0062203f=5_0xW00168a4d=6" + TAIL
FELL_DOWN = GATE + "d0xT00168a88=1_0xT00168a88=0_0xW00168a4d=589827" + TAIL
CLAIRE = "0xR00163da7=0_0xH00163db6=1_d0xN00168a90=0_0xN00168a90=1" + TAIL


def ach(i, title, desc, rule, order):
    return {"ID": i, "Title": title, "Description": desc, "MemAddr": rule}


PATCH = {"Achievements": [  # the server's order, which `patch` gives without DisplayOrder
    ach(1, "Marvin", "[Leon A] Find Marvin", MARVIN, 1),
    ach(5, "Fell", "[Leon A] Hear Annette", FELL_DOWN, 5),
    ach(2, "G2", "[Leon A] Defeat G-Type 2", G2, 2),
    ach(3, "End", "[Leon A] Complete the scenario", END, 3),
    ach(4, "Fast", "[Leon A] Complete within 2h30", END, 4),  # same flag as "End"
    ach(9, "Claire", "[Claire A] Something", CLAIRE, 9),
]}


KINDS = {1: "progression", 2: "progression", 3: "win_condition", 4: "progression", 5: "progression", 9: "progression"}


def test_build_groups_typed_achievements_by_scenario_and_finds_each_gate():
    items, undetectable = milestones.build(PATCH, KINDS)
    leon = [m for m in items if m["scenario"] == "Leon A"]
    assert [m["name"] for m in leon] == ["Marvin", "G2", "End"]  # Fell is not a plain 0 -> 1 flag; Fast repeats End
    assert leon[0] == {"ra_achievement_id": 1, "name": "Marvin", "scenario": "Leon A", "address": 0x168A90, "size": "N",
                       "value": 1, "gates": [(0x163DB6, "H", 0)]}
    claire = [m for m in items if m["scenario"] == "Claire A"]
    assert [m["name"] for m in claire] == ["Claire"] and claire[0]["gates"] == [(0x163DB6, "H", 1)]
    assert undetectable == {"Leon A": 1, "Claire A": 0}  # Fell cannot be read from the RAM


def test_build_keeps_only_story_types_and_skips_rules_it_cannot_read():
    extra = [ach(7, "Side", "[Leon A] Optional", GATE + "d0xN00168a91=0_0xN00168a91=1" + TAIL, 7),
             ach(8, "Broken", "[Leon A] No rule", None, 8)]
    patch = {"Achievements": PATCH["Achievements"] + extra}
    items, undetectable = milestones.build(patch, {**KINDS, 8: "progression"})  # 7 is untyped, 8 has no rule
    assert "Side" not in [m["name"] for m in items] and "Broken" not in [m["name"] for m in items]
    assert undetectable["Leon A"] == 1
    assert milestones.build(patch, {}) == ([], {})


def test_build_puts_achievements_without_a_tag_in_one_group():
    patch = {"Achievements": [ach(1, "Marvin", "Find Marvin", MARVIN, 1), ach(2, "G2", "Defeat G-Type 2", G2, 2)]}
    items, undetectable = milestones.build(patch, {1: "progression", 2: "progression"})
    assert [m["scenario"] for m in items] == ["", ""] and undetectable == {"": 0}


def test_save_load_and_groups_round_trip_and_replace(conn):
    gid = conn.execute("INSERT INTO games (key, platform, title, identified) VALUES ('re2', 'Nintendo - GameCube', 'RE2', 1)").lastrowid
    items, undetectable = milestones.build(PATCH, KINDS)
    milestones.save(conn, gid, items, undetectable)
    milestones.save(conn, gid, items, undetectable)  # a second sync replaces, it does not duplicate
    loaded = milestones.load(conn, gid)
    assert [(m["scenario"], m["name"]) for m in loaded] == [("Leon A", "Marvin"), ("Leon A", "G2"), ("Leon A", "End"), ("Claire A", "Claire")]
    assert loaded[0]["gates"] == [[0x163DB6, "H", 0]]
    assert milestones.groups(conn, gid) == [{"scenario": "Leon A", "undetectable": 1}, {"scenario": "Claire A", "undetectable": 0}]


def test_load_ignores_rows_saved_before_scenarios_existed(conn):
    gid = conn.execute("INSERT INTO games (key, platform, title, identified) VALUES ('re2', 'Nintendo - GameCube', 'RE2', 1)").lastrowid
    conn.execute("INSERT INTO milestones (game_id, position, name, address, size, value, gates) VALUES (?, 0, 'Old', 16, 'N', 1, '[]')", (gid,))
    conn.commit()
    assert milestones.load(conn, gid) == []  # those rows have no in-game gate; they are rebuilt, never read as they are


def test_read_reports_the_scenario_in_play_and_its_flags():
    items = [{"scenario": "Leon A", "name": "Marvin", "address": 0x10, "size": "N", "value": 1, "gates": [[0x20, "H", 0]]},
             {"scenario": "Leon A", "name": "End", "address": 0x11, "size": "H", "value": 5, "gates": [[0x20, "H", 0]]},
             {"scenario": "Claire A", "name": "Marvin", "address": 0x10, "size": "N", "value": 1, "gates": [[0x20, "H", 1]]}]
    ram = bytearray(0x40)
    ram[0x10], ram[0x11] = 0b10, 4
    rd = lambda a, n: bytes(ram[a:a + n])  # noqa: E731
    assert milestones.read(items, rd) == ("Leon A", [True, False])
    ram[0x20] = 1
    assert milestones.read(items, rd) == ("Claire A", [True])
    ram[0x20] = 2  # no scenario in play (a menu, the title screen): the flags mean something else
    assert milestones.read(items, rd) is None


def test_read_honors_gates_that_must_differ():
    items = [{"scenario": "", "name": "Marvin", "address": 0x10, "size": "N", "value": 1, "gates": [[0x30, "H", 5, "ne"]]}]
    ram = bytearray(0x40)
    ram[0x10], ram[0x30] = 0b10, 5
    rd = lambda a, n: bytes(ram[a:a + n])  # noqa: E731
    assert milestones.read(items, rd) is None
    ram[0x30] = 4
    assert milestones.read(items, rd) == ("", [True])


def test_fetch_patch_posts_the_token_in_the_body_and_checks_the_answer(monkeypatch):
    seen = {}

    def fake(url, timeout=15.0, data=None):
        seen.update(url=url, data=urllib.parse.parse_qs(data.decode()))
        return {"Success": True, "PatchData": {"Achievements": []}}

    monkeypatch.setattr(ra, "get_json", fake)
    assert ra.fetch_patch(3176, "rafaleel", "tok3n1234") == {"Achievements": []}
    assert "tok3n1234" not in seen["url"] and seen["data"] == {"r": ["patch"], "g": ["3176"], "u": ["rafaleel"], "t": ["tok3n1234"]}
    monkeypatch.setattr(ra, "get_json", lambda *a, **k: {"Success": False, "Error": "tok3n1234 expired"})
    with pytest.raises(ra.RAError) as err:
        ra.fetch_patch(3176, "rafaleel", "tok3n1234")
    assert "tok3n1234" not in str(err.value)


def test_ra_login_reads_dolphins_ini(tmp_path):
    install = dolphin.Install(False, tmp_path, tmp_path)
    assert dolphin.ra_login(install) is None
    (tmp_path / "RetroAchievements.ini").write_text("[Achievements]\nUsername = rafaleel\nApiToken = abc12345\n")
    assert dolphin.ra_login(install) == ("rafaleel", "abc12345")
    (tmp_path / "RetroAchievements.ini").write_text("[Achievements]\nUsername = rafaleel\n")
    assert dolphin.ra_login(install) is None


def test_an_expired_dolphin_token_points_at_dolphins_login_not_the_api_key(monkeypatch):
    def refused(*a, **k):
        raise ra.RAError("O RetroAchievements recusou o usuário ou a chave de API. Confira os dois em Configurações.")

    monkeypatch.setattr(ra, "get_json", refused)
    with pytest.raises(ra.RAError, match="Dolphin") as err:
        ra.fetch_patch(3176, "rafaleel", "tok3n1234")
    assert "chave de API" not in str(err.value)


def test_a_scenario_with_one_readable_rule_takes_only_the_scenario_byte_as_its_gate():
    room = "0xH00170000=7_"  # a room check inside the one rule: not a scenario, it must not become a gate
    claire = ach(9, "Claire", "[Claire A] Something", "0xR00163da7=0_0xH00163db6=1_" + room + "d0xN00168a90=0_0xN00168a90=1" + TAIL, 9)
    patch = {"Achievements": [PATCH["Achievements"][0], PATCH["Achievements"][2], claire]}  # Marvin and G2 share the scenario byte
    items, _ = milestones.build(patch, KINDS)
    assert [m["gates"] for m in items if m["scenario"] == "Claire A"] == [[(0x163DB6, "H", 1)]]


def test_a_lone_rule_with_no_other_scenario_to_say_which_byte_is_the_scenario_is_left_out():
    patch = {"Achievements": [ach(1, "Marvin", "[Leon A] Find Marvin", MARVIN, 1)]}
    assert milestones.build(patch, KINDS) == ([], {"Leon A": 1})  # its conditions could be a room: no safe gate
