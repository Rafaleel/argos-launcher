"""Automatic RetroAchievements id detection: GameCube disc hash, the gameid lookup and the API routes.

Nothing here reaches the real site: the lookup goes to a server on 127.0.0.1.
"""
import hashlib
import json
import struct
import threading
import zlib
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs

import pytest
from fastapi.testclient import TestClient

from app import api_ra
from app.collectors import ra_hash
from app.collectors import retroachievements as ra
from app.collectors.ra_hash import gamecube_hash
from app.collectors.retroachievements import RAError
from app.main import app
from tests.conftest import dat_xml
from tests.test_dolphin_api import GC

HEADER = 0x2440 + 0x20 + 0x100 + 0x40  # apploader body 0x100, trailer 0x40
DOL = 0x4000
SEGMENTS = [(0x6000, 0x300), (0x7000, 0x80)]  # (offset, length) of two non-empty segments; the offsets are absolute, as rcheevos reads them (not dol + offset)


def gc_image(*, magic=True, segments=SEGMENTS, size=0x8000, dol=DOL, fill=7) -> bytes:
    img = bytearray(bytes([fill]) * size)
    img[0x1C:0x20] = bytes.fromhex("c2339f3d") if magic else b"\0\0\0\0"
    img[0x2454:0x245C] = struct.pack(">II", 0x100, 0x40)
    img[0x420:0x424] = struct.pack(">I", dol)
    img[dol : dol + 0xD8] = bytes(0xD8)
    for i, (off, length) in enumerate(segments):
        img[dol + i * 4 : dol + i * 4 + 4] = struct.pack(">I", off)
        img[dol + 0x90 + i * 4 : dol + 0x90 + i * 4 + 4] = struct.pack(">I", length)
    return bytes(img)


def expected(img: bytes) -> str:
    return hashlib.md5(img[:HEADER] + b"".join(img[o : o + n] for o, n in SEGMENTS)).hexdigest()


@pytest.fixture
def disc(tmp_path):
    def make(img: bytes, name="game.iso") -> str:
        p = tmp_path / name
        p.write_bytes(img)
        return str(p)

    return make


# ---------------------------------------------------------------- hash


def test_gamecube_hash_covers_the_header_and_each_dol_segment(disc):
    img = gc_image()
    assert gamecube_hash(disc(img)) == expected(img)


def test_hash_changes_with_the_header_and_with_every_segment_but_not_with_other_bytes(disc):
    img = bytearray(gc_image())
    base = gamecube_hash(disc(bytes(img), "a.iso"))
    for at in (0x10, HEADER - 1, SEGMENTS[0][0], SEGMENTS[0][0] + SEGMENTS[0][1] - 1, SEGMENTS[1][0]):
        other = bytearray(img)
        other[at] ^= 0xFF
        assert gamecube_hash(disc(bytes(other), f"{at}.iso")) != base, at
    for at in (HEADER, SEGMENTS[0][0] + SEGMENTS[0][1], 0x7F00):  # game data the hash ignores
        other = bytearray(img)
        other[at] ^= 0xFF
        assert gamecube_hash(disc(bytes(other), f"x{at}.iso")) == base, at


def test_empty_segments_are_skipped(disc):
    img = gc_image(segments=[(0, 0), (0x6000, 0x300), (0, 0), (0x7000, 0x80)])
    assert gamecube_hash(disc(img)) == expected(img)


@pytest.mark.parametrize(
    "img",
    [
        b"",
        b"too short",
        gc_image(magic=False),
        gc_image()[:HEADER - 1],  # cut inside the header
        gc_image()[:0x6100],  # cut inside a segment
        gc_image(segments=[(0x7F00, 0x1000)]),  # segment runs past the end
        gc_image(segments=[(0x6000, 0xFFFFFFFF)]),  # absurd length
        gc_image(dol=0x7FFF)[:0x8000],  # dol table starts inside the image but does not fit
    ],
    ids=["empty", "short", "no-magic", "cut-header", "cut-segment", "past-end", "huge", "dol-outside"],
)
def test_not_a_usable_gamecube_image_gives_none(disc, img):
    assert gamecube_hash(disc(img)) is None


def test_missing_file_gives_none(tmp_path):
    assert gamecube_hash(str(tmp_path / "nope.iso")) is None


def test_huge_total_is_refused_even_if_each_segment_fits(disc, monkeypatch):
    monkeypatch.setattr(ra_hash, "MAX_HASHED", 0x200)
    assert gamecube_hash(disc(gc_image())) is None  # 0x300 + 0x80 > 0x200


def test_gamecube_is_registered_under_the_dat_platform_name():
    assert ra_hash.HASHERS[GC] is gamecube_hash


# ---------------------------------------------------------------- gameid lookup against a local server


