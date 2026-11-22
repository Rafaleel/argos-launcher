"""Story milestones read from Dolphin's RAM while a game is played.

For a game with a hand-picked story (STORIES) the rules come from RetroAchievements once, using the
login token Dolphin holds, and are kept in `milestones`. Then, every INTERVAL seconds of a session, the
flags are read from the emulator's RAM and a `milestones` signal is stored whenever the set of reached
ones changes. The flags are read as state: whether they survive a loaded save is UNVERIFIED (issue #16).
"""
import sqlite3
import threading
import time
from pathlib import Path

from app import milestones
from app.collectors.base import store_signal
from app.collectors.presence import _ended
from app.collectors.retroachievements import RAError, fetch_patch
from app.config import db_path
from app.db import connect
from app.emulators import dolphin
from app.emulators.dolphin_memory import DolphinMemory, DolphinMemoryError

INTERVAL = 2.0
POLLERS: list[threading.Thread] = []  # tests join these
# shortcut: one game picked by hand (RE2 GameCube, Leon A scenario); the optional side events are left out.
# RetroAchievements game id -> (achievement description prefix, achievement ids to skip). Add a game by hand.
# Third element: the bits that say a game is being played, from RA's own rich presence script for RE2
# (`0xS163DA4=0` is "On the Title Screen", `0xR163DA6=1` is "Watching a demo"). Without them the zeroed RAM of
# the title screen reads as "scenario 0, nothing reached" and every quit to title would store an empty set.
PROBLEMS: dict[int, str] = {}  # game id -> why the reader cannot work right now; the milestones endpoint shows it
STORIES = {3176: ("[Leon A]", frozenset({439337, 439550}), ((0x163DA4, "S", 1), (0x163DA6, "R", 0)))}


def ensure(conn: sqlite3.Connection, game_id: int, ra_id: int, install) -> list[dict]:
    """The stored milestones of the game, fetched first if there are none. [] when there is no story for the
    game, Dolphin has no RetroAchievements login, or the site does not answer (tried again next session).
    shortcut: stored rows are never rebuilt; if a story's prefix or skip list changes, delete that game's
    `milestones` rows. The reason for [] (no login, expired token, site down) goes to PROBLEMS."""
    if ra_id not in STORIES:
        return []
    items = milestones.load(conn, game_id)
    if items:
        return items
    login = dolphin.ra_login(install)
    if login is None:
        PROBLEMS[game_id] = ("O Dolphin não está logado no RetroAchievements; o Argos usa esse login para baixar a lista de marcos. "
                             "Entre nas conquistas do Dolphin, em Oficina.")
        return []
    try:
        patch = fetch_patch(ra_id, *login)
    except RAError as exc:
        PROBLEMS[game_id] = str(exc)
        return []
    PROBLEMS.pop(game_id, None)
    prefix, skip, _ = STORIES[ra_id]
    items = milestones.build(patch, prefix, skip)
    milestones.save(conn, game_id, items)
    return milestones.load(conn, game_id)


def _poll(db_file: Path, game_id: int, session_id: int, ra_id: int, code: str, install) -> None:
    conn = connect(db_file)
    mem = None
    last = None
    try:
        in_game = STORIES[ra_id][2]  # in memory only, so editing STORIES needs no rebuild of the stored rows
        items = [{**m, "gates": m["gates"] + list(in_game)} for m in ensure(conn, game_id, ra_id, install)]
        while items and _ended(conn, session_id) is None:
            time.sleep(INTERVAL)
            got = None
            try:
                mem = mem or DolphinMemory.attach()
                if mem is not None:
                    PROBLEMS.pop(game_id, None)  # the RAM is reachable now, whatever the game is doing
                    # the RAM of whatever game Dolphin has open: a different game would mean different addresses
                    opened = mem.read(0, 6)
                    if opened == code.encode():
                        got = milestones.read(items, mem.read)
                    elif any(opened):  # all zeros is normal while Dolphin boots
                        PROBLEMS[game_id] = f"O Dolphin está com outro jogo aberto ({opened.decode('ascii', 'replace')})."
            except DolphinMemoryError as exc:
                PROBLEMS[game_id] = str(exc)  # Dolphin is open but its RAM cannot be read
            except OSError:
                if mem is not None:
                    mem.close()
                mem = None  # Dolphin closed or restarted: attach again next round
            if got is not None and got != last:
                try:
                    reached = [m["name"] for m, hit in zip(items, got) if hit]
                    store_signal(conn, game_id, "milestones", {"ra_id": ra_id, "reached": reached, "total": len(items)}, session_id)
                    last = got
                except sqlite3.Error:
                    pass  # busy database: offered again next round
    finally:
        if mem is not None:
            mem.close()
        conn.close()


def start(conn: sqlite3.Connection, game_id: int, session_id: int, ra_id: int | None, code: str | None, install) -> bool:
    """Poll in the background for this session if the game has a story and its game id is known."""
    if ra_id not in STORIES or not code:
        return False
    # shortcut: a session split by a suspend ends this poller; the next play starts a new one (as in presence)
    t = threading.Thread(target=_poll, args=(db_path(), game_id, session_id, ra_id, code, install), daemon=True)
    t.start()
    POLLERS.append(t)
    return True
