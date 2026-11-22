import json
import threading

from app import milestones
from app.collectors import ram_milestones
from app.db import connect
from app.emulators import dolphin
from app.emulators.dolphin_memory import DolphinMemoryError
from tests.test_milestones import PATCH

REAL_START = ram_milestones.start  # the autouse fixture stubs the module's start in every test
IN_GAME = ((0x163DA4, "S", 1), (0x163DA6, "R", 0))

CODE = "GHAE08"
SKIPPED = frozenset({2})  # "G2" in the mini patch


def setup(monkeypatch, patch=PATCH):
    monkeypatch.setattr(ram_milestones, "STORIES", {3176: ("[Leon A]", SKIPPED, IN_GAME)})
    conn = connect()
    conn.execute("INSERT INTO games (key, title, platform, identified) VALUES ('k', 'RE2', 'Nintendo - GameCube', 1)")
    sid = conn.execute("INSERT INTO sessions (game_id, started_at, last_heartbeat) VALUES (1, '2026-11-21T04:00:00Z', '2026-11-21T04:00:00Z')").lastrowid
    conn.commit()
    return conn, sid


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
    milestones.save(conn, 1, milestones.build(PATCH, "[Leon A]", SKIPPED))
    t = threading.Thread(target=ram_milestones._poll, args=(ram_milestones.db_path(), 1, sid, 3176, CODE, None))
    t.start(); t.join(timeout=10)
    assert not t.is_alive()
    return [json.loads(r["payload"]) for r in conn.execute("SELECT payload FROM signals WHERE type = 'milestones' ORDER BY id")]


def test_signals_are_stored_only_when_the_reached_set_changes(monkeypatch):
    conn, sid = setup(monkeypatch)
    mem = FakeMem(conn, sid, [ram(), ram(), ram(marvin=1), ram(marvin=1), ram(marvin=1, end=5)])
    rows = run(conn, sid, mem, monkeypatch)
    assert [r["reached"] for r in rows] == [[], ["Marvin"], ["Marvin", "End"]]
    assert rows[0]["total"] == 2 and rows[0]["ra_id"] == 3176  # G2 was skipped


def test_another_scenario_or_game_stores_nothing(monkeypatch):
    conn, sid = setup(monkeypatch)
    assert run(conn, sid, FakeMem(conn, sid, [ram(marvin=1, scenario=1)] * 3), monkeypatch) == []
    conn2, sid2 = conn, conn.execute("INSERT INTO sessions (game_id, started_at, last_heartbeat) VALUES (1, '2026-11-21T06:00:00Z', '2026-11-21T06:00:00Z')").lastrowid
    conn2.commit()
    assert run(conn2, sid2, FakeMem(conn2, sid2, [ram(marvin=1)] * 3, code=b"GXXE01"), monkeypatch) == []  # Dolphin runs another game


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


def test_ensure_fetches_once_with_dolphins_login_and_ignores_unknown_games(monkeypatch, tmp_path):
    conn, _ = setup(monkeypatch)
    install = dolphin.Install(False, tmp_path, tmp_path)
    fetched = []
    monkeypatch.setattr(ram_milestones, "fetch_patch", lambda *a: fetched.append(a) or PATCH)
    assert ram_milestones.ensure(conn, 1, 3176, install) == []  # Dolphin is not logged in: nothing fetched
    (tmp_path / "RetroAchievements.ini").write_text("[Achievements]\nUsername = rafaleel\nApiToken = abc12345\n")
    items = ram_milestones.ensure(conn, 1, 3176, install)
    assert [m["name"] for m in items] == ["Marvin", "End"] and fetched == [(3176, "rafaleel", "abc12345")]
    ram_milestones.ensure(conn, 1, 3176, install)
    assert len(fetched) == 1  # stored; not fetched again
    assert ram_milestones.ensure(conn, 1, 999, install) == []
    assert REAL_START(conn, 1, 1, 999, CODE, install) is False


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
    (tmp_path / "RetroAchievements.ini").write_text("[Achievements]\nUsername = u\nApiToken = abc12345\n")

    def refused(*a):
        raise ram_milestones.RAError("O RetroAchievements recusou o login do Dolphin (o token pode ter expirado).")

    monkeypatch.setattr(ram_milestones, "fetch_patch", refused)
    assert ram_milestones.ensure(conn, 1, 3176, install) == []
    assert "token" in ram_milestones.PROBLEMS[1]
    monkeypatch.setattr(ram_milestones, "fetch_patch", lambda *a: PATCH)
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
