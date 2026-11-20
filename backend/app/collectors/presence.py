"""RetroAchievements rich presence: where the player is, as the emulator reports it to RA.

While Dolphin is logged in to RA it sends a line built from the game's RAM by the game's rich
presence script (verified for RE2 GameCube: "On the Title Screen"). The Web API returns the
user's latest line with the game id and time, so polling it during an Argos session records the
player's path through the game with no access to the emulator's memory.

The line belongs to the user, not to the game: it is only kept when its game is the one linked
and it was sent after this session started. RichPresenceMsgDate is UTC (checked against a real
sample). Only changes are stored, as `presence` signals of the session.
"""
import sqlite3
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from app.collectors import ra_store
from app.collectors.base import store_signal
from app.collectors.retroachievements import BASE, RAError, get_json
from app.config import db_path
from app.db import connect

INTERVAL = 60.0  # RA refreshes the line every couple of minutes; polling faster only costs requests
POLLERS: list[threading.Thread] = []  # tests join these


def fetch(user: str, key: str) -> dict:
    """{"game": id or None, "message": text or None, "at": UTC datetime or None}."""
    query = urllib.parse.urlencode({"y": key, "u": user, "g": 1, "a": 0})
    try:
        data = get_json(f"{BASE}API_GetUserSummary.php?{query}")
    except RAError as exc:
        raise RAError(str(exc).replace(key, "•••")) from None
    if not isinstance(data, dict):
        raise RAError("Resposta inesperada do RetroAchievements.")
    msg, game, when = data.get("RichPresenceMsg"), data.get("LastGameID"), data.get("RichPresenceMsgDate")
    try:
        at = datetime.strptime(when, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc) if isinstance(when, str) else None
    except ValueError:
        at = None
    return {
        "game": game if isinstance(game, int) and not isinstance(game, bool) else None,
        "message": msg.strip()[:200] if isinstance(msg, str) and msg.strip() else None,
        "at": at,
    }


def accept(p: dict, ra_id: int, since: datetime) -> str | None:
    """The line, if it is about this game and newer than the session start."""
    if p["game"] != ra_id or p["message"] is None or p["at"] is None or p["at"] < since:
        return None
    return p["message"]


def _open(conn: sqlite3.Connection, session_id: int) -> bool:
    row = conn.execute("SELECT ended_at FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return row is not None and row["ended_at"] is None


def _poll(db_file: Path, game_id: int, session_id: int, user: str, key: str, ra_id: int, since: datetime) -> None:
    conn = connect(db_file)
    last = None
    try:
        while True:
            still_open = _open(conn, session_id)
            time.sleep(INTERVAL)  # the first line arrives a while after the game boots
            try:
                p = fetch(user, key)
            except RAError:
                p = None  # offline or refused: try again next round
            msg = accept(p, ra_id, since) if p else None
            if msg and msg != last:
                store_signal(conn, game_id, "presence", {"ra_id": ra_id, "message": msg, "at": p["at"].strftime("%Y-%m-%dT%H:%M:%SZ")}, session_id)
                last = msg
            # shortcut: a session split by a suspend ends this poller; the next play starts a new one
            if not still_open:
                break  # one more read after the end catches the last line
    finally:
        conn.close()


def start(conn: sqlite3.Connection, game_id: int, session_id: int, since: datetime) -> bool:
    """Poll in the background for this session if the game is linked and the key is set."""
    creds, ra_id = ra_store.get_credentials(conn), ra_store.get_ra_id(conn, game_id)
    if creds is None or ra_id is None:
        return False
    t = threading.Thread(target=_poll, args=(db_path(), game_id, session_id, creds[0], creds[1], ra_id, since), daemon=True)
    t.start()
    POLLERS.append(t)
    return True
