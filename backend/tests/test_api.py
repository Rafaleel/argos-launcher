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
    assert client.post("/api/scan", headers={"Origin": "http://127.0.0.1:5173"}).status_code != 403


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


def test_scan_with_no_folders_is_refused_and_keeps_games(client, tmp_path):
    prepare(client, tmp_path)
    client.put("/api/settings", json={"rom_dirs": [], "dat_dirs": []})
    assert client.post("/api/scan").status_code == 422
    assert len(client.get("/api/games").json()) == 2


def test_connection_can_be_used_from_another_thread():
    # FastAPI creates the dependency in one worker thread and runs the endpoint in another
    import threading

    from app.db import connect

    conn = connect()
    errors = []

    def use():
        try:
            conn.execute("SELECT 1").fetchone()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    t = threading.Thread(target=use)
    t.start()
    t.join()
    assert errors == []


def test_play_records_a_session_and_blocks_a_second_open(client, tmp_path):
    prepare(client, tmp_path)
    exe = tmp_path / "slow-emu"
    exe.write_text("#!/bin/sh\nsleep 1.5\n")
    exe.chmod(0o755)
    client.put("/api/emulators", json={"platform": NES, "executable": str(exe), "args": ["{rom}"]})
    gid = next(g["id"] for g in client.get("/api/games").json() if g["title"] == "Mario (USA)")
    first = client.post(f"/api/games/{gid}/play")
    assert first.status_code == 200 and first.json()["session_id"] > 0
    assert client.get("/api/games").json()[0]["playing"] is True
    assert client.post(f"/api/games/{gid}/play").status_code == 409


def test_stats_endpoints_report_recorded_time(client, tmp_path):
    from app.db import connect

    prepare(client, tmp_path)
    gid = next(g["id"] for g in client.get("/api/games").json() if g["title"] == "Mario (USA)")
    c = connect()
    c.execute("INSERT INTO sessions (game_id, started_at, ended_at) VALUES (?, '2026-05-10T12:00:00Z', '2026-05-10T13:00:00Z')", (gid,))
    c.commit()
    c.close()
    assert next(g for g in client.get("/api/games").json() if g["id"] == gid)["seconds_played"] == 3600
    assert client.get("/api/stats/games").json()[0]["seconds"] == 3600
    assert client.get("/api/stats/platforms").json() == [{"platform": NES, "seconds": 3600}]
    assert client.get("/api/stats/periods?by=month&n=60").status_code == 200
    assert client.get("/api/stats/periods?by=year").status_code == 422


def test_played_game_survives_losing_its_files_and_scan_does_not_fail(client, tmp_path):
    import os

    from app.db import connect

    prepare(client, tmp_path)
    gid = next(g["id"] for g in client.get("/api/games").json() if g["title"] == "Mario (USA)")
    c = connect()
    c.execute("INSERT INTO sessions (game_id, started_at, ended_at) VALUES (?, '2026-05-10T12:00:00Z', '2026-05-10T13:00:00Z')", (gid,))
    c.commit()
    c.close()
    os.remove(tmp_path / "roms" / "mario.nes")
    r = client.post("/api/scan")
    assert r.status_code == 200  # a played game used to break the delete (foreign key)
    assert gid not in [g["id"] for g in client.get("/api/games").json()]  # no files, no Jogar
    assert client.get("/api/stats/games").json()[0]["seconds"] == 3600  # history kept


def test_startup_closes_orphan_sessions(tmp_path):
    from app.db import connect

    c = connect()
    gid = c.execute("INSERT INTO games (key, title, platform, identified) VALUES ('k', 'G', 'P', 1)").lastrowid
    c.execute("INSERT INTO sessions (game_id, started_at, last_heartbeat) VALUES (?, '2026-01-01T10:00:00Z', '2026-01-01T10:30:00Z')", (gid,))
    c.commit()
    c.close()
    with TestClient(app, base_url="http://127.0.0.1"):  # runs the lifespan
        pass
    c = connect()
    assert c.execute("SELECT ended_at FROM sessions").fetchone()["ended_at"] == "2026-01-01T10:30:00Z"
