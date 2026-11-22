import json
import threading

from app import milestones
from app.collectors import ra_store, ram_milestones
from app.db import connect
from app.emulators import dolphin
from app.emulators.dolphin_memory import DolphinMemoryError
from tests.test_milestones import KINDS, PATCH

REAL_START = ram_milestones.start  # the autouse fixture stubs the module's start in every test

CODE = "GHAE08"
RP = ("Display:\n?0xS163DA4=0?On the Title Screen\n?0xR163DA6=1?Watching a demo\n"
      "?0xH163DB6=5?Playing as @Char(0xH168A5D)\nWelcome to Raccoon City...\n")
FULL = {**PATCH, "RichPresencePatch": RP}
IN_GAME = [(0x163DA4, "S", 1), (0x163DA6, "R", 0)]  # what RP says: not the title screen, not a demo


def catalog(patch=PATCH, kinds=KINDS):
    return [{"id": a["ID"], "title": a["Title"], "description": a["Description"], "points": 5, "type": kinds.get(a["ID"], "")}
            for a in patch["Achievements"]]


def setup(monkeypatch, patch=PATCH, kinds=KINDS):
    conn = connect()
    conn.execute("INSERT INTO games (key, title, platform, identified) VALUES ('k', 'RE2', 'Nintendo - GameCube', 1)")
    sid = conn.execute("INSERT INTO sessions (game_id, started_at, last_heartbeat) VALUES (1, '2026-11-21T04:00:00Z', '2026-11-21T04:00:00Z')").lastrowid
    ra_store.save_catalog(conn, 3176, catalog(patch, kinds))
    conn.commit()
    return conn, sid


def stored(conn):
    """The rows ensure() would store for FULL, so a poller test needs no login."""
    items, undetectable = milestones.build(FULL, KINDS)
    milestones.save(conn, 1, [{**m, "gates": [*m["gates"], *IN_GAME]} for m in items], undetectable)


class FakeMem:
    """A RAM image that changes round by round; ends the session after the last image."""

    def __init__(self, conn, sid, images, code=CODE.encode()):
        self.conn, self.sid, self.images, self.code, self.round = conn, sid, list(images), code, 0

    def read(self, addr, n):
        if addr == 0:
            return self.code[:n]
        img = self.images[min(self.round, len(self.images) - 1)]
        return bytes(img[addr:addr + n])

    def close(self):
        pass

    def tick(self):
        self.round += 1
        if self.round >= len(self.images):
            self.conn.execute("UPDATE sessions SET ended_at = '2026-11-21T05:00:00Z' WHERE id = ?", (self.sid,))
            self.conn.commit()


def ram(marvin=0, end=0, scenario=0, playing=True):
    img = bytearray(0x700000)
    img[0x163DA4] = 0x40 if playing else 0  # bit 6 set: not on the title screen
    img[0x163DB6] = scenario
    img[0x168A90] = marvin << 1
    img[0x62203F] = end
    return img


def run(conn, sid, mem, monkeypatch, attach=None):
    real_read = mem.read

    def read(a, n):
        if a == 0:
            mem.tick()  # one tick per round, on the game id check
        return real_read(a, n)

    mem.read = read
    monkeypatch.setattr(ram_milestones.DolphinMemory, "attach", attach or (lambda: mem))
    stored(conn)
    t = threading.Thread(target=ram_milestones._poll, args=(ram_milestones.db_path(), 1, sid, 3176, CODE, None))
    t.start(); t.join(timeout=10)
    assert not t.is_alive()
    return [json.loads(r["payload"]) for r in conn.execute("SELECT payload FROM signals WHERE type = 'milestones' ORDER BY id")]


def test_signals_are_stored_only_when_the_reached_set_changes(monkeypatch):
    conn, sid = setup(monkeypatch)
    mem = FakeMem(conn, sid, [ram(), ram(), ram(marvin=1), ram(marvin=1), ram(marvin=1, end=5)])
    rows = run(conn, sid, mem, monkeypatch)
    assert [r["reached"] for r in rows] == [[], ["Marvin"], ["Marvin", "End"]]
    assert rows[0]["total"] == 3 and rows[0]["ra_id"] == 3176 and rows[0]["scenario"] == "Leon A"  # Marvin, G2, End


