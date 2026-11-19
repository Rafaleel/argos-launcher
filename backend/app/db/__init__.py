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
CREATE TABLE IF NOT EXISTS milestones (
    id INTEGER PRIMARY KEY,
    game_id INTEGER NOT NULL REFERENCES games(id),
    position INTEGER NOT NULL,
    name TEXT NOT NULL
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
CREATE TABLE IF NOT EXISTS progress_estimates (
    id INTEGER PRIMARY KEY,
    game_id INTEGER NOT NULL REFERENCES games(id),
    timestamp TEXT NOT NULL,
    mean REAL NOT NULL,
    lower REAL NOT NULL,
    upper REAL NOT NULL
);
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
    return conn
