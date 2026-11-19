import json
import os
import stat
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient

from app.collectors import retroachievements as ra
from app.collectors.base import latest_signal, store_signal
from app.collectors.retroachievements import RAError, parse_game_ref, parse_progress, summary
from app.main import app
from tests.test_dolphin_api import GC, prepare

KEY = "SECRETKEY123"

# Shaped after https://api-docs.retroachievements.org/v1/get-game-info-and-user-progress.html
PASCAL = {
    "ID": 3176, "Title": "Resident Evil 2", "ConsoleID": 16, "ConsoleName": "GameCube",
    "NumAchievements": 4, "NumAwardedToUser": 2, "NumAwardedToUserHardcore": 1,
    "Achievements": {
        "1": {"ID": 1, "Title": "A", "Points": 5, "DateEarned": "2026-01-02 10:00:00", "DateEarnedHardcore": "2026-01-02 10:00:00"},
        "2": {"ID": 2, "Title": "B", "Points": 10, "DateEarned": "2026-01-03 11:00:00"},
        "3": {"ID": 3, "Title": "C", "Points": 25},
        "4": {"ID": 4, "Title": "D", "Points": 50},
    },
}
CAMEL = {
    "id": 3176, "title": "RE2", "consoleName": "GameCube", "numAchievements": 3, "numAwardedToUser": 1,
    "achievements": [{"id": 1, "points": 5, "dateEarned": "2026-01-02"}, {"id": 2, "points": 5}, {"id": 3, "points": 5}],
}


def test_parser_reads_the_documented_shape():
    p = parse_progress(PASCAL, 3176)
    assert (p["total"], p["earned"], p["earned_hardcore"]) == (4, 2, 1)
    assert (p["points_total"], p["points_earned"]) == (90, 15)
    assert [a["id"] for a in p["earned_list"]] == [1, 2] and p["earned_list"][0]["hardcore"] and not p["earned_list"][1]["hardcore"]
    assert p["title"] == "Resident Evil 2" and p["console"] == "GameCube" and p["ra_id"] == 3176


def test_parser_accepts_camel_case_and_a_list_of_achievements():
    p = parse_progress(CAMEL, 3176)
    assert (p["total"], p["earned"]) == (3, 1) and p["earned_list"][0]["at"] == "2026-01-02"


def test_parser_derives_counts_when_the_totals_are_missing():
    only_items = {"Achievements": {"1": {"ID": 1, "DateEarned": "x"}, "2": {"ID": 2}}}
    p = parse_progress(only_items, 1)
    assert (p["total"], p["earned"], p["earned_hardcore"]) == (2, 1, 0)


@pytest.mark.parametrize("bad", [[], "text", None, {}, {"unrelated": 1}, {"Error": "no access"}, {"message": "Unauthenticated."}])
def test_parser_rejects_unexpected_shapes_with_a_readable_error(bad):
    with pytest.raises(RAError) as exc:
        parse_progress(bad, 1)
    assert str(exc.value)  # something the user can read


def test_unexpected_shape_error_names_the_keys_it_saw():
    with pytest.raises(RAError, match="Chaves: .*Foo"):
        parse_progress({"Foo": 1, "Bar": 2}, 1)


def test_summary_percent_and_zero_achievements():
    assert summary({"total": 4, "earned": 1, "earned_hardcore": 0, "title": "x", "synced_at": "t"})["percent"] == 25.0
    assert summary({"total": 0, "earned": 0})["percent"] is None  # a game with no set: no division by zero
    assert summary({"total": 2, "earned": 5})["percent"] == 100.0  # never above 100
    assert summary(None) is None


@pytest.mark.parametrize("text,expected", [
    ("3176", 3176), (" 3176 ", 3176), ("https://retroachievements.org/game/3176", 3176),
    ("retroachievements.org/game/6870/", 6870), ("", None), (None, None), ("   ", None),
])
def test_game_ref_accepts_ids_and_page_urls(text, expected):
    assert parse_game_ref(text) == expected


