"""Rich presence polling. The site is a local server or a fake; nothing real is contacted."""
import json
import threading
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.collectors import presence
from app.collectors import retroachievements as ra
from app.collectors.retroachievements import RAError
from app.db import connect
from app.main import app
from tests.test_dolphin_api import native_dolphin, prepare
from tests.test_launcher import wait_for
from tests.test_ra import KEY, Server

T0 = datetime(2026, 11, 20, 4, 0, 0, tzinfo=timezone.utc)
REAL_FETCH = presence.fetch
REAL_START = presence.start


def line(msg, game=3176, at="2026-11-20 04:22:15"):
    return {"RichPresenceMsg": msg, "RichPresenceMsgDate": at, "LastGameID": game, "Status": "Online"}


@pytest.fixture
def server(monkeypatch):
    s = Server()
    monkeypatch.setattr(ra, "BASE", s.url)
    monkeypatch.setattr(presence, "BASE", s.url)
    monkeypatch.setattr(presence, "fetch", REAL_FETCH)
    yield s
    s.close()


def test_fetch_reads_the_documented_fields_as_utc(server):
    server.reply = (200, json.dumps(line("Leon A | Police Station")).encode(), {})
    p = presence.fetch("rafael", KEY)
    assert p == {"game": 3176, "message": "Leon A | Police Station", "at": datetime(2026, 11, 20, 4, 22, 15, tzinfo=timezone.utc)}
    assert server.requests[0].startswith("/API/API_GetUserSummary.php?") and "u=rafael" in server.requests[0]


@pytest.mark.parametrize("body", [
    {"RichPresenceMsg": None, "RichPresenceMsgDate": None, "LastGameID": 0},  # a user who never played
    {"RichPresenceMsg": 5, "RichPresenceMsgDate": "yesterday", "LastGameID": True},
    {},
])
def test_odd_or_empty_summaries_give_nothing(server, body):
    server.reply = (200, json.dumps(body).encode(), {})
    p = presence.fetch("u", KEY)
    assert presence.accept(p, 3176, T0) is None


def test_errors_never_carry_the_key(server):
    server.reply = (500, b"boom " + KEY.encode(), {})
    with pytest.raises(RAError) as exc:
        presence.fetch("u", KEY)
    assert KEY not in str(exc.value)


def test_accept_only_this_game_and_this_session():
    p = {"game": 3176, "message": "Hall", "at": datetime(2026, 11, 20, 4, 5, tzinfo=timezone.utc)}
    assert presence.accept(p, 3176, T0) == "Hall"
    assert presence.accept({**p, "game": 6870}, 3176, T0) is None  # another game played on RA
    assert presence.accept({**p, "at": datetime(2026, 11, 19, tzinfo=timezone.utc)}, 3176, T0) is None  # from before


def test_poller_stores_only_changes_and_stops_after_the_session(monkeypatch):
    conn = connect()
    conn.execute("INSERT INTO games (key, title, platform, identified) VALUES ('k', 'RE2', 'Nintendo - GameCube', 1)")
    sid = conn.execute("INSERT INTO sessions (game_id, started_at, last_heartbeat) VALUES (1, '2026-11-20T04:00:00Z', '2026-11-20T04:00:00Z')").lastrowid
    conn.commit()
    at = datetime(2026, 11, 20, 4, 10, tzinfo=timezone.utc)
    script = iter([
        {"game": 3176, "message": "On the Title Screen", "at": at},
        {"game": 3176, "message": "On the Title Screen", "at": at},  # unchanged: not stored again
        None,  # the site did not answer this round
        {"game": 6870, "message": "Jill | Uptown", "at": at},  # another game: ignored
        {"game": 3176, "message": "Leon A | Police Station", "at": at},
    ])

    def fake(user, key):
        p = next(script, {"game": 3176, "message": "Leon A | Police Station", "at": at})
        if p is None:
            raise RAError("offline")
        if p["message"] == "Leon A | Police Station":
            conn.execute("UPDATE sessions SET ended_at = '2026-11-20T04:30:00Z' WHERE id = ?", (sid,))
            conn.commit()
        return p

    monkeypatch.setattr(presence, "fetch", fake)
    t = threading.Thread(target=presence._poll, args=(presence.db_path(), 1, sid, "u", KEY, 3176, T0))
    t.start(); t.join(timeout=10)
    assert not t.is_alive()
    rows = conn.execute("SELECT session_id, payload FROM signals WHERE type = 'presence' ORDER BY id").fetchall()
    assert [json.loads(r["payload"])["message"] for r in rows] == ["On the Title Screen", "Leon A | Police Station"]
    assert all(r["session_id"] == sid for r in rows)


