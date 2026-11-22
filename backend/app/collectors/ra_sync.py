"""One RetroAchievements sync of a game, shared by the sync button and the end of a play session."""
import sqlite3
import threading

from app.collectors import ra_store
from app.collectors.base import store_signal
from app.collectors.retroachievements import RAError, RetroAchievementsCollector
from app.editions import edition_ids

LOCK = threading.Lock()  # one sync at a time: the API asks for reasonable use


def sync(conn: sqlite3.Connection, game_id: int) -> dict | None:
    """Fetch the game's progress and store it for every disc linked to the same set. Raises RAError.
    None when there are no credentials or no link."""
    payload = RetroAchievementsCollector().collect(conn, game_id)
    ra_id = ra_store.get_ra_id(conn, game_id)
    for disc in edition_ids(conn, game_id):  # one answer covers every disc linked to the same set
        if disc != game_id and payload and ra_store.get_ra_id(conn, disc) == ra_id:
            store_signal(conn, disc, "achievements", payload)
    return payload


def auto_sync(conn: sqlite3.Connection, game_id: int) -> bool:
    """The sync that runs when a session ends. Quiet: skips when another sync runs, and a failure (offline, a
    refused key) leaves the old numbers; the button still works. True if it synced."""
    if not LOCK.acquire(blocking=False):
        return False
    try:
        return sync(conn, game_id) is not None
    except (RAError, sqlite3.Error):
        return False
    finally:
        LOCK.release()