@pytest.mark.parametrize("text", ["abc", "0", "-5", "12.5", "https://example.com/game/12", "1234567890123", "3176; DROP"])
def test_game_ref_rejects_everything_else(text):
    with pytest.raises(ValueError):
        parse_game_ref(text)


# ---------------------------------------------------------------- HTTP client against a real local server


class Server:
    def __init__(self):
        outer = self
        self.requests, self.reply = [], (200, b"{}", {})

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.requests.append(self.path)
                code, body, headers = outer.reply() if callable(outer.reply) else outer.reply
                self.send_response(code)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/API/"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()


@pytest.fixture
def server(monkeypatch):
    s = Server()
    monkeypatch.setattr(ra, "BASE", s.url)
    yield s
    s.close()


def test_fetch_builds_the_documented_query_and_parses(server):
    server.reply = (200, json.dumps(PASCAL).encode(), {})
    p = ra.fetch_progress("rafael", KEY, 3176)
    assert p["earned"] == 2
    path = server.requests[0]
    assert path.startswith("/API/API_GetGameInfoAndUserProgress.php?")
    assert "y=" + KEY in path and "u=rafael" in path and "g=3176" in path


def test_fetch_url_encodes_odd_user_names(server):
    server.reply = (200, json.dumps(PASCAL).encode(), {})
    ra.fetch_progress("a b&c=d", KEY, 1)
    assert "u=a+b%26c%3Dd" in server.requests[0]  # cannot smuggle another parameter


@pytest.mark.parametrize("code,fragment", [(401, "recusou"), (403, "recusou"), (404, "não achou"), (429, "Limite"), (500, "erro 500"), (503, "erro 503")])
def test_http_errors_become_readable_messages_without_the_key(server, code, fragment):
    server.reply = (code, b"nope", {})
    with pytest.raises(RAError) as exc:
        ra.fetch_progress("u", KEY, 1)
    assert fragment in str(exc.value) and KEY not in str(exc.value) and "127.0.0.1" not in str(exc.value)


def test_redirects_are_not_followed(server):
    server.reply = (302, b"", {"Location": "http://127.0.0.1:1/steal"})
    with pytest.raises(RAError, match="302"):
        ra.fetch_progress("u", KEY, 1)
    assert len(server.requests) == 1  # the key was not sent anywhere else


def test_non_json_and_oversized_responses_are_refused(server, monkeypatch):
    server.reply = (200, b"<html>maintenance</html>", {})
    with pytest.raises(RAError, match="JSON"):
        ra.fetch_progress("u", KEY, 1)
    monkeypatch.setattr(ra, "MAX_BYTES", 100)
    server.reply = (200, b"[" + b"1," * 500 + b"1]", {})
    with pytest.raises(RAError, match="grande demais"):
        ra.fetch_progress("u", KEY, 1)


def test_a_slow_server_times_out_and_a_dead_one_is_reported(server, monkeypatch):
    server.reply = lambda: (time.sleep(2) or (200, b"{}", {}))
    with pytest.raises(RAError, match="Não consegui falar"):
        ra.get_json(server.url + "x", timeout=0.3)
    monkeypatch.setattr(ra, "BASE", "http://127.0.0.1:1/API/")  # nothing listens there
    with pytest.raises(RAError, match="Não consegui falar") as exc:
        ra.fetch_progress("u", KEY, 1)
    assert KEY not in str(exc.value)


# ---------------------------------------------------------------- API


@pytest.fixture
def client():
    return TestClient(app, base_url="http://127.0.0.1")


def with_game(client, tmp_path):
    gid = prepare(client, tmp_path)
    return gid


