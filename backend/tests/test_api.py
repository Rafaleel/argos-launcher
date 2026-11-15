import hashlib
import json
import zlib

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import dat_xml
from tests.test_launcher import fake_emulator, wait_for

BODY = bytes(range(256)) * 10
NES = "Nintendo - Nintendo Entertainment System"


@pytest.fixture
def client():
    return TestClient(app, base_url="http://127.0.0.1")


def prepare(client, tmp_path):
    roms, dats = tmp_path / "roms", tmp_path / "dats"
    roms.mkdir(), dats.mkdir()
    (roms / "mario.nes").write_bytes(BODY)
    (roms / "mystery.gba").write_bytes(b"?")
    sha, crc = hashlib.sha1(BODY).hexdigest(), f"{zlib.crc32(BODY):08x}"
    (dats / "n.dat").write_text(dat_xml(NES, [("Mario (USA)", [("m.nes", len(BODY), crc, sha)])]))
    client.put("/api/settings", json={"rom_dirs": [str(roms)], "dat_dirs": [str(dats)]})
    return client.post("/api/scan").json()


def test_full_flow_scan_list_configure_play(client, tmp_path):
    result = prepare(client, tmp_path)
    assert result["games"] == 2 and result["errors"] == []
    assert client.get("/api/platforms").json() == [NES]
    games = {g["title"]: g for g in client.get("/api/games").json()}
    assert games["Mario (USA)"]["identified"] and not games["Mario (USA)"]["has_emulator"]
    assert not games["mystery"]["identified"]

    # no emulator yet, and unidentified games cannot play
    assert client.post(f"/api/games/{games['Mario (USA)']['id']}/play").status_code == 409
    assert client.post(f"/api/games/{games['mystery']['id']}/play").status_code == 409

    out = tmp_path / "argv.json"
    emu = {"platform": NES, "executable": fake_emulator(tmp_path), "args": [str(out), "{rom}"]}
    assert client.put("/api/emulators", json=emu).status_code == 200
    r = client.post(f"/api/games/{games['Mario (USA)']['id']}/play")
    assert r.status_code == 200 and r.json()["pid"] > 0
    assert wait_for(out) == [str(tmp_path / "roms" / "mario.nes")]


def test_emulator_validation(client, tmp_path):
    prepare(client, tmp_path)
    exe = fake_emulator(tmp_path)
    assert client.put("/api/emulators", json={"platform": "NES", "executable": exe, "args": ["{rom}"]}).status_code == 422
    assert client.put("/api/emulators", json={"platform": NES, "executable": exe, "args": ["--x"]}).status_code == 422
    assert client.put("/api/emulators", json={"platform": NES, "executable": "emu", "args": ["{rom}"]}).status_code == 422


def test_unknown_game_is_404(client):
    assert client.post("/api/games/999/play").status_code == 404


def test_foreign_host_header_is_rejected(tmp_path):
    evil = TestClient(app, base_url="http://evil.example")
    assert evil.get("/api/games").status_code == 400


def test_cross_site_post_is_rejected_but_local_ui_origin_passes(client):
    evil = {"Origin": "https://evil.example", "Content-Type": "text/plain"}
    assert client.post("/api/scan", headers=evil).status_code == 403
    assert client.post("/api/scan", headers={"Origin": "http://127.0.0.1:5173"}).status_code == 200


def test_relative_folder_is_refused(client):
    r = client.put("/api/settings", json={"rom_dirs": ["roms"], "dat_dirs": []})
    assert r.status_code == 422


def test_settings_can_be_saved_while_a_scan_is_hashing(tmp_path, monkeypatch):
    import threading
    import time

    from app.db import connect
    from app.scanner import scan as scan_mod

    roms = tmp_path / "roms"
    roms.mkdir()
    for i in range(4):
        (roms / f"{i}.gba").write_bytes(bytes([i]))
    real = scan_mod.hash_file
    monkeypatch.setattr(scan_mod, "hash_file", lambda p: (time.sleep(0.3), real(p))[1])
    worker = threading.Thread(target=lambda: scan_mod.scan(connect(), [str(roms)], []))
    worker.start()
    time.sleep(0.5)  # mid-scan, after the first file was written
    other = connect()
    started = time.monotonic()
    other.execute("INSERT INTO settings (key, value) VALUES ('x', '1')")
    other.commit()
    waited = time.monotonic() - started
    worker.join()
    assert waited < 0.2  # a scan that held its write lock would make this wait for the whole scan
