import os
import stat
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from app.launcher.launch import launch
from app.sessions import tracker
from app.sessions.tracker import AlreadyPlaying, close_orphans, start_session


def script(tmp_path, body: str, name="emu"):
    exe = tmp_path / name
    exe.write_text(f"#!{sys.executable}\n{body}\n")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    return str(exe)


def add_game(conn, title="G"):
    cur = conn.execute("INSERT INTO games (key, title, platform, identified) VALUES (?, ?, 'P', 1)", (f"k:{title}", title))
    conn.commit()
    return cur.lastrowid


def sessions(conn):
    return conn.execute("SELECT * FROM sessions ORDER BY id").fetchall()


def wait_monitors():
    for t in list(tracker.MONITORS):
        t.join(timeout=10)


def test_session_lasts_while_the_emulator_runs_and_is_closed_after(conn, tmp_path):
    g = add_game(conn)
    exe = script(tmp_path, "import time; time.sleep(1.2)")
    t0 = time.time()
    start_session(conn, g, lambda: launch(exe, [], [exe]))
    wait_monitors()
    [s] = sessions(conn)
    assert s["ended_at"] is not None and time.time() - t0 >= 1.0
    assert s["last_heartbeat"] is not None


def test_wrapper_that_exits_at_once_does_not_end_the_session(conn, tmp_path):
    g = add_game(conn)
    # The parent exits immediately; the child it started keeps the Linux session alive.
    exe = script(tmp_path, 'import subprocess; subprocess.Popen(["/bin/sleep", "1.5"])')
    t0 = time.time()
    start_session(conn, g, lambda: launch(exe, [], [exe]))
    wait_monitors()
    assert time.time() - t0 >= 1.3
    assert sessions(conn)[0]["ended_at"] is not None


def test_heartbeat_advances_during_a_long_session(conn, tmp_path):
    g = add_game(conn)
    exe = script(tmp_path, "import time; time.sleep(2.4)")
    start_session(conn, g, lambda: launch(exe, [], [exe]))
    time.sleep(1.8)
    [s] = sessions(conn)
    assert s["ended_at"] is None and s["last_heartbeat"] > s["started_at"]
    wait_monitors()


def test_same_game_cannot_be_opened_twice_until_it_ends(conn, tmp_path):
    g = add_game(conn)
    exe = script(tmp_path, "import time; time.sleep(1)")
    start_session(conn, g, lambda: launch(exe, [], [exe]))
    with pytest.raises(AlreadyPlaying):
        start_session(conn, g, lambda: launch(exe, [], [exe]))
    wait_monitors()
    start_session(conn, g, lambda: launch(exe, [], [exe]))  # allowed again
    wait_monitors()
    assert len(sessions(conn)) == 2


def test_double_click_opens_exactly_one_emulator(tmp_path):
    from app.db import connect

    c0 = connect()
    g = add_game(c0)
    exe = script(tmp_path, "import time; time.sleep(1)")
    outcomes = []

    def click():
        c = connect()
        try:
            start_session(c, g, lambda: launch(exe, [], [exe]))
            outcomes.append("ok")
        except AlreadyPlaying:
            outcomes.append("blocked")
        finally:
            c.close()

    threads = [threading.Thread(target=click) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    wait_monitors()
    assert sorted(outcomes) == ["blocked"] * 3 + ["ok"]


def test_session_is_closed_even_if_the_process_is_already_gone(conn):
    g = add_game(conn)
    start_session(conn, g, lambda: 2_000_000_000)  # no such session id
    wait_monitors()
    assert sessions(conn)[0]["ended_at"] is not None


def test_orphan_sessions_close_at_their_last_heartbeat(conn):
    g = add_game(conn)
    conn.execute("INSERT INTO sessions (game_id, started_at, last_heartbeat) VALUES (?, '2026-01-01T10:00:00Z', '2026-01-01T10:30:00Z')", (g,))
    conn.execute("INSERT INTO sessions (game_id, started_at) VALUES (?, '2026-01-01T11:00:00Z')", (g,))
    conn.commit()
    assert close_orphans(conn) == 2
    a, b = sessions(conn)
    assert a["ended_at"] == "2026-01-01T10:30:00Z" and b["ended_at"] == "2026-01-01T11:00:00Z"


def test_suspend_is_not_counted_as_play_time(conn, tmp_path, monkeypatch):
    g = add_game(conn)
    real = tracker.utc_now
    calls = {"n": 0}

    def jumping_now():
        calls["n"] += 1
        # from the 6th call on, the clock is 3 hours ahead: the laptop slept
        return real() + (timedelta(hours=3) if calls["n"] > 6 else timedelta())

    exe = script(tmp_path, "import time; time.sleep(1.5)")
    monkeypatch.setattr(tracker, "utc_now", jumping_now)
    start_session(conn, g, lambda: launch(exe, [], [exe]))
    wait_monitors()
    first, second = sessions(conn)
    assert first["ended_at"] is not None and second["ended_at"] is not None
    gap = datetime.fromisoformat(second["started_at"].replace("Z", "+00:00")) - datetime.fromisoformat(first["ended_at"].replace("Z", "+00:00"))
    assert gap >= timedelta(hours=2, minutes=59)  # the sleep sits between the sessions, in neither


def test_busy_heartbeat_does_not_kill_the_monitor(conn, tmp_path, monkeypatch):
    g = add_game(conn)
    exe = script(tmp_path, "import time; time.sleep(1.5)")
    start_session(conn, g, lambda: launch(exe, [], [exe]))
    # hold the write lock for a moment, as a long scan would
    blocker = __import__("sqlite3").connect(os.environ["ARGOS_DB"], timeout=0)
    blocker.execute("BEGIN IMMEDIATE")
    time.sleep(0.6)
    blocker.rollback()
    blocker.close()
    wait_monitors()
    assert sessions(conn)[0]["ended_at"] is not None


def test_late_heartbeat_does_not_touch_a_closed_session(conn, tmp_path):
    # Happens when a second backend sweeps the session while the first monitor still runs.
    g = add_game(conn)
    exe = script(tmp_path, "import time; time.sleep(2)")
    start_session(conn, g, lambda: launch(exe, [], [exe]))
    close_orphans(conn)
    closed = sessions(conn)[0]
    time.sleep(1.2)  # several beats pass (BEAT is 0.3 s in tests)
    after = sessions(conn)[0]
    assert after["ended_at"] == closed["ended_at"] and after["last_heartbeat"] == closed["last_heartbeat"]
    wait_monitors()


def test_clock_stepping_back_never_records_a_negative_session(conn, tmp_path, monkeypatch):
    g = add_game(conn)
    real = tracker.utc_now
    calls = {"n": 0}

    def stepping_back():
        calls["n"] += 1
        return real() - (timedelta(hours=2) if calls["n"] > 4 else timedelta())

    exe = script(tmp_path, "import time; time.sleep(1.2)")
    monkeypatch.setattr(tracker, "utc_now", stepping_back)
    start_session(conn, g, lambda: launch(exe, [], [exe]))
    wait_monitors()
    [row] = sessions(conn)  # raw row: the stats code would hide a bad one by clamping
    assert row["ended_at"] >= row["started_at"]