def test_the_key_is_write_only(client):
    assert client.get("/api/ra/settings").json() == {"user": "", "has_key": False}
    r = client.put("/api/ra/settings", json={"user": "rafael", "key": KEY})
    assert r.json() == {"user": "rafael", "has_key": True} and KEY not in r.text
    assert KEY not in client.get("/api/ra/settings").text
    client.put("/api/ra/settings", json={"user": "rafael2"})  # no key sent: keep the stored one
    assert client.get("/api/ra/settings").json() == {"user": "rafael2", "has_key": True}
    client.put("/api/ra/settings", json={"user": "rafael2", "key": ""})  # empty: remove it
    assert client.get("/api/ra/settings").json()["has_key"] is False


@pytest.mark.parametrize("body", [{"user": ""}, {"user": "x" * 65}, {"user": "a\nb"}, {"user": "u", "key": "has space"}, {"user": "u", "key": "k" * 200}, {"user": "u", "key": "a\nb"}])
def test_bad_credentials_are_refused(client, body):
    assert client.put("/api/ra/settings", json=body).status_code == 422


def test_game_link_roundtrip_and_validation(client, tmp_path):
    gid = with_game(client, tmp_path)
    assert client.put(f"/api/games/{gid}/ra", json={"ra": "https://retroachievements.org/game/3176"}).json() == {"ra_id": 3176}
    assert client.get(f"/api/games/{gid}/ra").json()["ra_id"] == 3176
    assert client.put(f"/api/games/{gid}/ra", json={"ra": "nope"}).status_code == 422
    assert client.get(f"/api/games/{gid}/ra").json()["ra_id"] == 3176  # a bad value changes nothing
    assert client.put(f"/api/games/{gid}/ra", json={"ra": ""}).json() == {"ra_id": None}
    assert client.put("/api/games/999/ra", json={"ra": "1"}).status_code == 404


def test_sync_stores_a_signal_and_the_games_list_shows_it(client, tmp_path, monkeypatch):
    gid = with_game(client, tmp_path)
    assert client.post(f"/api/games/{gid}/ra/sync").status_code == 409  # nothing configured
    client.put("/api/ra/settings", json={"user": "rafael", "key": KEY})
    assert client.post(f"/api/games/{gid}/ra/sync").status_code == 409  # not linked yet
    client.put(f"/api/games/{gid}/ra", json={"ra": "3176"})
    calls = []
    monkeypatch.setattr(ra, "get_json", lambda url, timeout=15.0: calls.append(url) or PASCAL)
    r = client.post(f"/api/games/{gid}/ra/sync")
    assert r.status_code == 200 and (r.json()["earned"], r.json()["total"], r.json()["percent"]) == (2, 4, 50.0)
    assert "g=3176" in calls[0] and "u=rafael" in calls[0]
    game = next(g for g in client.get("/api/games").json() if g["id"] == gid)
    assert game["ra_id"] == 3176 and game["achievements"]["percent"] == 50.0 and game["achievements"]["title"] == "Resident Evil 2"
    from app.db import connect
    sig = connect().execute("SELECT type, session_id FROM signals WHERE game_id = ?", (gid,)).fetchall()
    assert [(s["type"], s["session_id"]) for s in sig] == [("achievements", None)]  # raw signal kept, no session needed


def test_a_second_sync_keeps_history_and_the_list_shows_the_latest(client, tmp_path, monkeypatch):
    gid = with_game(client, tmp_path)
    client.put("/api/ra/settings", json={"user": "u", "key": KEY})
    client.put(f"/api/games/{gid}/ra", json={"ra": "1"})
    monkeypatch.setattr(ra, "get_json", lambda url, timeout=15.0: PASCAL)
    client.post(f"/api/games/{gid}/ra/sync")
    more = json.loads(json.dumps(PASCAL))
    more["NumAwardedToUser"] = 3
    more["Achievements"]["3"]["DateEarned"] = "2026-02-01"
    monkeypatch.setattr(ra, "get_json", lambda url, timeout=15.0: more)
    client.post(f"/api/games/{gid}/ra/sync")
    from app.db import connect
    assert connect().execute("SELECT COUNT(*) FROM signals").fetchone()[0] == 2
    assert next(g for g in client.get("/api/games").json() if g["id"] == gid)["achievements"]["earned"] == 3


