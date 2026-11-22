from fastapi.testclient import TestClient

from app import milestones
from app.collectors import ram_milestones
from app.collectors.base import store_signal
from app.db import connect
from app.main import app
from tests.test_milestones import PATCH


def make_game(conn, ra_id):
    gid = conn.execute("INSERT INTO games (key, title, platform, identified) VALUES ('k', 'RE2', 'Nintendo - GameCube', 1)").lastrowid
    if ra_id:
        conn.execute("INSERT INTO ra_games (game_id, ra_id) VALUES (?, ?)", (gid, ra_id))
    conn.commit()
    return gid


def test_unsupported_games_and_unknown_ids():
    conn = connect()
    gid = make_game(conn, None)
    c = TestClient(app, base_url="http://127.0.0.1")
    assert c.get(f"/api/games/{gid}/milestones").json() == {"supported": False}
    assert c.get("/api/games/999/milestones").status_code == 404


def test_reached_list_comes_from_the_latest_signal_of_the_linked_game(monkeypatch):
    monkeypatch.setattr(ram_milestones, "STORIES", {3176: ("[Leon A]", frozenset(), ())})
    ram_milestones.PROBLEMS.clear()
    conn = connect()
    gid = make_game(conn, 3176)
    c = TestClient(app, base_url="http://127.0.0.1")
    empty = c.get(f"/api/games/{gid}/milestones").json()
    assert empty["supported"] and empty["total"] == 0 and empty["problem"] is None  # nothing fetched yet
    milestones.save(conn, gid, milestones.build(PATCH, "[Leon A]"))
    store_signal(conn, gid, "milestones", {"ra_id": 999, "reached": ["Marvin"], "total": 3})  # an old link: ignored
    store_signal(conn, gid, "milestones", {"ra_id": 3176, "reached": ["Marvin", "End"], "total": 3})
    ram_milestones.PROBLEMS[gid] = "sem permissão"
    body = c.get(f"/api/games/{gid}/milestones").json()
    assert body["reached"] == 2 and body["total"] == 3 and body["problem"] == "sem permissão"
    assert [(i["name"], i["reached"]) for i in body["items"]] == [("Marvin", True), ("G2", False), ("End", True)]
    assert body["read_at"]
    ram_milestones.PROBLEMS.clear()
