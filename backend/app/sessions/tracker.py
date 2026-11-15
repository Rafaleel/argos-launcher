import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from app.config import db_path
from app.db import connect

POLL = 1.0  # seconds between process checks
BEAT = 15.0  # seconds between heartbeat writes
GAP = 60.0  # a loop that stalls longer than this means the machine was suspended

_play_lock = threading.Lock()
MONITORS: list[threading.Thread] = []  # tests join these


class AlreadyPlaying(Exception):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def session_alive(sid: int) -> bool:
    """True while any live process belongs to Linux session `sid`.

    The launcher starts the emulator with start_new_session, so the session id
    equals the launched pid. Wrappers (scripts, Flatpak) may exit at once while
    the emulator they started keeps running in the same session.
    """
    for entry in os.scandir("/proc"):
        if not entry.name.isdigit():
            continue
        try:
            with open(f"/proc/{entry.name}/stat") as f:
                # "pid (comm) state ppid pgrp session ..." and comm may hold spaces/parens
                fields = f.read().rpartition(")")[2].split()
        except OSError:
            continue
        if fields[0] != "Z" and int(fields[3]) == sid:
            return True
    return False


def start_session(conn: sqlite3.Connection, game_id: int, launch_fn) -> tuple[int, int]:
    """Launch the game and record a session. Returns (pid, session id)."""
    # One lock for check + launch + insert: a double click must not open two emulators.
    with _play_lock:
        if conn.execute("SELECT 1 FROM sessions WHERE game_id = ? AND ended_at IS NULL", (game_id,)).fetchone():
            raise AlreadyPlaying()
        # Record first: if the database is busy we fail before an emulator exists,
        # instead of leaving an untracked emulator that can be opened again.
        now = iso(utc_now())
        session_id = conn.execute(
            "INSERT INTO sessions (game_id, started_at, last_heartbeat) VALUES (?, ?, ?)", (game_id, now, now)
        ).lastrowid
        conn.commit()
        try:
            pid = launch_fn()
        except BaseException:
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            conn.commit()
            raise
    # Bind the database now, so a monitor outliving its caller never reopens another file.
    thread = threading.Thread(target=_monitor, args=(db_path(), session_id, game_id, pid), daemon=True)
    thread.start()
    MONITORS.append(thread)
    return pid, session_id


def close_orphans(conn: sqlite3.Connection) -> int:
    """Close sessions left open by a crash, at their last heartbeat."""
    cur = conn.execute(
        "UPDATE sessions SET ended_at = COALESCE(last_heartbeat, started_at) WHERE ended_at IS NULL"
    )
    conn.commit()
    return cur.rowcount


def _write(conn: sqlite3.Connection, sql: str, params: tuple, tries: int) -> bool:
    for attempt in range(tries):
        try:
            conn.execute(sql, params)
            conn.commit()
            return True
        except sqlite3.Error:
            if attempt + 1 < tries:
                time.sleep(0.5)
    return False


def _end(conn: sqlite3.Connection, session_id: int, when: datetime) -> None:
    _write(conn, "UPDATE sessions SET ended_at = ? WHERE id = ? AND ended_at IS NULL", (iso(when), session_id), 20)


def _begin(conn: sqlite3.Connection, game_id: int, when: datetime) -> int | None:
    try:
        cur = conn.execute(
            "INSERT INTO sessions (game_id, started_at, last_heartbeat) VALUES (?, ?, ?)",
            (game_id, iso(when), iso(when)),
        )
        conn.commit()
        return cur.lastrowid
    except sqlite3.Error:
        return None


def _open_db(db_file: Path) -> sqlite3.Connection | None:
    for _ in range(10):
        try:
            return connect(db_file)
        except sqlite3.Error:
            time.sleep(0.5)
    return None


def _monitor(db_file: Path, session_id: int | None, game_id: int, sid: int) -> None:
    conn = _open_db(db_file)
    if conn is None:
        return  # the orphan sweep at the next start closes the session
    try:
        last_seen = last_beat = utc_now()
        while session_alive(sid):
            time.sleep(POLL)
            # shortcut: a clock stepped back freezes the count until it catches up
            # (time is lost, never invented); revisit if NTP steps become common.
            now = max(utc_now(), last_seen)
            if (now - last_seen).total_seconds() > GAP:
                # Suspended: do not count the sleep as play time.
                _end(conn, session_id, last_seen)
                session_id = None
                if not session_alive(sid):
                    break
                session_id = _begin(conn, game_id, now)
                if session_id is None:
                    break
                last_beat = now
            last_seen = now
            if (now - last_beat).total_seconds() >= BEAT:
                # A busy database just skips this beat; it must not end the monitor.
                _write(conn, "UPDATE sessions SET last_heartbeat = ? WHERE id = ? AND ended_at IS NULL", (iso(now), session_id), 1)
                last_beat = now
    finally:
        if session_id is not None:
            _end(conn, session_id, max(utc_now(), last_seen))
        conn.close()