class Lookup:
    def __init__(self):
        outer = self
        self.calls, self.reply = [], (200, {"Success": True, "GameID": 3176}, {})

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
                outer.calls.append({"path": self.path, "body": parse_qs(body), "type": self.headers.get("Content-Type")})
                code, payload, headers = outer.reply() if callable(outer.reply) else outer.reply
                raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                self.send_response(code)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *a):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/dorequest.php"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()


@pytest.fixture
def lookup(monkeypatch):
    s = Lookup()
    monkeypatch.setattr(ra, "DOREQUEST", s.url)
    yield s
    s.httpd.shutdown()


MD5 = "a" * 32


def test_resolve_posts_only_the_request_type_and_the_hash(lookup):
    assert ra.resolve_game_id(MD5) == 3176
    call = lookup.calls[0]
    assert call["path"] == "/dorequest.php"
    assert call["body"] == {"r": ["gameid"], "m": [MD5]}  # no user, no key
    assert call["type"] == "application/x-www-form-urlencoded"


def test_resolve_treats_game_id_zero_as_unknown(lookup):
    lookup.reply = (200, {"Success": True, "GameID": 0}, {})
    assert ra.resolve_game_id(MD5) is None
    lookup.reply = (200, {"Success": True}, {})
    assert ra.resolve_game_id(MD5) is None


@pytest.mark.parametrize("payload", [{"Success": False, "Error": "x"}, [], "text", b"<html>"])
def test_resolve_rejects_failures_and_odd_shapes(lookup, payload):
    lookup.reply = (200, payload, {})
    with pytest.raises(RAError):
        ra.resolve_game_id(MD5)


@pytest.mark.parametrize("bad", ["", "xyz", "A" * 32, "a" * 31, "a" * 33, "a" * 32 + "&r=x"])
def test_resolve_refuses_anything_that_is_not_a_lowercase_md5(lookup, bad):
    with pytest.raises(RAError):
        ra.resolve_game_id(bad)
    assert lookup.calls == []  # nothing was sent


def test_resolve_does_not_follow_redirects_and_maps_http_errors(lookup):
    lookup.reply = (302, b"", {"Location": "http://127.0.0.1:1/x"})
    with pytest.raises(RAError, match="302"):
        ra.resolve_game_id(MD5)
    lookup.reply = (503, b"down", {})
    with pytest.raises(RAError, match="503"):
        ra.resolve_game_id(MD5)


def test_a_huge_game_id_is_not_trusted(lookup):
    lookup.reply = (200, {"Success": True, "GameID": 10**30}, {})
    assert ra.resolve_game_id(MD5) is None


# ---------------------------------------------------------------- API


@pytest.fixture
def client():
    return TestClient(app, base_url="http://127.0.0.1")


@pytest.fixture(autouse=True)
def no_pause(monkeypatch):
    monkeypatch.setattr(api_ra, "PAUSE", 0)


def library(client, tmp_path, files: dict[str, tuple[str, bytes]]):
    """files: name -> (platform, bytes). Returns {name: game id}."""
    roms, dats = tmp_path / "roms", tmp_path / "dats"
    roms.mkdir(), dats.mkdir()
    by_platform: dict[str, list] = {}
    for name, (platform, data) in files.items():
        (roms / name).write_bytes(data)
        by_platform.setdefault(platform, []).append(
            (f"Game {name}", [(name, len(data), f"{zlib.crc32(data):08x}", hashlib.sha1(data).hexdigest())])
        )
    for i, (platform, games) in enumerate(by_platform.items()):
        (dats / f"{i}.dat").write_text(dat_xml(platform, games))
    client.put("/api/settings", json={"rom_dirs": [str(roms)], "dat_dirs": [str(dats)]})
    client.post("/api/scan")
    ids = {g["title"]: g["id"] for g in client.get("/api/games").json()}
    return {name: ids[f"Game {name}"] for name in files}


def test_detect_links_the_game_the_site_names(client, tmp_path, lookup):
    img = gc_image()
    gid = library(client, tmp_path, {"a.iso": (GC, img)})["a.iso"]
    r = client.post(f"/api/games/{gid}/ra/detect")
    assert r.status_code == 200 and r.json() == {"found": True, "ra_id": 3176, "hash": expected(img)}
    assert lookup.calls[0]["body"]["m"] == [expected(img)]
    assert client.get(f"/api/games/{gid}/ra").json()["ra_id"] == 3176
    assert next(g for g in client.get("/api/games").json() if g["id"] == gid)["ra_id"] == 3176


def test_detect_needs_no_credentials(client, tmp_path, lookup):
    gid = library(client, tmp_path, {"a.iso": (GC, gc_image())})["a.iso"]
    assert client.get("/api/ra/settings").json()["has_key"] is False
    assert client.post(f"/api/games/{gid}/ra/detect").status_code == 200


