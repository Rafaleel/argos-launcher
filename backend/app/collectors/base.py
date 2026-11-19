"""Signal collectors: each one turns an outside source into rows of the `signals` table.

Raw signals are always kept, so the progress filter of phase 5 can be re-run on the history.
"""
import json
import sqlite3
from typing import Protocol

from app.sessions.tracker import iso, utc_now


class Collector(Protocol):
    name: str

    def collect(self, conn: sqlite3.Connection, game_id: int) -> dict | None:
        """Fetch the source for this game and store a signal. None if the source has nothing."""


def store_signal(conn: sqlite3.Connection, game_id: int, kind: str, payload: dict, session_id: int | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO signals (game_id, session_id, type, payload, timestamp) VALUES (?, ?, ?, ?, ?)",
        (game_id, session_id, kind, json.dumps(payload), iso(utc_now())),
    )
    conn.commit()
    return cur.lastrowid


def latest_signal(conn: sqlite3.Connection, game_id: int, kind: str) -> dict | None:
    row = conn.execute(
        "SELECT payload, timestamp FROM signals WHERE game_id = ? AND type = ? ORDER BY id DESC LIMIT 1",
        (game_id, kind),
    ).fetchone()
    if row is None:
        return None
    try:
        return {**json.loads(row["payload"]), "synced_at": row["timestamp"]}
    except ValueError:
        return None
