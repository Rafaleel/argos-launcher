"""Logging Dolphin in to RetroAchievements from Argos. The lookup server is local; no real login."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs

import pytest
from fastapi.testclient import TestClient

from app.collectors import retroachievements as ra
from app.collectors.retroachievements import RAError
from app.emulators import dolphin
from app.main import app
from tests.test_dolphin_api import native_dolphin, prepare

PASSWORD = "hunter2-secret"
TOKEN = "AbCdEf0123456789"


class Site:
    def __init__(self):
        outer = self
        self.bodies, self.reply = [], {"Success": True, "User": "Rafael", "Token": TOKEN}

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                outer.bodies.append(parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode()))
                body = json.dumps(outer.reply).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()


@pytest.fixture
def site(monkeypatch):
    s = Site()
    monkeypatch.setattr(ra, "DOREQUEST", f"http://127.0.0.1:{s.httpd.server_port}/dorequest.php")
    yield s
    s.httpd.shutdown()


def test_login_sends_login2_and_returns_the_token(site):
    assert ra.login_token("rafael", PASSWORD) == ("Rafael", TOKEN)
    assert site.bodies[0] == {"r": ["login2"], "u": ["rafael"], "p": [PASSWORD]}


@pytest.mark.parametrize("reply", [
    {"Success": False, "Error": f"Invalid password {PASSWORD}"},
    {"Success": True, "User": "Rafael"},
    {"Success": True, "User": "Rafael", "Token": "has space"},
    {"Success": True, "User": "a\nb", "Token": TOKEN},
    [],
])
def test_bad_logins_are_readable_and_never_echo_the_password(site, reply):
    site.reply = reply
    with pytest.raises(RAError) as exc:
        ra.login_token("rafael", PASSWORD)
    assert PASSWORD not in str(exc.value)


def test_status_reads_the_ini_without_the_token(tmp_path):
    ins = dolphin.Install(False, tmp_path / "cfg", tmp_path / "data")
    assert dolphin.ra_status(ins) == {"enabled": False, "user": "", "logged_in": False, "hardcore": False}
    dolphin.write_ra_login(ins, "Rafael", TOKEN)
    ini = (tmp_path / "cfg/RetroAchievements.ini").read_text()
    assert "[Achievements]" in ini and f"ApiToken = {TOKEN}" in ini and "Enabled = True" in ini
    assert dolphin.ra_status(ins) == {"enabled": True, "user": "Rafael", "logged_in": True, "hardcore": False}
    dolphin.write_ra_login(ins, "", None)
    assert TOKEN not in (tmp_path / "cfg/RetroAchievements.ini").read_text()
    assert dolphin.ra_status(ins)["logged_in"] is False


def test_login_keeps_other_settings(tmp_path):
    ins = dolphin.Install(False, tmp_path / "cfg", tmp_path / "data")
    (tmp_path / "cfg").mkdir()
    (tmp_path / "cfg/RetroAchievements.ini").write_text("[Achievements]\nHardcoreEnabled = True\nUnofficialEnabled = False\n")
    dolphin.write_ra_login(ins, "Rafael", TOKEN)
    text = (tmp_path / "cfg/RetroAchievements.ini").read_text()
    assert "HardcoreEnabled = True" in text and "UnofficialEnabled = False" in text
    assert dolphin.ra_status(ins)["hardcore"] is True


@pytest.mark.parametrize("user,token", [("a b", TOKEN), ("ok", "short"), ("ok", "x\nApiToken = evil")])
def test_write_refuses_odd_values(tmp_path, user, token):
    with pytest.raises(ValueError):
        dolphin.write_ra_login(dolphin.Install(False, tmp_path, tmp_path), user, token)


# ---------------------------------------------------------------- API


@pytest.fixture
def client(tmp_path):
    c = TestClient(app, base_url="http://127.0.0.1")
    prepare(c, tmp_path)
    native_dolphin(c, tmp_path)
    return c


def test_api_login_writes_dolphin_and_never_returns_token_or_password(client, site):
    r = client.post("/api/dolphin/achievements/login", json={"user": "rafael", "password": PASSWORD})
    assert r.status_code == 200 and r.json()["logged_in"] is True and r.json()["user"] == "Rafael"
    assert TOKEN not in r.text and PASSWORD not in r.text
    assert TOKEN not in client.get("/api/dolphin/achievements").text
    assert TOKEN in (Path.home() / ".config/dolphin-emu/RetroAchievements.ini").read_text()
    assert client.delete("/api/dolphin/achievements/login").json()["logged_in"] is False


def test_api_refuses_while_dolphin_runs(client, site, monkeypatch):
    monkeypatch.setattr(dolphin, "is_running", lambda proc="/proc": True)
    assert client.post("/api/dolphin/achievements/login", json={"user": "rafael", "password": PASSWORD}).status_code == 409
    assert site.bodies == []  # the password was not even sent


def test_api_rejected_login_is_502_without_the_password(client, site):
    site.reply = {"Success": False, "Error": f"bad {PASSWORD}"}
    r = client.post("/api/dolphin/achievements/login", json={"user": "rafael", "password": PASSWORD})
    assert r.status_code == 502 and PASSWORD not in r.text
    assert not (Path.home() / ".config/dolphin-emu/RetroAchievements.ini").exists()


def test_validation_error_does_not_echo_the_password(client):
    r = client.post("/api/dolphin/achievements/login", json={"user": "", "password": PASSWORD})
    assert r.status_code == 422 and PASSWORD not in r.text


def test_a_401_login_says_user_or_password(site, monkeypatch):
    def refuse(*a, **k):
        raise RAError("O RetroAchievements recusou o usuário ou a chave de API. Confira os dois em Configurações.")
    monkeypatch.setattr(ra, "get_json", refuse)
    with pytest.raises(RAError, match="senha"):
        ra.login_token("rafael", PASSWORD)
