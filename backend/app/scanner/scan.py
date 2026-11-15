import os
import re
import sqlite3

from app.scanner.dat import DatIndex, load_dats
from app.scanner.hashing import NES_HEADER, hash_file

EXTENSIONS = {
    ".nes", ".fds", ".sfc", ".smc", ".gb", ".gbc", ".gba", ".nds", ".n64", ".z64", ".v64",
    ".md", ".gen", ".smd", ".sms", ".gg", ".pce", ".a26", ".a78", ".lnx",
    ".iso", ".cue", ".bin", ".img", ".gcm",
    # Not identifiable in phase 1 (hash differs from the DAT), but listed as unidentified.
    ".zip", ".7z", ".chd", ".rvz",
}


def printable(path: str) -> str:
    """Make a path safe to put in a JSON message (names may hold undecodable bytes)."""
    return os.fsencode(path).decode("utf-8", "replace")


def scan(conn: sqlite3.Connection, rom_dirs: list[str], dat_dirs: list[str]) -> dict:
    index, errors = load_dats(dat_dirs)
    seen: set[str] = set()
    protected: list[str] = []  # folders whose missing files must NOT be deleted
    healthy: list[str] = []
    empty: list[str] = []
    hashed = cached = 0

    for configured in rom_dirs:
        root = os.path.realpath(configured)
        if not os.path.isdir(root):
            errors.append(f"ROM folder not found: {printable(root)}")
            protected.append(root)
            continue
        found_here = 0
        unreadable: list[str] = []

        def on_error(exc: OSError) -> None:
            unreadable.append(exc.filename)
            errors.append(f"Cannot read folder {printable(str(exc.filename))}: {exc.strerror}")

        for dirpath, _, names in os.walk(root, onerror=on_error):
            for name in sorted(names):
                if os.path.splitext(name)[1].lower() not in EXTENSIONS:
                    continue
                path = os.path.join(dirpath, name)
                try:
                    path.encode("utf-8")  # SQLite cannot store undecodable names
                except UnicodeEncodeError:
                    errors.append(f"Skipped file with a non-UTF-8 name in {printable(dirpath)}")
                    continue
                found_here += 1  # counts files already seen via an overlapping root too
                if path in seen:
                    continue
                try:
                    if _refresh_file(conn, path):
                        hashed += 1
                    else:
                        cached += 1
                    seen.add(path)
                except OSError as exc:
                    errors.append(f"Cannot read {printable(path)}: {exc.strerror}")
        protected += unreadable
        if found_here:
            healthy.append(root)
        elif _has_files_under(conn, root):
            empty.append(root)
    # An existing but empty folder is most likely an unmounted drive, unless a
    # healthy folder that contains it already vouches for its files.
    for root in empty:
        if not any(root == h or root.startswith(h + os.sep) for h in healthy):
            protected.append(root)
            errors.append(f"{printable(root)} is empty now; kept its games. Remove the folder from the settings to clear them.")

    removed = _remove_vanished(conn, protected, seen)
    games = _regroup(conn, index)
    conn.commit()
    return {
        "files_hashed": hashed,
        "files_cached": cached,
        "files_removed": removed,
        "games": games,
        "errors": errors,
    }


def _has_files_under(conn: sqlite3.Connection, root: str) -> bool:
    return any(r["path"].startswith(root + os.sep) for r in conn.execute("SELECT path FROM files"))


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
    conn.commit()  # short write lock: settings can be saved while a scan runs
    return True


def _remove_vanished(conn: sqlite3.Connection, protected: list[str], seen: set[str]) -> int:
    """Drop rows the scan did not see, except under folders we could not judge
    (missing, unreadable or suspiciously empty). Rows under folders that left
    the settings are dropped too: the settings define the library."""
    removed = 0
    for row in conn.execute("SELECT id, path FROM files").fetchall():
        path = row["path"]
        if path in seen or any(path == p or path.startswith(p + os.sep) for p in protected):
            continue
        conn.execute("DELETE FROM files WHERE id = ?", (row["id"],))
        removed += 1
    return removed


CUE_FILE = re.compile(r'^\s*FILE\s+(?:"([^"]+)"|(\S+))', re.IGNORECASE | re.MULTILINE)


def _cue_tracks(cue_path: str) -> list[str]:
    try:
        with open(cue_path, "rb") as f:
            text = f.read(1024 * 1024).decode("latin-1")
    except OSError:
        return []
    base = os.path.dirname(cue_path)
    return [os.path.normpath(os.path.join(base, m.group(1) or m.group(2))) for m in CUE_FILE.finditer(text)]


def _regroup(conn: sqlite3.Connection, index: DatIndex) -> int:
    """Rebuild file -> game links from the stored hashes. Game ids stay stable."""
    files = conn.execute("SELECT * FROM files").fetchall()
    group: dict[str, tuple[str, str, str | None, int]] = {}  # path -> (key, title, platform, identified)
    for f in files:
        match = index.find(f["sha1"], f["crc32"], f["size"])
        if not match and f["sha1_nohdr"]:
            match = index.find(f["sha1_nohdr"], f["crc32_nohdr"], f["size"] - NES_HEADER)
        if match:
            platform, title = match
            group[f["path"]] = (f"dat:{platform}|{title}", title, platform, 1)
        else:
            title = os.path.splitext(os.path.basename(f["path"]))[0]
            group[f["path"]] = (f"path:{f['path']}", title, None, 0)

    # A .cue edited by the user no longer matches the DAT: join it to its tracks.
    for path in sorted(p for p, g in group.items() if p.lower().endswith(".cue") and not g[3]):
        tracks = [t for t in _cue_tracks(path) if t in group]
        known = next((group[t] for t in tracks if group[t][3]), None)
        if known:
            group[path] = known
        else:
            for t in tracks:
                group[t] = group[path]

    for f in files:
        key, title, platform, identified = group[f["path"]]
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
