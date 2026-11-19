import hashlib
import json
import os
import stat
import sys
import zlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.emulators import dolphin
from app.main import app
from tests.conftest import dat_xml
from tests.test_dolphin import make_zip, needs_7z
from tests.test_launcher import wait_for

GC = "Nintendo - GameCube"
DISC = b"GHAE08" + bytes(range(250)) * 4


@pytest.fixture
def client():
    return TestClient(app, base_url="http://127.0.0.1")


def prepare(client, tmp_path):
    roms, dats = tmp_path / "roms", tmp_path / "dats"
    roms.mkdir(), dats.mkdir()
    (roms / "re2.iso").write_bytes(DISC)
    sha, crc = hashlib.sha1(DISC).hexdigest(), f"{zlib.crc32(DISC):08x}"
    (dats / "gc.dat").write_text(dat_xml(GC, [("Resident Evil 2 (USA)", [("re2.iso", len(DISC), crc, sha)])]))
    client.put("/api/settings", json={"rom_dirs": [str(roms)], "dat_dirs": [str(dats)]})
    client.post("/api/scan")
    return next(g["id"] for g in client.get("/api/games").json() if g["title"].startswith("Resident"))


def fake(tmp_path, name):
    exe = tmp_path / name
    exe.write_text(f"#!{sys.executable}\nimport json, os, sys\nopen(sys.argv[1], 'w').write(json.dumps({{'argv': sys.argv[2:], 'prime': os.environ.get('__NV_PRIME_RENDER_OFFLOAD')}}))\n")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    return str(exe)


def native_dolphin(client, tmp_path):
    out = tmp_path / "out.json"
    exe = fake(tmp_path, "dolphin-emu")
    assert client.put("/api/emulators", json={"platform": GC, "executable": exe, "args": [str(out), "-b", "-e", "{rom}"]}).status_code == 200
    return out


def test_play_writes_the_game_ini_and_passes_gpu_and_backend(client, tmp_path):
    gid = prepare(client, tmp_path)
    out = native_dolphin(client, tmp_path)
    client.put("/api/dolphin/defaults", json={"backend": "Vulkan", "gpu": "nvidia", "internal_resolution": 2, "vsync": True})
    client.put(f"/api/games/{gid}/profile", json={"internal_resolution": 4, "hires_textures": True})
    assert client.post(f"/api/games/{gid}/play").status_code == 200
    ran = wait_for(out)
    assert ran["argv"][-2:] == ["-v", "Vulkan"] and ran["prime"] == "1"
    ini = (Path.home() / ".local/share/dolphin-emu/GameSettings/GHAE08.ini").read_text()
    assert "InternalResolution = 4" in ini  # the game overrides the default of 2
    assert "VSync = True" in ini and "HiresTextures = True" in ini


def test_non_dolphin_emulator_is_launched_untouched(client, tmp_path):
    gid = prepare(client, tmp_path)
    out = tmp_path / "out.json"
    exe = fake(tmp_path, "other-emu")
    client.put("/api/emulators", json={"platform": GC, "executable": exe, "args": [str(out), "{rom}"]})
    assert client.post(f"/api/games/{gid}/play").status_code == 200
    ran = wait_for(out)
    assert ran["argv"] == [str(tmp_path / "roms" / "re2.iso")] and ran["prime"] is None
    assert not (Path.home() / ".local/share/dolphin-emu").exists()
    assert client.get(f"/api/games/{gid}/profile").status_code == 409  # not a Dolphin game


def test_flatpak_launch_puts_env_options_before_the_app_id(client, tmp_path):
    gid = prepare(client, tmp_path)
    out = tmp_path / "out.json"
    exe = fake(tmp_path, "flatpak")
    client.put("/api/emulators", json={"platform": GC, "executable": exe, "args": [str(out), "run", dolphin.FLATPAK_ID, "-b", "-e", "{rom}"]})
    client.put("/api/dolphin/defaults", json={"gpu": "nvidia", "hires_textures": True})
    assert client.post(f"/api/games/{gid}/play").status_code == 200
    argv = wait_for(out)["argv"]
    assert argv[0] == "run" and argv[1].startswith("--env=") and argv.index(dolphin.FLATPAK_ID) == 1 + len(dolphin.NVIDIA_ENV)
    assert (Path.home() / ".var/app/org.DolphinEmu.dolphin-emu/data/dolphin-emu/GameSettings/GHAE08.ini").exists()