def test_play_starts_polling_and_start_needs_key_and_link(tmp_path, monkeypatch):
    client = TestClient(app, base_url="http://127.0.0.1")
    gid = prepare(client, tmp_path)
    out = native_dolphin(client, tmp_path)
    started = []
    monkeypatch.setattr(presence, "start", lambda *a: started.append(a) or True)
    assert client.post(f"/api/games/{gid}/play").status_code == 200
    wait_for(out)
    assert len(started) == 1 and started[0][1] == gid and started[0][3].tzinfo is not None
    # play always calls start; start itself refuses without a key or a link
    conn = connect()
    assert REAL_START(conn, gid, 1, T0) is False
    client.put("/api/ra/settings", json={"user": "u", "key": KEY})
    assert REAL_START(conn, gid, 1, T0) is False  # key but no link


def test_library_shows_the_last_place(tmp_path):
    client = TestClient(app, base_url="http://127.0.0.1")
    gid = prepare(client, tmp_path)
    conn = connect()
    for msg in ("On the Title Screen", "Leon A | Police Station"):
        conn.execute("INSERT INTO signals (game_id, type, payload, timestamp) VALUES (?, 'presence', ?, '2026-11-20T04:00:00Z')",
                     (gid, json.dumps({"ra_id": 3176, "message": msg, "at": "2026-11-20T04:10:00Z"})))
    conn.commit()
    game = next(g for g in client.get("/api/games").json() if g["id"] == gid)
    assert game["presence"] == {"message": "Leon A | Police Station", "at": "2026-11-20T04:10:00Z"}


def _session(conn, ended=None):
    conn.execute("INSERT OR IGNORE INTO games (id, key, title, platform, identified) VALUES (1, 'k', 'RE2', 'Nintendo - GameCube', 1)")
    sid = conn.execute("INSERT INTO sessions (game_id, started_at, last_heartbeat, ended_at) VALUES (1, '2026-11-20T04:00:00Z', '2026-11-20T04:00:00Z', ?)",
                       (ended,)).lastrowid
    conn.commit()
    return sid


def test_the_read_after_the_end_ignores_lines_of_the_next_session(monkeypatch):
    conn = connect()
    sid = _session(conn, ended="2026-11-20T04:30:00Z")
    later = datetime(2026, 11, 20, 4, 31, tzinfo=timezone.utc)  # sent after this session ended
    monkeypatch.setattr(presence, "fetch", lambda u, k: {"game": 3176, "message": "Next session", "at": later})
    presence._poll(presence.db_path(), 1, sid, "u", KEY, 3176, T0)
    assert conn.execute("SELECT COUNT(*) FROM signals WHERE type = 'presence'").fetchone()[0] == 0


def test_a_busy_database_does_not_kill_the_poller(monkeypatch):
    import sqlite3
    conn = connect()
    sid = _session(conn)
    at = datetime(2026, 11, 20, 4, 10, tzinfo=timezone.utc)
    rounds = {"n": 0}

    def fetch(u, k):
        rounds["n"] += 1
        if rounds["n"] == 3:
            conn.execute("UPDATE sessions SET ended_at = '2026-11-20T04:30:00Z' WHERE id = ?", (sid,)); conn.commit()
        return {"game": 3176, "message": "Hall", "at": at}

    real_store = presence.store_signal
    fails = {"n": 1}

    def flaky(*a, **k):
        if fails["n"]:
            fails["n"] -= 1
            raise sqlite3.OperationalError("database is locked")
        return real_store(*a, **k)

    monkeypatch.setattr(presence, "fetch", fetch)
    monkeypatch.setattr(presence, "store_signal", flaky)
    presence._poll(presence.db_path(), 1, sid, "u", KEY, 3176, T0)
    assert conn.execute("SELECT COUNT(*) FROM signals WHERE type = 'presence'").fetchone()[0] == 1  # retried, stored once
