"""Covers: fetched once from a local stand-in for libretro-thumbnails, then served from the cache."""
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from app import covers
from app.main import app
from tests.test_dolphin_api import GC, prepare

IMG = covers.PNG + b"fake image body" + covers.PNG_END


class Thumbs:
    def __init__(self):
        outer = self
        self.files: dict[str, bytes] = {}
        self.paths: list[str] = []
        self.status = None

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.paths.append(unquote(self.path))
                body = outer.files.get(unquote(self.path))
                code = outer.status or (200 if body is not None else 404)
                body = body if code == 200 else b"nope"
                self.send_response(code)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()


@pytest.fixture
def thumbs(monkeypatch):
    t = Thumbs()
    monkeypatch.setattr(covers, "BASE", f"http://127.0.0.1:{t.httpd.server_port}/")
    yield t
    t.httpd.shutdown()


def path(platform, title):
    return f"/{platform.replace(' ', '_')}/master/Named_Boxarts/{title}.png"


def test_url_follows_the_libretro_naming_rule():
    [u] = covers.urls("Nintendo - GameCube", 'A/B: C? "D" & E')
    assert u.endswith("Nintendo_-_GameCube/master/Named_Boxarts/A_B_%20C_%20_D_%20_%20E.png")


def test_a_disc_title_also_tries_the_name_without_the_disc():
    urls = covers.urls(GC, "Game (USA) (Disc 2)")
    assert len(urls) == 2 and "Disc" not in urls[1]


def test_fetched_once_then_served_from_cache(thumbs):
    thumbs.files[path(GC, "Game (USA)")] = IMG
    p = covers.get(GC, "Game (USA)")
    assert p.read_bytes() == IMG
    assert covers.get(GC, "Game (USA)") == p and len(thumbs.paths) == 1


def test_disc_fallback(thumbs):
    thumbs.files[path(GC, "Game (USA)")] = IMG
    assert covers.get(GC, "Game (USA) (Disc 2)").read_bytes() == IMG


def test_missing_cover_is_remembered_but_retried_later(thumbs, monkeypatch):
    assert covers.get(GC, "Nothing") is None
    assert covers.get(GC, "Nothing") is None and len(thumbs.paths) == 1  # remembered
    monkeypatch.setattr(covers, "RETRY_MISSING", 0)
    thumbs.files[path(GC, "Nothing")] = IMG
    assert covers.get(GC, "Nothing").read_bytes() == IMG


def test_offline_or_server_error_is_not_remembered(thumbs):
    thumbs.status = 503
    assert covers.get(GC, "X") is None
    thumbs.status = None
    thumbs.files[path(GC, "X")] = IMG
    assert covers.get(GC, "X") is not None


@pytest.mark.parametrize("body", [b"<html>not an image</html>", covers.PNG + b"x" * (6 * 1024 * 1024) + covers.PNG_END])
def test_non_png_or_huge_answers_are_not_saved(thumbs, body):
    thumbs.files[path(GC, "Bad")] = body
    assert covers.get(GC, "Bad") is None
    assert not list(covers.cover_dir().glob("*.png"))


def test_api_serves_the_cover_of_an_identified_game(thumbs, tmp_path):
    client = TestClient(app, base_url="http://127.0.0.1")
    gid = prepare(client, tmp_path)
    thumbs.files[path(GC, "Resident Evil 2 (USA)")] = IMG
    r = client.get(f"/api/games/{gid}/cover")
    assert r.status_code == 200 and r.content == IMG and r.headers["content-type"] == "image/png"
    assert client.get("/api/games/999/cover").status_code == 404


def test_a_cut_download_is_not_cached(thumbs):
    thumbs.files[path(GC, "Cut")] = covers.PNG + b"half of it"  # no IEND: the connection dropped
    assert covers.get(GC, "Cut") is None
    thumbs.files[path(GC, "Cut")] = IMG
    assert covers.get(GC, "Cut").read_bytes() == IMG
