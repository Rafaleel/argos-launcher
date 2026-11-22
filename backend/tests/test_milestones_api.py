from fastapi.testclient import TestClient

from app import milestones
from app.collectors import ram_milestones
from app.collectors.base import store_signal
from app.db import connect
from app.main import app
from tests.test_milestones import KINDS, PATCH


def make_game(conn, ra_id):
    gid = conn.execute("INSERT INTO games (key, title, platform, identified) VALUES (?, 'RE2', 'Nintendo - GameCube', 1)", (f"k{ra_id}",)).lastrowid
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
    linked = make_game(conn, 3176)
    ram_milestones.PROBLEMS.clear()
    assert c.get(f"/api/games/{linked}/milestones").json() == {"supported": False}  # linked, nothing built, nothing to say yet
    ram_milestones.PROBLEMS[linked] = "Sincronize as conquistas"
    body = c.get(f"/api/games/{linked}/milestones").json()
    assert body["supported"] and body["total"] == 0 and body["groups"] == [] and body["problem"] == "Sincronize as conquistas"
    ram_milestones.PROBLEMS.clear()


def test_groups_and_the_active_scenario_come_from_the_latest_signal_of_the_linked_game():
    ram_milestones.PROBLEMS.clear()
    conn = connect()
    gid = make_game(conn, 3176)
    c = TestClient(app, base_url="http://127.0.0.1")
    items, undetectable = milestones.build(PATCH, KINDS)
    milestones.save(conn, gid, items, undetectable)
    store_signal(conn, gid, "milestones", {"ra_id": 999, "scenario": "Claire A", "reached": ["Claire"], "total": 1})  # an old link: ignored
    nothing = c.get(f"/api/games/{gid}/milestones").json()
    assert nothing["active"] is None and nothing["read_at"] is None and nothing["total"] == 3  # no reading yet: the first group is shown
    store_signal(conn, gid, "milestones", {"ra_id": 3176, "scenario": "Leon A", "reached": ["Marvin", "End"], "total": 3})
    ram_milestones.PROBLEMS[gid] = "sem permissão"
    body = c.get(f"/api/games/{gid}/milestones").json()
    assert body["supported"] and body["active"] == "Leon A" and body["problem"] == "sem permissão" and body["read_at"]
    assert body["reached"] == 2 and body["total"] == 3  # the active scenario, in the keys the page already reads
    assert [(i["name"], i["reached"]) for i in body["items"]] == [("Marvin", True), ("G2", False), ("End", True)]
    leon, claire = body["groups"]
    assert (leon["scenario"], leon["total"], leon["reached"], leon["undetectable"]) == ("Leon A", 3, 2, 1)
    assert (claire["scenario"], claire["total"], claire["reached"], claire["undetectable"]) == ("Claire A", 1, None, 0)  # not read now
    ram_milestones.PROBLEMS.clear()


def test_a_game_with_rows_from_before_scenarios_says_they_will_be_rebuilt():
    ram_milestones.PROBLEMS.clear()
    conn = connect()
    gid = make_game(conn, 3176)
    conn.execute("INSERT INTO milestones (game_id, position, name, address, size, value, gates) VALUES (?, 0, 'Old', 16, 'N', 1, '[]')", (gid,))
    conn.commit()
    body = TestClient(app, base_url="http://127.0.0.1").get(f"/api/games/{gid}/milestones").json()
    assert body["supported"] and body["total"] == 0 and "remontados" in body["problem"]  # the tab stays, with the reason


def test_relinking_to_another_set_drops_the_milestones_of_the_old_one():
    from app.collectors import ra_store
    conn = connect()
    gid = make_game(conn, 3176)
    items, undetectable = milestones.build(PATCH, KINDS)
    milestones.save(conn, gid, items, undetectable)
    ra_store.set_ra_id(conn, gid, 3176)  # the same link again: nothing changes
    assert milestones.load(conn, gid)
    ra_store.set_ra_id(conn, gid, 999)
    assert milestones.load(conn, gid) == [] and milestones.groups(conn, gid) == []


def test_before_any_reading_the_page_shows_the_first_scenario_that_has_milestones():
    ram_milestones.PROBLEMS.clear()
    conn = connect()
    gid = make_game(conn, 3176)
    items, _ = milestones.build(PATCH, KINDS)
    milestones.save(conn, gid, [m for m in items if m["scenario"] == "Claire A"], {"Leon A": 3, "Claire A": 0})  # Leon A has none readable
    body = TestClient(app, base_url="http://127.0.0.1").get(f"/api/games/{gid}/milestones").json()
    assert body["active"] is None and body["total"] == 1 and [i["name"] for i in body["items"]] == ["Claire"]
