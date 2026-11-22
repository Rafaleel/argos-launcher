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


# ---------------------------------------------------------------- review fixes


import socket


class RawServer:
    """Sends fixed bytes and closes: for answers a real HTTP server would never produce."""

    def __init__(self, payload: bytes, slow: float = 0.0):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.url = f"http://127.0.0.1:{self.sock.getsockname()[1]}/API/"
        threading.Thread(target=self._run, args=(payload, slow), daemon=True).start()

    def _run(self, payload, slow):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            try:
                conn.recv(65536)
                if slow:
                    conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n")
                    for _ in range(200):
                        conn.sendall(b" ")
                        time.sleep(slow)
                else:
                    conn.sendall(payload)
            except OSError:
                pass
            finally:
                conn.close()

    def close(self):
        self.sock.close()


def raw(monkeypatch, payload, slow=0.0):
    srv = RawServer(payload, slow)
    monkeypatch.setattr(ra, "BASE", srv.url)
    return srv


def http(body: bytes, extra=b"") -> bytes:
    return b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n" + extra + b"Content-Length: %d\r\n\r\n" % len(body) + body


@pytest.mark.parametrize(
    "payload",
    [
        http(b'{"NumAchievements": Infinity, "Achievements": {}}'),
        http(b'{"NumAchievements": NaN, "Achievements": {}}'),
        http(b"[" * 200000 + b"]" * 200000),  # RecursionError in the JSON decoder
        b"GARBAGE\r\n\r\n{}",  # BadStatusLine
        b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\nZZ\r\nx",  # malformed chunk
        b"HTTP/1.1 200 OK\r\n" + b"X: " + b"a" * 70000 + b"\r\n\r\n{}",  # header line too long
        b"HTTP/1.1 200 OK\r\n" + b"".join(b"H%d: x\r\n" % i for i in range(150)) + b"\r\n{}",  # too many headers
    ],
    ids=["infinity", "nan", "deep-nesting", "bad-status", "bad-chunk", "long-header", "many-headers"],
)
def test_hostile_http_answers_become_a_readable_error_not_a_crash(monkeypatch, payload):
    raw(monkeypatch, payload)
    with pytest.raises(RAError) as exc:
        ra.fetch_progress("u", KEY, 1)
    assert str(exc.value) and KEY not in str(exc.value)


@pytest.mark.parametrize(
    "data",
    [
        {"NumAchievements": 10**400, "NumAwardedToUser": 1, "Achievements": {}},
        {"NumAchievements": float("inf"), "Achievements": {}},
        {"NumAchievements": "1e999", "Achievements": {}},
        {"Achievements": 5}, {"Achievements": True}, {"Achievements": "text"},
    ],
    ids=["huge-int", "inf-float", "exp-string", "number", "bool", "string"],
)
def test_odd_value_types_never_raise_outside_rarerror(data, monkeypatch):
    monkeypatch.setattr(ra, "get_json", lambda url, timeout=15.0: data)
    try:
        result = ra.fetch_progress("u", KEY, 1)
    except RAError:
        return  # a readable refusal is fine
    s = summary({**result, "synced_at": "t"})  # and whatever was accepted must be safe to show
    assert s["percent"] is None or 0 <= s["percent"] <= 100


def test_counts_are_sane_numbers_only():
    p = parse_progress({"NumAchievements": -5, "NumAwardedToUser": 3, "Achievements": {"1": {"ID": 1, "DateEarned": "x"}}}, 1)
    assert p["total"] == 1 and p["earned"] == 3  # a negative total is ignored, not trusted
    assert summary({**p, "synced_at": None})["percent"] == 100.0  # and a percent is never negative or above 100
    p = parse_progress({"NumAchievements": True, "Achievements": {"1": {"ID": 1}, "2": {"ID": 2}}}, 1)
    assert p["total"] == 2  # a boolean is not a count
    p = parse_progress({"Achievements": {"1": {"ID": 7, "Points": 5, "DateEarned": "x"}, "2": {"ID": 7, "Points": 5, "DateEarned": "x"}}}, 1)
    assert (p["earned"], p["points_earned"], len(p["earned_list"])) == (1, 5, 1)  # the same id twice counts once
    p = parse_progress({"NumAchievements": 1, "Title": {"a": 1}, "Achievements": {"1": {"ID": 1, "Points": -1000, "DateEarned": "x"}}}, 1)
    assert p["points_earned"] == 0 and p["title"] == ""


def test_non_dict_achievement_items_are_skipped():
    p = parse_progress({"Achievements": [None, 5, "x", {"ID": 1, "DateEarned": "x"}]}, 1)
    assert (p["total"], p["earned"]) == (1, 1)


