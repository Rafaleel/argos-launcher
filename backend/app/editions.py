"""Multi-disc editions: DAT entries that differ only by "(Disc N)" are one game in the UI.

Mirrors frontend/src/collection.ts: same platform, same title once the disc tag is removed.
"""
import re
import sqlite3

DISC = re.compile(r"\s*\(Disc (\d+)\)(?=(?:\s*\([^)]*\))*\s*$)", re.I | re.ASCII)  # ASCII: JS \d is 0-9 only


def disc_number(title: str) -> int:
    m = DISC.search(title)
    return int(m.group(1)) if m else 0


def edition_title(title: str) -> str:
    return DISC.sub("", title, count=1).strip()


def edition_ids(conn: sqlite3.Connection, game_id: int) -> list[int]:
    """Ids of every disc of the game's edition, disc order; just [game_id] for a single-disc game."""
    game = conn.execute("SELECT title, platform, identified FROM games WHERE id = ?", (game_id,)).fetchone()
    if game is None or not game["identified"] or not disc_number(game["title"]):
        return [game_id]
    base = DISC.sub("", game["title"], count=1).strip()  # JS String.replace changes the first match only
    rows = conn.execute("SELECT id, title FROM games WHERE identified = 1 AND platform IS ? AND title LIKE ?",
                        (game["platform"], "%(Disc %")).fetchall()
    same = [r for r in rows if DISC.sub("", r["title"], count=1).strip() == base and disc_number(r["title"])]
    return [r["id"] for r in sorted(same, key=lambda r: disc_number(r["title"]))] or [game_id]