def test_games_list_marks_dolphin_games(client, tmp_path):
    gid = prepare(client, tmp_path)
    assert client.get("/api/games").json()[0]["dolphin"] is False
    native_dolphin(client, tmp_path)
    game = next(g for g in client.get("/api/games").json() if g["id"] == gid)
    assert game["dolphin"] is True and "emu_exe" not in game


def test_defaults_and_profile_endpoints_validate_and_roundtrip(client, tmp_path):
    gid = prepare(client, tmp_path)
    native_dolphin(client, tmp_path)
    assert client.put("/api/dolphin/defaults", json={"internal_resolution": 99}).status_code == 422
    assert client.put("/api/dolphin/defaults", json={"hack": True}).status_code == 422
    assert client.put("/api/dolphin/defaults", json={"anisotropy": 4, "vsync": None}).json() == {"anisotropy": 4}
    assert client.put(f"/api/games/{gid}/profile", json={"vsync": False}).json() == {"vsync": False}
    prof = client.get(f"/api/games/{gid}/profile").json()
    assert prof["effective"] == {"anisotropy": 4, "vsync": False} and prof["game_code"] == "GHAE08"
    assert client.get("/api/games/999/profile").status_code == 404


def test_corrupt_stored_profile_reads_as_empty(client, tmp_path):
    from app.db import connect

    gid = prepare(client, tmp_path)
    native_dolphin(client, tmp_path)
    c = connect()
    c.execute("INSERT INTO settings (key, value) VALUES ('dolphin_defaults', 'not json')")
    c.execute("INSERT INTO game_profiles (game_id, data) VALUES (?, '{\"internal_resolution\": 99}')", (gid,))
    c.commit()
    assert client.get(f"/api/games/{gid}/profile").json()["effective"] == {}
    assert client.post(f"/api/games/{gid}/play").status_code == 200


def test_info_endpoint(client, tmp_path):
    assert client.get("/api/dolphin/info").json()["detected"] is False
    prepare(client, tmp_path)
    native_dolphin(client, tmp_path)
    info = client.get("/api/dolphin/info").json()
    assert info["detected"] and info["presets"] == ["keyboard_default", "keyboard_wasd", "xbox"]
    assert isinstance(info["gpus"], list) and isinstance(info["controllers"], list)


def test_controls_endpoints_and_the_running_guard(client, tmp_path, monkeypatch):
    assert client.get("/api/dolphin/controls").status_code == 409  # no Dolphin configured yet
    prepare(client, tmp_path)
    native_dolphin(client, tmp_path)
    r = client.put("/api/dolphin/controls", json={"preset": "xbox", "device": "SDL/0/Xbox Wireless Controller"})
    assert r.json() == {"device": "SDL/0/Xbox Wireless Controller"}
    assert client.put("/api/dolphin/controls", json={"preset": "xbox", "device": "nope"}).status_code == 422
    assert client.put("/api/dolphin/controls", json={"preset": "bogus"}).status_code == 422
    monkeypatch.setattr(dolphin, "is_running", lambda proc="/proc": True)
    assert client.put("/api/dolphin/controls", json={"preset": "keyboard_wasd"}).status_code == 409
    assert client.get("/api/dolphin/controls").json()["device"] == "SDL/0/Xbox Wireless Controller"


@needs_7z
def test_textures_endpoints_install_job_and_remove(client, tmp_path, monkeypatch):
    gid = prepare(client, tmp_path)
    native_dolphin(client, tmp_path)
    z = tmp_path / "pack.zip"
    make_zip(z, ["GHA/Rooms/a.dds"])
    assert client.post(f"/api/games/{gid}/textures", json={"archive": "relative.zip"}).status_code == 422
    assert client.post(f"/api/games/{gid}/textures", json={"archive": str(tmp_path / "missing.zip")}).status_code == 422
    with monkeypatch.context() as m:  # never monkeypatch.undo(): it would also undo the HOME/DB isolation
        m.setattr(dolphin, "is_running", lambda proc="/proc": True)
        assert client.post(f"/api/games/{gid}/textures", json={"archive": str(z)}).status_code == 409
    assert client.post(f"/api/games/{gid}/textures", json={"archive": str(z)}).status_code == 202
    for t in list(dolphin.MONITORS):
        t.join(timeout=30)
    assert client.get("/api/dolphin/textures/job").json()["state"] == "done"
    assert client.get(f"/api/games/{gid}/profile").json()["textures"]["files"] == 1
    assert client.delete(f"/api/games/{gid}/textures").json() == {"removed": True}
    assert client.get(f"/api/games/{gid}/profile").json()["textures"]["installed"] is False
    other = tmp_path / "other.zip"
    make_zip(other, ["ZZZ/a.dds"])
    client.post(f"/api/games/{gid}/textures", json={"archive": str(other)})
    for t in list(dolphin.MONITORS):
        t.join(timeout=30)
    job = client.get("/api/dolphin/textures/job").json()
    assert job["state"] == "error" and "não é deste jogo" in job["message"]