def test_the_scenario_in_play_names_the_signal_and_an_unknown_one_stores_nothing(monkeypatch):
    conn, sid = setup(monkeypatch)
    rows = run(conn, sid, FakeMem(conn, sid, [ram(marvin=1, scenario=1)] * 3), monkeypatch)
    assert rows and rows[0]["scenario"] == "Claire A" and rows[0]["reached"] == ["Claire"]
    sid2 = conn.execute("INSERT INTO sessions (game_id, started_at, last_heartbeat) VALUES (1, '2026-11-21T06:00:00Z', '2026-11-21T06:00:00Z')").lastrowid
    conn.commit()
    conn.execute("DELETE FROM signals")
    conn.commit()
    assert run(conn, sid2, FakeMem(conn, sid2, [ram(marvin=1, scenario=2)] * 3), monkeypatch) == []  # no scenario's gates hold
    sid3 = conn.execute("INSERT INTO sessions (game_id, started_at, last_heartbeat) VALUES (1, '2026-11-21T07:00:00Z', '2026-11-21T07:00:00Z')").lastrowid
    conn.commit()
    assert run(conn, sid3, FakeMem(conn, sid3, [ram(marvin=1)] * 3, code=b"GXXE01"), monkeypatch) == []  # Dolphin runs another game


def test_dolphin_closing_and_reopening_reattaches(monkeypatch):
    conn, sid = setup(monkeypatch)
    mem = FakeMem(conn, sid, [ram(marvin=1)] * 4)
    calls = []
    real_read = mem.read

    def read(a, n):
        calls.append(a)
        if len(calls) == 3:
            raise OSError("the process is gone")
        return real_read(a, n)

    mem.read = read
    attached = []

    def attach():
        attached.append(1)
        if len(attached) == 2:
            raise DolphinMemoryError("no RAM")  # reopened, but not readable yet: must not end the poller
        return mem

    rows = run(conn, sid, mem, monkeypatch, attach)
    assert len(attached) >= 2 and rows and rows[0]["reached"] == ["Marvin"]


def logged_in(tmp_path):
    (tmp_path / "RetroAchievements.ini").write_text("[Achievements]\nUsername = rafaleel\nApiToken = abc12345\n")
    return dolphin.Install(False, tmp_path, tmp_path)


def test_ensure_builds_once_with_dolphins_login_and_stores_the_in_game_gate(monkeypatch, tmp_path):
    conn, _ = setup(monkeypatch)
    install = dolphin.Install(False, tmp_path, tmp_path)
    fetched = []
    monkeypatch.setattr(ram_milestones, "fetch_patch", lambda *a: fetched.append(a) or FULL)
    assert ram_milestones.ensure(conn, 1, 3176, install) == []  # Dolphin is not logged in: nothing fetched
    assert fetched == []
    items = ram_milestones.ensure(conn, 1, 3176, logged_in(tmp_path))
    assert [(m["scenario"], m["name"]) for m in items] == [("Leon A", "Marvin"), ("Leon A", "G2"), ("Leon A", "End"), ("Claire A", "Claire")]
    assert fetched == [(3176, "rafaleel", "abc12345")]
    assert [0x163DA4, "S", 1] in items[0]["gates"] and [0x163DA6, "R", 0] in items[0]["gates"]
    ram_milestones.ensure(conn, 1, 3176, logged_in(tmp_path))
    assert len(fetched) == 1  # stored; not fetched again
    assert REAL_START(conn, 1, 1, None, CODE, install) is False  # no RetroAchievements link
    assert REAL_START(conn, 1, 1, 3176, None, install) is False  # no game code


def test_a_game_that_cannot_be_built_stores_nothing_and_says_why(monkeypatch, tmp_path):
    no_gate = {**PATCH, "RichPresencePatch": "Display:\n?0xH1=1?Playing @Val(0xH2)\n"}
    cases = [  # (catalog kinds, patch, text of the reason)
        (None, FULL, "Sincronize"),  # achievements never synced: no catalog
        ({}, FULL, "não tem conquistas de progressão"),
        (KINDS, no_gate, "rich presence"),
        ({5: "progression"}, {"Achievements": [PATCH["Achievements"][1]], "RichPresencePatch": RP}, "lida da memória"),  # only Fell, no plain flag
    ]
    for n, (kinds, patch, reason) in enumerate(cases):
        monkeypatch.setenv("ARGOS_DB", str(tmp_path / f"{n}.db"))
        conn, _ = setup(monkeypatch, PATCH, {} if kinds is None else kinds)
        if kinds is None:
            conn.execute("DELETE FROM ra_achievements")
            conn.commit()
        monkeypatch.setattr(ram_milestones, "fetch_patch", lambda *a, p=patch: p)
        ram_milestones.PROBLEMS.clear()
        assert ram_milestones.ensure(conn, 1, 3176, logged_in(tmp_path)) == []
        assert reason in ram_milestones.PROBLEMS[1]
        assert conn.execute("SELECT COUNT(*) FROM milestones").fetchone()[0] == 0


