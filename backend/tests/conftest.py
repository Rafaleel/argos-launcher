import os
import pytest

from app.emulators import dolphin as _dolphin

REAL_IS_RUNNING = _dolphin.is_running  # the autouse fixture below replaces it in every test

from app.db import connect


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_DB", str(tmp_path / "test.db"))
    # Dolphin's folders hang off HOME: tests must never touch the real ones.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    yield
    # A test that called monkeypatch.undo() would point the next calls at the real files.
    assert os.environ.get("ARGOS_DB", "").startswith(str(tmp_path)), "test isolation was undone"
    assert os.environ.get("HOME") == str(tmp_path / "home"), "test isolation was undone"


@pytest.fixture
def conn():
    c = connect()
    yield c
    c.close()


def dat_xml(platform: str, games: list[tuple[str, list[tuple[str, int, str, str]]]]) -> str:
    """games: [(title, [(rom name, size, crc, sha1)])]"""
    body = ""
    for title, roms in games:
        rs = "".join(f'<rom name="{n}" size="{s}" crc="{c}" sha1="{h}"/>' for n, s, c, h in roms)
        body += f'<game name="{title}">{rs}</game>'
    return f'<?xml version="1.0"?><datafile><header><name>{platform}</name></header>{body}</datafile>'


@pytest.fixture(autouse=True)
def fast_monitors(monkeypatch):
    """Quick polling, and no monitor thread may outlive its test (it could
    otherwise touch another test's, or the user's, database)."""
    from app.sessions import tracker

    monkeypatch.setattr(tracker, "POLL", 0.05)
    monkeypatch.setattr(tracker, "BEAT", 0.3)
    yield
    for t in tracker.MONITORS:
        t.join(timeout=10)
    assert not any(t.is_alive() for t in tracker.MONITORS), "a session monitor is still running"
    tracker.MONITORS.clear()


@pytest.fixture(autouse=True)
def clean_dolphin_state(monkeypatch):
    """Dolphin helpers keep module state; tests must not depend on the machine's Dolphin."""
    from app.emulators import dolphin

    dolphin.gpu_names.cache_clear()
    dolphin.nvidia_flatpak_ready.cache_clear()
    dolphin.JOB.update(state="idle", message="", game_id=None)
    monkeypatch.setattr(dolphin, "is_running", lambda proc="/proc": False)  # a real Dolphin may be open
    yield
    for t in dolphin.MONITORS:
        t.join(timeout=30)
    dolphin.MONITORS.clear()


@pytest.fixture(autouse=True)
def no_installed_emulators(monkeypatch):
    """A scan auto-configures installed emulators: tests must not see the machine's Flatpaks or PATH."""
    from app.emulators import detect

    monkeypatch.setattr(detect, "candidates", lambda: [])


@pytest.fixture(autouse=True)
def no_presence_network(monkeypatch):
    """Rich presence polls start with every play of a linked game: never reach the real site."""
    from app.collectors import presence
    from app.collectors.retroachievements import RAError

    def offline(user, key):
        raise RAError("offline in tests")

    monkeypatch.setattr(presence, "fetch", offline)
    monkeypatch.setattr(presence.ra_sync, "auto_sync", lambda conn, game_id: False)  # no network at the end of a session
    monkeypatch.setattr(presence, "INTERVAL", 0.02)
    from app.collectors import retroachievements
    monkeypatch.setattr(retroachievements, "fetch_game_ttb", lambda *a, **k: None)
    yield
    for t in presence.POLLERS:
        t.join(timeout=10)
    assert not any(t.is_alive() for t in presence.POLLERS), "a presence poller is still running"
    presence.POLLERS.clear()


@pytest.fixture(autouse=True)
def no_ram_milestones(monkeypatch):
    """Every play of a Dolphin game would start a RAM poller and fetch rules: not in tests."""
    from app.collectors import ram_milestones

    monkeypatch.setattr(ram_milestones, "INTERVAL", 0.01)
    monkeypatch.setattr(ram_milestones, "start", lambda *a, **k: False)
    yield
