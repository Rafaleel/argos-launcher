from fastapi.testclient import TestClient

from app.collectors import ra_store
from app.collectors import retroachievements as ra
from app.collectors.base import store_signal
from app.db import connect
from app.main import app

SET = {"ID": 3176, "Title": "RE2", "ConsoleName": "GameCube", "NumAchievements": 3, "NumAwardedToUser": 1, "NumAwardedToUserHardcore": 0,
       "Achievements": {
           "2": {"ID": 2, "Title": "Second", "Description": "Do the second thing", "Points": 5, "Type": "", "DisplayOrder": 1},
           "1": {"ID": 1, "Title": "First", "Description": "Do the first thing", "Points": 1, "Type": "progression", "DisplayOrder": 0,
                 "DateEarned": "2026-11-22 02:01:41"},
           "3": {"ID": 3, "Title": "Odd", "Description": None, "Points": "x", "DisplayOrder": "oops"}}}


def test_parse_progress_lists_the_whole_set_in_the_sites_order_and_defensively():
    payload = ra.parse_progress(SET, 3176)
    assert [(a["id"], a["title"]) for a in payload["catalog"]] == [(1, "First"), (3, "Odd"), (2, "Second")]  # a bad order counts as 0; ties keep the site's order
    assert payload["catalog"][1] == {"id": 3, "title": "Odd", "description": "", "points": 0, "type": ""}
    assert payload["catalog"][0]["type"] == "progression"


def test_a_sync_stores_the_catalog_apart_and_the_endpoint_merges_what_was_earned(monkeypatch):
    conn = connect()
    gid = conn.execute("INSERT INTO games (key, title, platform, identified) VALUES ('k', 'RE2', 'Nintendo - GameCube', 1)").lastrowid
    conn.execute("INSERT INTO ra_games (game_id, ra_id) VALUES (?, 3176)", (gid,))
    ra_store.set_credentials(conn, "u", "k" * 32)
    conn.commit()
    monkeypatch.setattr(ra, "get_json", lambda url, **k: SET)
    payload = ra.RetroAchievementsCollector().collect(conn, gid)
    assert "catalog" not in payload  # kept out of the signal
    assert "catalog" not in conn.execute("SELECT payload FROM signals WHERE type = 'achievements'").fetchone()["payload"]
    c = TestClient(app, base_url="http://127.0.0.1")
    body = c.get(f"/api/games/{gid}/achievements").json()
    assert body["ra_id"] == 3176
    assert [(a["title"], a["earned"], a["points"]) for a in body["items"]] == [("First", True, 1), ("Odd", False, 0), ("Second", False, 5)]
    assert body["items"][0]["at"] == "2026-11-22 02:01:41" and body["items"][0]["description"] == "Do the first thing"
    ra.RetroAchievementsCollector().collect(conn, gid)  # a second sync replaces, it does not duplicate
    assert len(c.get(f"/api/games/{gid}/achievements").json()["items"]) == 3


def test_unlinked_and_unknown_games():
    conn = connect()
    gid = conn.execute("INSERT INTO games (key, title, platform, identified) VALUES ('k', 'X', 'p', 1)").lastrowid
    conn.commit()
    c = TestClient(app, base_url="http://127.0.0.1")
    assert c.get(f"/api/games/{gid}/achievements").json() == {"ra_id": None, "items": []}
    assert c.get("/api/games/999/achievements").status_code == 404
