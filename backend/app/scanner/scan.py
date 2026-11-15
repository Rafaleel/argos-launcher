import os
import sqlite3

from app.scanner.dat import DatIndex, load_dats
from app.scanner.hashing import NES_HEADER, hash_file

EXTENSIONS = {
    ".nes", ".fds", ".sfc", ".smc", ".gb", ".gbc", ".gba", ".nds", ".n64", ".z64", ".v64",
    ".md", ".gen", ".smd", ".sms", ".gg", ".pce", ".a26", ".a78", ".lnx",
    ".iso", ".cue", ".bin", ".img", ".gcm",
}


def scan(conn: sqlite3.Connection, rom_dirs: list[str], dat_dirs: list[str]) -> dict:
    index, errors = load_dats(dat_dirs)
    seen: set[str] = set()
    ok_roots: list[str] = []
    hashed = cached = 0

    for root in rom_dirs:
        root = os.path.abspath(root)
        if not os.path.isdir(root):
            errors.append(f"ROM folder not found: {root}")
            continue
        ok_roots.append(root)
        for dirpath, _, names in os.walk(root):
            for name in sorted(names):
                if os.path.splitext(name)[1].lower() not in EXTENSIONS:
                    continue
                path = os.path.join(dirpath, name)
                if path in seen:
                    continue
                try:
                    if _refresh_file(conn, path):
                        hashed += 1
                    else:
                        cached += 1
                    seen.add(path)
                except OSError as exc:
                    errors.append(f"Cannot read {path}: {exc}")

    removed = _remove_vanished(conn, ok_roots, seen)
    games = _regroup(conn, index)
    conn.commit()
    return {
        "files_hashed": hashed,
        "files_cached": cached,
        "files_removed": removed,
        "games": games,
        "errors": errors,
    }


def _refresh_file(conn: sqlite3.Connection, path: str) -> bool:
    """Hash the file unless size and mtime match the stored row. True if hashed."""
    st = os.stat(path)
    row = conn.execute("SELECT size, mtime_ns FROM files WHERE path = ?", (path,)).fetchone()
    if row and row["size"] == st.st_size and row["mtime_ns"] == st.st_mtime_ns:
        return False
    h = hash_file(path)
    conn.execute(
        """INSERT INTO files (path, size, mtime_ns, crc32, sha1, crc32_nohdr, sha1_nohdr)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(path) DO UPDATE SET size = excluded.size, mtime_ns = excluded.mtime_ns,
             crc32 = excluded.crc32, sha1 = excluded.sha1,
             crc32_nohdr = excluded.crc32_nohdr, sha1_nohdr = excluded.sha1_nohdr""",
        (path, st.st_size, st.st_mtime_ns, h.crc32, h.sha1, h.crc32_nohdr, h.sha1_nohdr),
    )
    return True


def _remove_vanished(conn: sqlite3.Connection, ok_roots: list[str], seen: set[str]) -> int:
    # Only judge files under folders that exist now: an unmounted drive must
    # not wipe the library.
    removed = 0
    for row in conn.execute("SELECT id, path FROM files").fetchall():
        under_ok_root = any(row["path"].startswith(r + os.sep) for r in ok_roots)
        if under_ok_root and row["path"] not in seen:
            conn.execute("DELETE FROM files WHERE id = ?", (row["id"],))
            removed += 1
    return removed


def _regroup(conn: sqlite3.Connection, index: DatIndex) -> int:
    """Rebuild file -> game links from the stored hashes. Game ids stay stable."""
    for f in conn.execute("SELECT * FROM files").fetchall():
        match = index.find(f["sha1"], f["crc32"], f["size"])
        if not match and f["sha1_nohdr"]:
            match = index.find(f["sha1_nohdr"], f["crc32_nohdr"], f["size"] - NES_HEADER)
        if match:
            platform, title = match
            key, identified = f"dat:{platform}|{title}", 1
        else:
            platform, key, identified = None, f"path:{f['path']}", 0
            title = os.path.splitext(os.path.basename(f["path"]))[0]
        conn.execute(
            """INSERT INTO games (key, title, platform, identified) VALUES (?, ?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET title = excluded.title,
                 platform = excluded.platform, identified = excluded.identified""",
            (key, title, platform, identified),
        )
        game_id = conn.execute("SELECT id FROM games WHERE key = ?", (key,)).fetchone()["id"]
        conn.execute("UPDATE files SET game_id = ? WHERE id = ?", (game_id, f["id"]))
    conn.execute("DELETE FROM games WHERE id NOT IN (SELECT game_id FROM files WHERE game_id IS NOT NULL)")
    return conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]
