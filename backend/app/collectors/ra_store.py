import sqlite3


def get_credentials(conn: sqlite3.Connection) -> tuple[str, str] | None:
    rows = dict(conn.execute("SELECT key, value FROM settings WHERE key IN ('ra_user', 'ra_key')").fetchall())
    user, key = rows.get("ra_user", "").strip(), rows.get("ra_key", "").strip()
    return (user, key) if user and key else None


def get_user(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = 'ra_user'").fetchone()
    return row["value"] if row else ""


def set_credentials(conn: sqlite3.Connection, user: str, key: str | None) -> None:
    """The key is write-only: None keeps the stored one, "" removes it."""
    conn.execute(
        "INSERT INTO settings (key, value) VALUES ('ra_user', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (user.strip(),),
    )
    if key is not None:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('ra_key', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key.strip(),),
        )
    conn.commit()


def get_ra_id(conn: sqlite3.Connection, game_id: int) -> int | None:
    row = conn.execute("SELECT ra_id FROM ra_games WHERE game_id = ?", (game_id,)).fetchone()
    return row["ra_id"] if row else None


def set_ra_id(conn: sqlite3.Connection, game_id: int, ra_id: int | None) -> None:
    if ra_id is None:
        conn.execute("DELETE FROM ra_games WHERE game_id = ?", (game_id,))
    else:
        conn.execute(
            "INSERT INTO ra_games (game_id, ra_id) VALUES (?, ?) ON CONFLICT(game_id) DO UPDATE SET ra_id = excluded.ra_id",
            (game_id, ra_id),
        )
    conn.commit()


def save_catalog(conn: sqlite3.Connection, ra_id: int, items: list[dict]) -> None:
    """The achievements of a set (title, what to do, points), replaced on every sync. Shared by every disc of it."""
    with conn:
        conn.execute("DELETE FROM ra_achievements WHERE ra_id = ?", (ra_id,))
        conn.executemany(
            "INSERT OR REPLACE INTO ra_achievements (ra_id, achievement_id, position, title, description, points, kind)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(ra_id, a["id"], i, a["title"], a["description"], a["points"], a["type"]) for i, a in enumerate(items)])


def get_catalog(conn: sqlite3.Connection, ra_id: int) -> list[dict]:
    rows = conn.execute("SELECT achievement_id, title, description, points, kind FROM ra_achievements WHERE ra_id = ? ORDER BY position", (ra_id,))
    return [{"id": r["achievement_id"], "title": r["title"], "description": r["description"], "points": r["points"], "type": r["kind"]} for r in rows]