def test_an_unknown_disc_changes_nothing(client, tmp_path, lookup):
    lookup.reply = (200, {"Success": True, "GameID": 0}, {})
    gid = library(client, tmp_path, {"a.iso": (GC, gc_image())})["a.iso"]
    client.put(f"/api/games/{gid}/ra", json={"ra": "999"})
    r = client.post(f"/api/games/{gid}/ra/detect")
    assert r.json()["found"] is False and r.json()["ra_id"] is None
    assert client.get(f"/api/games/{gid}/ra").json()["ra_id"] == 999  # the manual link survives


def test_detect_refuses_unknown_games_other_consoles_and_bad_images(client, tmp_path, lookup):
    ids = library(client, tmp_path, {"a.iso": (GC, gc_image(magic=False)), "b.nes": ("Nintendo - Nintendo Entertainment System", b"NES\x1a" + bytes(100))})
    assert client.post("/api/games/999/ra/detect").status_code == 404
    r = client.post(f"/api/games/{ids['b.nes']}/ra/detect")
    assert r.status_code == 409 and "Nintendo Entertainment System" in r.json()["detail"]
    r = client.post(f"/api/games/{ids['a.iso']}/ra/detect")
    assert r.status_code == 409 and "imagem de disco" in r.json()["detail"]
    assert lookup.calls == []  # nothing is asked of the site when we cannot hash


def test_detect_reports_missing_files(client, tmp_path, lookup):
    gid = library(client, tmp_path, {"a.iso": (GC, gc_image())})["a.iso"]
    (tmp_path / "roms" / "a.iso").unlink()
    r = client.post(f"/api/games/{gid}/ra/detect")
    assert r.status_code == 409 and "escaneie" in r.json()["detail"]


def test_detect_turns_a_site_failure_into_502(client, tmp_path, lookup):
    lookup.reply = (503, b"down", {})
    gid = library(client, tmp_path, {"a.iso": (GC, gc_image())})["a.iso"]
    assert client.post(f"/api/games/{gid}/ra/detect").status_code == 502
    assert client.get(f"/api/games/{gid}/ra").json()["ra_id"] is None


def test_detect_all_tries_only_unlinked_hashable_games(client, tmp_path, lookup):
    ids = library(
        client,
        tmp_path,
        {
            "a.iso": (GC, gc_image(fill=1)),
            "b.iso": (GC, gc_image(fill=2)),
            "c.iso": (GC, gc_image(fill=3)),
            "d.nes": ("Nintendo - Nintendo Entertainment System", b"NES\x1a" + bytes(100)),
        },
    )
    client.put(f"/api/games/{ids['b.iso']}/ra", json={"ra": "55"})  # already linked
    results = client.post("/api/ra/detect").json()
    assert [r["title"] for r in results] == ["Game a.iso", "Game c.iso"]
    assert all(r["ok"] for r in results) and len(lookup.calls) == 2
    assert client.get(f"/api/games/{ids['b.iso']}/ra").json()["ra_id"] == 55
    assert client.get(f"/api/games/{ids['a.iso']}/ra").json()["ra_id"] == 3176
    assert client.get(f"/api/games/{ids['d.nes']}/ra").json()["ra_id"] is None


def test_detect_all_reports_each_game_and_keeps_going_after_a_bad_disc(client, tmp_path, lookup):
    library(client, tmp_path, {"a.iso": (GC, gc_image(magic=False)), "b.iso": (GC, gc_image(fill=2))})
    results = client.post("/api/ra/detect").json()
    assert [(r["title"], r["ok"]) for r in results] == [("Game a.iso", False), ("Game b.iso", True)]
    assert "imagem de disco" in results[0]["message"]


def test_detect_all_stops_when_the_site_is_unreachable(client, tmp_path, lookup):
    lookup.reply = (503, b"down", {})
    library(client, tmp_path, {f"{n}.iso": (GC, gc_image(fill=i + 1)) for i, n in enumerate("abc")})
    results = client.post("/api/ra/detect").json()
    assert len(results) == 1 and results[0]["ok"] is False  # the other two would fail the same way
    assert len(lookup.calls) == 1


def test_detect_all_with_nothing_to_do(client):
    assert client.post("/api/ra/detect").json() == []


def test_an_operation_in_progress_refuses_detection(client, tmp_path, lookup):
    gid = library(client, tmp_path, {"a.iso": (GC, gc_image())})["a.iso"]
    assert api_ra._sync_lock.acquire(blocking=False)
    try:
        assert client.post(f"/api/games/{gid}/ra/detect").status_code == 409
        assert client.post("/api/ra/detect").status_code == 409
    finally:
        api_ra._sync_lock.release()
    assert lookup.calls == []