def test_rows_saved_before_scenarios_existed_are_rebuilt(monkeypatch, tmp_path):
    conn, _ = setup(monkeypatch)
    conn.execute("INSERT INTO milestones (game_id, position, name, address, size, value, gates) VALUES (1, 0, 'Old', 16, 'N', 1, '[]')")
    conn.commit()
    monkeypatch.setattr(ram_milestones, "fetch_patch", lambda *a: FULL)
    assert [m["name"] for m in ram_milestones.ensure(conn, 1, 3176, logged_in(tmp_path))][0] == "Marvin"
    assert conn.execute("SELECT COUNT(*) FROM milestones WHERE name = 'Old'").fetchone()[0] == 0


def test_the_title_screen_does_not_store_an_empty_set_after_progress(monkeypatch):
    conn, sid = setup(monkeypatch)
    # Marvin reached, then the player quits to the title: the id is still there, the rest is zeros
    mem = FakeMem(conn, sid, [ram(), ram(), ram(marvin=1), ram(marvin=1), ram(playing=False), ram(playing=False)])  # the first image is skipped by the tick
    rows = run(conn, sid, mem, monkeypatch)
    assert [r["reached"] for r in rows] == [[], ["Marvin"]]  # nothing after the quit; no false regression


def test_problems_are_recorded_and_cleared(monkeypatch, tmp_path):
    conn, sid = setup(monkeypatch)
    ram_milestones.PROBLEMS.clear()
    install = dolphin.Install(False, tmp_path, tmp_path)
    assert ram_milestones.ensure(conn, 1, 3176, install) == []
    assert "não está logado" in ram_milestones.PROBLEMS[1]
    install = logged_in(tmp_path)

    def refused(*a):
        raise ram_milestones.RAError("O RetroAchievements recusou o login do Dolphin (o token pode ter expirado).")

    monkeypatch.setattr(ram_milestones, "fetch_patch", refused)
    assert ram_milestones.ensure(conn, 1, 3176, install) == []
    assert "token" in ram_milestones.PROBLEMS[1]
    monkeypatch.setattr(ram_milestones, "fetch_patch", lambda *a: FULL)
    assert ram_milestones.ensure(conn, 1, 3176, install)
    assert 1 not in ram_milestones.PROBLEMS  # fetched fine: the problem is gone
    # unreadable Dolphin memory is recorded by the poller and cleared by the next good read
    mem = FakeMem(conn, sid, [ram(playing=False)] * 3)  # attach works, the title screen is up: the old error must go
    tries = []

    def attach():
        tries.append(1)
        if len(tries) == 1:
            raise DolphinMemoryError("sem os 24 MB")
        return mem

    run(conn, sid, mem, monkeypatch, attach)
    assert 1 not in ram_milestones.PROBLEMS and len(tries) >= 2


def test_another_game_open_is_reported(monkeypatch):
    conn, sid = setup(monkeypatch)
    ram_milestones.PROBLEMS.clear()
    mem = FakeMem(conn, sid, [ram(marvin=1)] * 3, code=b"GXXE01")
    assert run(conn, sid, mem, monkeypatch) == []  # nothing is read from another game's RAM
    assert "GXXE01" in ram_milestones.PROBLEMS[1]
    ram_milestones.PROBLEMS.clear()


def test_an_address_outside_the_games_ram_is_reported_and_stops_the_poller(monkeypatch):
    conn, sid = setup(monkeypatch)
    ram_milestones.PROBLEMS.clear()
    mem = FakeMem(conn, sid, [ram(marvin=1)] * 3)
    real_read = mem.read

    def read(a, n):  # what DolphinMemory.read does for an address past its 24 MB
        if a >= 0x1800000:
            raise ValueError("fora da RAM do jogo")
        return real_read(a, n)

    mem.read = read
    items, undetectable = milestones.build(FULL, KINDS)
    gate = [(0x1800000, "H", 1)]  # a rich presence gate on memory this reader cannot see
    milestones.save(conn, 1, [{**m, "gates": [*m["gates"], *gate]} for m in items], undetectable)
    monkeypatch.setattr(ram_milestones.DolphinMemory, "attach", lambda: mem)
    t = threading.Thread(target=ram_milestones._poll, args=(ram_milestones.db_path(), 1, sid, 3176, CODE, None))
    t.start(); t.join(timeout=10)
    assert not t.is_alive() and "fora da RAM" in ram_milestones.PROBLEMS[1]
    ram_milestones.PROBLEMS.clear()