def test_summary_never_raises_even_for_garbage_payloads(client, tmp_path):
    from app.db import connect

    assert summary({"total": 10**400, "earned": 5}) == {"title": "", "total": 0, "earned": 5, "earned_hardcore": 0, "points_earned": 0, "points_total": 0, "percent": None, "synced_at": None}
    assert summary({"total": "x", "earned": None})["percent"] is None and summary("not a dict") is None
    gid = prepare(client, tmp_path)
    c = connect()
    c.execute("INSERT INTO ra_games (game_id, ra_id) VALUES (?, 5)", (gid,))
    store_signal(c, gid, "achievements", {"ra_id": 5, "total": 10**400, "earned": 5})
    c.execute("INSERT INTO signals (game_id, type, payload, timestamp) VALUES (?, 'achievements', 'not json', 't')", (gid,))
    c.commit()
    assert client.get("/api/games").status_code == 200  # one bad stored signal must not take the library down
    assert client.get(f"/api/games/{gid}/ra").status_code == 200


def test_server_error_text_that_repeats_the_key_is_redacted(client, tmp_path, monkeypatch):
    gid = prepare(client, tmp_path)
    client.put("/api/ra/settings", json={"user": "u", "key": KEY})
    client.put(f"/api/games/{gid}/ra", json={"ra": "1"})
    monkeypatch.setattr(ra, "get_json", lambda url, timeout=15.0: {"Error": f"invalid key {KEY}"})
    r = client.post(f"/api/games/{gid}/ra/sync")
    assert r.status_code == 502 and KEY not in r.text and "invalid key" in r.text


def test_validation_errors_do_not_echo_the_submitted_key(client):
    r = client.put("/api/ra/settings", json={"user": "u", "key": KEY + " has space"})
    assert r.status_code == 422 and KEY not in r.text and r.json()["detail"][0]["msg"]
    assert client.put("/api/ra/settings", json={"user": "   "}).status_code == 422  # blank after trimming
    assert client.put("/api/ra/settings", json={"user": "  rafael  "}).json()["user"] == "rafael"


def test_the_whole_answer_has_a_deadline_not_just_each_read(monkeypatch):
    raw(monkeypatch, b"", slow=0.2)  # one byte every 0.2 s, for 40 s
    monkeypatch.setattr(ra, "TOTAL_TIMEOUT", 1.0)
    started = time.monotonic()
    with pytest.raises(RAError, match="demorou demais"):
        ra.fetch_progress("u", KEY, 1)
    assert time.monotonic() - started < 5


def test_redirect_target_receives_nothing(server):
    other = Server()
    try:
        server.reply = (307, b"", {"Location": other.url + "steal"})
        with pytest.raises(RAError, match="307"):
            ra.fetch_progress("u", KEY, 1)
        assert other.requests == []  # the key never reached the other host
    finally:
        other.close()


@pytest.mark.parametrize("text", [
    "evilretroachievements.org/game/5", "https://example.com/?u=retroachievements.org/game/5",
    "retroachievements.org.evil.com/game/5", "retroachievements.org/game/12abc",
    "https://retroachievements.org/game/9999999999999999999999999", "٣٤", "１２",
    "retroachievements.org/game/", "ftp://retroachievements.org/game/5",
])
def test_game_refs_are_anchored_and_ascii_only(text):
    with pytest.raises(ValueError):
        parse_game_ref(text)


@pytest.mark.parametrize("text,expected", [
    ("https://www.retroachievements.org/game/5/hashes", 5), ("http://retroachievements.org/game/5?x=1#f", 5),
    ("HTTPS://RETROACHIEVEMENTS.ORG/game/00005", 5),
])
def test_real_page_urls_still_work(text, expected):
    assert parse_game_ref(text) == expected


def test_a_huge_id_in_a_url_is_a_422_not_a_500(client, tmp_path):
    gid = prepare(client, tmp_path)
    r = client.put(f"/api/games/{gid}/ra", json={"ra": "https://retroachievements.org/game/9999999999999999999999999"})
    assert r.status_code == 422


def test_changing_or_removing_the_link_hides_the_old_result(client, tmp_path, monkeypatch):
    gid = prepare(client, tmp_path)
    client.put("/api/ra/settings", json={"user": "u", "key": KEY})
    client.put(f"/api/games/{gid}/ra", json={"ra": "3176"})
    monkeypatch.setattr(ra, "get_json", lambda url, timeout=15.0: PASCAL)
    client.post(f"/api/games/{gid}/ra/sync")
    shown = lambda: next(g for g in client.get("/api/games").json() if g["id"] == gid)["achievements"]  # noqa: E731
    assert shown()["percent"] == 50.0
    client.put(f"/api/games/{gid}/ra", json={"ra": "9999"})  # another game now
    assert shown() is None and client.get(f"/api/games/{gid}/ra").json()["summary"] is None
    client.put(f"/api/games/{gid}/ra", json={"ra": ""})
    assert shown() is None
    client.put(f"/api/games/{gid}/ra", json={"ra": "3176"})  # back to the one that was synced
    assert shown()["percent"] == 50.0