def test_dolphin_game_without_a_profile_writes_no_ini(client, tmp_path):
    gid = prepare(client, tmp_path)
    out = native_dolphin(client, tmp_path)
    assert client.post(f"/api/games/{gid}/play").status_code == 200
    assert wait_for(out)["argv"][-1] == str(tmp_path / "roms" / "re2.iso")  # no -v appended
    assert not (Path.home() / ".local/share/dolphin-emu/GameSettings").exists()


def test_padrao_removes_what_argos_wrote_on_the_next_play(client, tmp_path):
    gid = prepare(client, tmp_path)
    out = native_dolphin(client, tmp_path)
    ini = Path.home() / ".local/share/dolphin-emu/GameSettings/GHAE08.ini"
    client.put(f"/api/games/{gid}/profile", json={"internal_resolution": 6, "vsync": False})
    client.post(f"/api/games/{gid}/play")
    wait_for(out)
    assert "InternalResolution = 6" in ini.read_text()
    for t in list(__import__("app.sessions.tracker", fromlist=["x"]).MONITORS):
        t.join(timeout=10)
    out.unlink()
    client.put(f"/api/games/{gid}/profile", json={})
    assert client.post(f"/api/games/{gid}/play").status_code == 200
    wait_for(out)
    assert "InternalResolution" not in ini.read_text() and "VSync" not in ini.read_text()


def test_refused_play_does_not_rewrite_the_ini(client, tmp_path):
    from app.db import connect

    gid = prepare(client, tmp_path)
    native_dolphin(client, tmp_path)
    c = connect()
    c.execute("INSERT INTO sessions (game_id, started_at, last_heartbeat) VALUES (?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')", (gid,))
    c.commit()  # the game is "already open"
    client.put(f"/api/games/{gid}/profile", json={"internal_resolution": 5})
    assert client.post(f"/api/games/{gid}/play").status_code == 409
    assert not (Path.home() / ".local/share/dolphin-emu/GameSettings/GHAE08.ini").exists()


@needs_7z
def test_remove_and_play_are_refused_while_a_pack_installs(client, tmp_path):
    gid = prepare(client, tmp_path)
    native_dolphin(client, tmp_path)
    dolphin.JOB.update(state="running", game_id="GHAE08")
    assert dolphin._pack_lock.acquire(blocking=False)
    try:
        assert client.delete(f"/api/games/{gid}/textures").status_code == 409
        assert client.post(f"/api/games/{gid}/play").status_code == 409
    finally:
        dolphin._pack_lock.release()


def test_removing_textures_is_refused_while_dolphin_is_open(client, tmp_path, monkeypatch):
    gid = prepare(client, tmp_path)
    native_dolphin(client, tmp_path)
    with monkeypatch.context() as m:
        m.setattr(dolphin, "is_running", lambda proc="/proc": True)
        assert client.delete(f"/api/games/{gid}/textures").status_code == 409


def test_play_with_the_exported_wrapper_and_a_gpu_choice_explains_what_to_change(client, tmp_path):
    gid = prepare(client, tmp_path)
    out = tmp_path / "out.json"
    wrapper = tmp_path / "org.DolphinEmu.dolphin-emu"
    wrapper.write_text(f"#!{sys.executable}\nimport sys\nopen(sys.argv[1], 'w').write('ran')\n")
    wrapper.chmod(0o755)
    client.put("/api/emulators", json={"platform": GC, "executable": str(wrapper), "args": [str(out), "{rom}"]})
    client.put("/api/dolphin/defaults", json={"gpu": "nvidia"})
    r = client.post(f"/api/games/{gid}/play")
    assert r.status_code == 409 and "flatpak" in r.json()["detail"] and not out.exists()


def test_info_survives_an_unreadable_pad_file(client, tmp_path):
    prepare(client, tmp_path)
    native_dolphin(client, tmp_path)
    cfg = Path.home() / ".config/dolphin-emu"
    cfg.mkdir(parents=True)
    (cfg / "GCPadNew.ini").write_bytes(b"[GCPad1]\nDevice = SDL/0/Pad\xe9\n")
    assert client.get("/api/dolphin/info").status_code == 200
