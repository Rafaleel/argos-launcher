import os
import pytest

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