def test_sync_all_goes_on_after_an_unexpected_error_in_one_game(client, tmp_path, monkeypatch):
    from app import api_ra
    from app.db import connect

    monkeypatch.setattr(api_ra, "PAUSE", 0)
    gid = prepare(client, tmp_path)
    c = connect()
    other = c.execute("INSERT INTO games (key, title, platform, identified) VALUES ('k', 'AAA', 'P', 1)").lastrowid
    c.commit()
    client.put("/api/ra/settings", json={"user": "u", "key": KEY})
    client.put(f"/api/games/{other}/ra", json={"ra": "1"})
    client.put(f"/api/games/{gid}/ra", json={"ra": "2"})

    def fake(url, timeout=15.0):
        if "g=1&" in url or url.endswith("g=1"):
            raise RuntimeError("boom with " + KEY)
        return PASCAL

    monkeypatch.setattr(ra, "get_json", fake)
    r = client.post("/api/ra/sync")
    assert r.status_code == 200 and [x["ok"] for x in r.json()] == [False, True] and KEY not in r.text


def test_collector_needs_both_credentials_and_a_link(client, tmp_path):
    from app.collectors import ra_store
    from app.db import connect

    gid = prepare(client, tmp_path)
    c = connect()
    ra_store.set_credentials(c, "u", KEY)
    assert ra.RetroAchievementsCollector().collect(c, gid) is None  # credentials but no link
    ra_store.set_credentials(c, "u", "")
    ra_store.set_ra_id(c, gid, 5)
    assert ra.RetroAchievementsCollector().collect(c, gid) is None  # link but no key


@pytest.mark.parametrize("table", ["signals", "milestones", "progress_estimates"])
def test_scan_survives_a_game_that_lost_its_files_while_any_table_still_points_at_it(client, tmp_path, monkeypatch, table):
    """Each table alone must protect the game: the foreign key made every later scan fail with a 500."""
    import os

    from app.db import connect

    gid = prepare(client, tmp_path)
    (tmp_path / "roms" / "other.gba").write_bytes(b"x")  # keep the folder non-empty
    client.post("/api/scan")
    c = connect()
    if table == "signals":
        client.put("/api/ra/settings", json={"user": "u", "key": KEY})
        client.put(f"/api/games/{gid}/ra", json={"ra": "3176"})
        monkeypatch.setattr(ra, "get_json", lambda url, timeout=15.0: PASCAL)
        assert client.post(f"/api/games/{gid}/ra/sync").status_code == 200
    elif table == "milestones":
        c.execute("INSERT INTO milestones (game_id, position, name) VALUES (?, 1, 'm')", (gid,))
    else:
        c.execute("INSERT INTO progress_estimates (game_id, timestamp, mean, lower, upper) VALUES (?, 't', 0.5, 0.4, 0.6)", (gid,))
    c.commit()
    iso = tmp_path / "roms" / "re2.iso"
    data = iso.read_bytes()
    os.remove(iso)
    assert client.post("/api/scan").status_code == 200  # was: 500 IntegrityError, forever
    assert gid not in [g["id"] for g in client.get("/api/games").json()]  # no files: hidden
    (tmp_path / "roms" / "new.gba").write_bytes(b"new")
    client.post("/api/scan")
    assert any(g["title"] == "new" for g in client.get("/api/games").json())  # new games still get in
    iso.write_bytes(data)
    assert client.post("/api/scan").status_code == 200
    back = next(g for g in client.get("/api/games").json() if g["id"] == gid)  # same id: the history is back
    if table == "signals":
        assert back["achievements"]["percent"] == 50.0


def test_database_files_including_an_old_wal_are_made_private(tmp_path):
    import sqlite3

    from app.db import connect

    path = tmp_path / "old.db"
    first = sqlite3.connect(path)
    first.execute("PRAGMA journal_mode = WAL")
    first.execute("CREATE TABLE t (x)")
    first.execute("INSERT INTO t VALUES (1)")
    first.commit()  # leaves -wal and -shm behind, still open
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(f"{path}{suffix}"):
            os.chmod(f"{path}{suffix}", 0o644)
    connect(path).close()
    modes = {suffix: stat.S_IMODE(os.stat(f"{path}{suffix}").st_mode) for suffix in ("", "-wal", "-shm") if os.path.exists(f"{path}{suffix}")}
    assert modes and set(modes.values()) == {0o600}, modes
    first.close()