def test_failed_sync_is_a_502_with_a_message_and_stores_nothing(client, tmp_path, monkeypatch):
    gid = with_game(client, tmp_path)
    client.put("/api/ra/settings", json={"user": "u", "key": KEY})
    client.put(f"/api/games/{gid}/ra", json={"ra": "1"})

    def boom(url, timeout=15.0):
        raise RAError("O RetroAchievements recusou o usuário ou a chave de API.")

    monkeypatch.setattr(ra, "get_json", boom)
    r = client.post(f"/api/games/{gid}/ra/sync")
    assert r.status_code == 502 and "recusou" in r.json()["detail"] and KEY not in r.text
    from app.db import connect
    assert connect().execute("SELECT COUNT(*) FROM signals").fetchone()[0] == 0


def test_sync_all_continues_after_a_game_error_but_stops_on_a_bad_key(client, tmp_path, monkeypatch):
    from app.db import connect
    from app import api_ra

    monkeypatch.setattr(api_ra, "PAUSE", 0)
    gid = with_game(client, tmp_path)
    c = connect()
    ids = [gid] + [c.execute("INSERT INTO games (key, title, platform, identified) VALUES (?, ?, 'P', 1)", (f"k{i}", f"G{i}")).lastrowid for i in range(3)]
    c.commit()
    client.put("/api/ra/settings", json={"user": "u", "key": KEY})
    for n, g in enumerate(ids):
        client.put(f"/api/games/{g}/ra", json={"ra": str(100 + n)})
    order = []

    def fake(url, timeout=15.0):
        order.append(url)
        if "g=101" in url:
            raise RAError("O RetroAchievements não achou esse jogo.")
        if "g=102" in url:
            raise RAError("O RetroAchievements recusou o usuário ou a chave de API.")
        return PASCAL

    monkeypatch.setattr(ra, "get_json", fake)
    results = client.post("/api/ra/sync").json()  # sorted by title: G0, G1, G2, then Resident Evil 2
    assert [(r["title"], r["ok"]) for r in results] == [("G0", False), ("G1", False)]  # G0 failed alone, G1 hit the bad key
    assert len(order) == 2 and not any("g=103" in u or "g=100" in u for u in order)  # nothing was asked after the bad key
    assert client.post("/api/ra/sync").status_code == 200


def test_two_syncs_at_once_are_refused(client, tmp_path):
    from app import api_ra

    gid = with_game(client, tmp_path)
    assert api_ra._sync_lock.acquire(blocking=False)
    try:
        assert client.post(f"/api/games/{gid}/ra/sync").status_code == 409
        client.put("/api/ra/settings", json={"user": "u", "key": KEY})
        assert client.post("/api/ra/sync").status_code == 409
    finally:
        api_ra._sync_lock.release()


def test_collector_does_nothing_without_credentials_or_a_link(client, tmp_path):
    from app.db import connect

    gid = with_game(client, tmp_path)
    assert ra.RetroAchievementsCollector().collect(connect(), gid) is None


def test_latest_signal_returns_the_newest(client, tmp_path):
    from app.db import connect

    gid = with_game(client, tmp_path)
    c = connect()
    store_signal(c, gid, "achievements", {"total": 1, "earned": 0})
    store_signal(c, gid, "achievements", {"total": 1, "earned": 1})
    store_signal(c, gid, "other", {"total": 9})
    assert latest_signal(c, gid, "achievements")["earned"] == 1 and latest_signal(c, gid, "none") is None


def test_database_file_is_private(tmp_path, monkeypatch):
    from app.db import connect

    path = tmp_path / "private" / "new.db"
    connect(path).close()
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600  # it holds the API key
