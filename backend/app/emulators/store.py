import json
import sqlite3

from pydantic import ValidationError

from app.emulators.dolphin import VideoSettings, effective


def _load(raw: str | None) -> dict:
    """Stored JSON back to a clean dict; bad or old data reads as "no settings"."""
    try:
        return VideoSettings(**json.loads(raw or "{}")).model_dump(exclude_none=True)
    except (ValueError, ValidationError):
        return {}


def get_defaults(conn: sqlite3.Connection) -> dict:
    row = conn.execute("SELECT value FROM settings WHERE key = 'dolphin_defaults'").fetchone()
    return _load(row["value"] if row else None)


def set_defaults(conn: sqlite3.Connection, settings: VideoSettings) -> dict:
    data = settings.model_dump(exclude_none=True)
    conn.execute(
        "INSERT INTO settings (key, value) VALUES ('dolphin_defaults', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (json.dumps(data),),
    )
    conn.commit()
    return data


def get_game(conn: sqlite3.Connection, game_id: int) -> dict:
    row = conn.execute("SELECT data FROM game_profiles WHERE game_id = ?", (game_id,)).fetchone()
    return _load(row["data"] if row else None)


def set_game(conn: sqlite3.Connection, game_id: int, settings: VideoSettings) -> dict:
    data = settings.model_dump(exclude_none=True)
    conn.execute(
        "INSERT INTO game_profiles (game_id, data) VALUES (?, ?) "
        "ON CONFLICT(game_id) DO UPDATE SET data = excluded.data",
        (game_id, json.dumps(data)),
    )
    conn.commit()
    return data


def effective_for(conn: sqlite3.Connection, game_id: int) -> dict:
    return effective(get_defaults(conn), get_game(conn, game_id))
