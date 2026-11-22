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


def test_build_orders_dedupes_skips_and_finds_the_scenario_gate():
    items = milestones.build(PATCH, "[Leon A]")
    assert [m["name"] for m in items] == ["Marvin", "G2", "End"]  # Fell is not a plain 0 -> 1 flag; Fast repeats End
    assert items[0] == {"ra_achievement_id": 1, "name": "Marvin", "address": 0x168A90, "size": "N", "value": 1,
                        "gates": [(0x163DB6, "H", 0)]}
    assert milestones.build(PATCH, "[Nobody]") == []


def test_save_load_round_trip_and_replace(conn):
    gid = conn.execute("INSERT INTO games (key, platform, title, identified) VALUES ('re2', 'Nintendo - GameCube', 'RE2', 1)").lastrowid
    items = milestones.build(PATCH, "[Leon A]")
    milestones.save(conn, gid, items)
    milestones.save(conn, gid, items)  # a second sync replaces, it does not duplicate
    loaded = milestones.load(conn, gid)
    assert [m["name"] for m in loaded] == ["Marvin", "G2", "End"]
    assert loaded[0]["gates"] == [[0x163DB6, "H", 0]]


def test_read_reports_reached_flags_only_in_the_right_scenario():
    items = [{"name": "Marvin", "address": 0x10, "size": "N", "value": 1, "gates": [[0x20, "H", 0]]},
             {"name": "End", "address": 0x11, "size": "H", "value": 5, "gates": [[0x20, "H", 0]]}]
    ram = bytearray(0x30)
    ram[0x10], ram[0x11] = 0b10, 4
    rd = lambda a, n: bytes(ram[a:a + n])  # noqa: E731
    assert milestones.read(items, rd) == [True, False]
    ram[0x20] = 1  # another scenario: the flags mean something else
    assert milestones.read(items, rd) is None


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
