"""Emulator detection. Flatpak and PATH are faked; nothing on the machine is consulted."""
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.emulators import detect
from app.emulators.detect import Candidate
from app.main import app
from tests.test_dolphin_api import GC, prepare

REAL_CANDIDATES = detect.candidates


def exe(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


@pytest.fixture
def machine(tmp_path, monkeypatch):
    """A fake machine: flatpak binary, installed app ids, RetroArch info files."""
    bins = tmp_path / "bin"
    flatpak = exe(bins / "flatpak")
    monkeypatch.setenv("PATH", str(bins))
    state = {"apps": set(), "location": tmp_path / "ra-app"}
    monkeypatch.setattr(detect, "flatpak_apps", lambda: frozenset(state["apps"]))
    monkeypatch.setattr(detect, "flatpak_location", lambda app: state["location"])
    monkeypatch.setattr(detect, "candidates", REAL_CANDIDATES)
    state["flatpak"], state["bins"] = flatpak, bins
    return state


def ra_core(name: str, database: str | None, info_in_app: Path | None = None) -> Path:
    cores = Path.home() / ".var/app/org.libretro.RetroArch/config/retroarch/cores"
    cores.mkdir(parents=True, exist_ok=True)
    so = cores / f"{name}_libretro.so"
    so.write_bytes(b"\x7fELF")
    if database is not None:
        info_dir = info_in_app or cores
        info_dir.mkdir(parents=True, exist_ok=True)
        (info_dir / f"{name}_libretro.info").write_text(f'display_name = "x"\ndatabase = "{database}"\n')
    return so


def test_nothing_installed_finds_nothing(machine):
    assert detect.candidates() == []


def test_flatpak_dolphin_gets_the_batch_template(machine):
    machine["apps"].add(detect.DOLPHIN_ID)
    [c] = detect.candidates()
    assert c.executable == machine["flatpak"] and c.args == ("run", detect.DOLPHIN_ID, "-b", "-e", "{rom}")
    assert GC in c.platforms


def test_native_dolphin_from_path(machine):
    path = exe(machine["bins"] / "dolphin-emu")
    [c] = detect.candidates()
    assert c.executable == path and c.args == ("-b", "-e", "{rom}")


def test_retroarch_cores_map_to_the_platforms_their_info_lists(machine):
    machine["apps"].add(detect.RETROARCH_ID)
    app_info = machine["location"] / "files/share/libretro/info"
    gb = ra_core("gambatte", "Nintendo - Game Boy|Nintendo - Game Boy Color", app_info)
    ra_core("mystery", None)  # no .info anywhere: skipped
    [c] = detect.candidates()
    assert c.platforms == ("Nintendo - Game Boy", "Nintendo - Game Boy Color")
    assert c.args == ("run", detect.RETROARCH_ID, "-L", str(gb), "{rom}")
    assert "gambatte" in c.name


def test_dedicated_emulator_beats_a_retroarch_core(machine):
    machine["apps"].update({detect.DOLPHIN_ID, detect.RETROARCH_ID})
    ra_core("dolphin", "Nintendo - GameCube|Nintendo - Wii")
    found = detect.candidates()
    assert len(found) == 2 and detect.best_for(GC, found).name == "Dolphin (Flatpak)"
    assert detect.best_for("Sega - Saturn", found) is None


# ---------------------------------------------------------------- API


@pytest.fixture
def client():
    return TestClient(app, base_url="http://127.0.0.1")


def test_scan_configures_a_missing_emulator_and_never_replaces_one(client, tmp_path, machine):
    machine["apps"].add(detect.DOLPHIN_ID)
    roms, dats = tmp_path / "roms", tmp_path / "dats"
    gid = prepare(client, tmp_path)  # prepare already scanned once
    assert client.get("/api/emulators").json() == [
        {"platform": GC, "executable": machine["flatpak"], "args": ["run", detect.DOLPHIN_ID, "-b", "-e", "{rom}"]}
    ]
    assert next(g for g in client.get("/api/games").json() if g["id"] == gid)["dolphin"] is True
    mine = exe(tmp_path / "mine" / "dolphin-emu")
    assert client.put("/api/emulators", json={"platform": GC, "executable": mine, "args": ["{rom}"]}).status_code == 200
    r = client.post("/api/scan").json()
    assert r["emulators_configured"] == []
    assert client.get("/api/emulators").json()[0]["executable"] == mine  # the user's choice stays


def test_scan_reports_what_it_configured(client, tmp_path, machine):
    prepare(client, tmp_path)
    assert client.get("/api/emulators").json() == []  # nothing installed: nothing configured
    machine["apps"].add(detect.DOLPHIN_ID)
    assert client.post("/api/scan").json()["emulators_configured"] == [{"platform": GC, "name": "Dolphin (Flatpak)"}]


def test_detected_lists_options_per_library_platform(client, tmp_path, machine):
    machine["apps"].update({detect.DOLPHIN_ID, detect.RETROARCH_ID})
    ra_core("dolphin", GC)
    prepare(client, tmp_path)
    opts = client.get("/api/emulators/detected").json()
    assert list(opts) == [GC] and [o["name"] for o in opts[GC]] == ["Dolphin (Flatpak)", "RetroArch (Flatpak) · dolphin"]
