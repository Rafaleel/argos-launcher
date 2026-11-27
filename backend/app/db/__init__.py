import os
import sqlite3
from pathlib import Path

from app.config import db_path

# Tables for later phases (sessions, signals, ...) exist so the design stays
# whole; phase 1 only uses settings, games, files and emulators.
SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    platform TEXT,
    identified INTEGER NOT NULL,
    cover TEXT
);
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    game_id INTEGER REFERENCES games(id) ON DELETE SET NULL,
    path TEXT NOT NULL UNIQUE,
    size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    crc32 TEXT NOT NULL,
    sha1 TEXT NOT NULL,
    crc32_nohdr TEXT,
    sha1_nohdr TEXT
);
CREATE TABLE IF NOT EXISTS emulators (
    id INTEGER PRIMARY KEY,
    platform TEXT NOT NULL UNIQUE,
    executable TEXT NOT NULL,
    args TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY,
    game_id INTEGER NOT NULL REFERENCES games(id),
    started_at TEXT NOT NULL,
    ended_at TEXT,
    last_heartbeat TEXT
);
CREATE TABLE IF NOT EXISTS ra_achievements (
    ra_id INTEGER NOT NULL,
    achievement_id INTEGER NOT NULL,
    position INTEGER NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    points INTEGER NOT NULL,
    kind TEXT NOT NULL,
    PRIMARY KEY (ra_id, achievement_id)
);
CREATE TABLE IF NOT EXISTS milestones (
    id INTEGER PRIMARY KEY,
    game_id INTEGER NOT NULL REFERENCES games(id),
    position INTEGER NOT NULL,
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS milestone_groups (
    game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    scenario TEXT NOT NULL,
    position INTEGER NOT NULL,
    undetectable INTEGER NOT NULL,
    PRIMARY KEY (game_id, scenario)
);
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY,
    game_id INTEGER NOT NULL REFERENCES games(id),
    session_id INTEGER REFERENCES sessions(id),
    type TEXT NOT NULL,
    payload TEXT NOT NULL,
    timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_game ON sessions(game_id, ended_at);
CREATE INDEX IF NOT EXISTS idx_files_game ON files(game_id);
CREATE TABLE IF NOT EXISTS game_profiles (
    game_id INTEGER PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ra_games (
    game_id INTEGER PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,
    ra_id INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_signals_game ON signals(game_id, type, id);
CREATE TABLE IF NOT EXISTS game_progress_config (
    game_id INTEGER PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,
    ttb_hours REAL,
    source TEXT
);
CREATE TABLE IF NOT EXISTS progress_estimates (
    id INTEGER PRIMARY KEY,
    game_id INTEGER NOT NULL REFERENCES games(id),
    timestamp TEXT NOT NULL,
    mean REAL NOT NULL,
    lower REAL NOT NULL,
    upper REAL NOT NULL,
    scenario TEXT,
    sources TEXT,
    details TEXT
);
CREATE INDEX IF NOT EXISTS idx_progress_game ON progress_estimates(game_id, id);
"""


BUSY_TIMEOUT = 5.0  # seconds a writer waits for the lock (tests shorten it)


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(path) if path else db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # FastAPI opens the connection in one worker thread and runs the endpoint in
    # another; a request uses it from one thread at a time.
    conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    migrated = False
    have = {r["name"] for r in conn.execute("PRAGMA table_info(milestones)")}
    for col, kind in (("ra_achievement_id", "INTEGER"), ("address", "INTEGER"), ("size", "TEXT"), ("value", "INTEGER"), ("gates", "TEXT"), ("scenario", "TEXT"), ("kind", "TEXT")):
        if col not in have:  # the table predates the RAM reader or phase 5
            conn.execute(f"ALTER TABLE milestones ADD COLUMN {col} {kind}")
            migrated = True
    if "kind" not in have:
        conn.execute(
            """UPDATE milestones SET kind = COALESCE(
                   (SELECT a.kind FROM ra_games r JOIN ra_achievements a
                    ON a.ra_id = r.ra_id AND a.achievement_id = milestones.ra_achievement_id
                    WHERE r.game_id = milestones.game_id LIMIT 1),
                   'progression'
               ) WHERE kind IS NULL"""
        )
        migrated = True
    pe_have = {r["name"] for r in conn.execute("PRAGMA table_info(progress_estimates)")}
    for col, kind in (("scenario", "TEXT"), ("sources", "TEXT"), ("details", "TEXT")):
        if col not in pe_have:
            conn.execute(f"ALTER TABLE progress_estimates ADD COLUMN {col} {kind}")
            migrated = True
    cfg_have = {r["name"] for r in conn.execute("PRAGMA table_info(game_progress_config)")}
    if "source" not in cfg_have:
        conn.execute("ALTER TABLE game_progress_config ADD COLUMN source TEXT")
        migrated = True
    if migrated:
        conn.commit()
    for suffix in ("", "-wal", "-shm"):  # the database holds the RetroAchievements key, and the WAL holds the same data as the database
        try:
            os.chmod(f"{path}{suffix}", 0o600)
        except OSError:
            pass  # that file does not exist (yet)
    return conn
