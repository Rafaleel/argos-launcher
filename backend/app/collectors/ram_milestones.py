"""Story milestones read from Dolphin's RAM while a game is played.

The milestones of a game come from its RetroAchievements set: the achievements typed progression or
win_condition (the catalog `ra_store` keeps), their rules from `r=patch` with the login token Dolphin holds,
and the "a game is being played" gate from the game's rich presence script. They are built once and kept in
`milestones`. Then, every INTERVAL seconds of a session, the flags are read from the emulator's RAM and a
`milestones` signal is stored whenever the set of reached ones changes. The flags are read as state: whether
they survive a loaded save is UNVERIFIED (issue #16).
"""
import sqlite3
import threading
import time
from pathlib import Path

from app import milestones
from app.collectors import ra_store, rich_presence
from app.collectors.base import store_signal
from app.collectors.presence import _ended
from app.collectors.retroachievements import RAError, fetch_patch
from app.config import db_path
from app.db import connect
from app.emulators import dolphin
from app.emulators.dolphin_memory import DolphinMemory, DolphinMemoryError

INTERVAL = 2.0
POLLERS: list[threading.Thread] = []  # tests join these
PROBLEMS: dict[int, str] = {}  # game id -> why the reader cannot work right now; the milestones endpoint shows it


def _cannot(game_id: int, why: str) -> list[dict]:
    PROBLEMS[game_id] = why
    return []


def ensure(conn: sqlite3.Connection, game_id: int, ra_id: int, install) -> list[dict]:
    """The stored milestones of the game, built first if there are none. [] when the game cannot be built:
    its achievements were never synced or none is typed progression, Dolphin has no RetroAchievements login, the
    site does not answer, the rich presence does not say when a game is being played, or no story achievement
    can be read from the RAM. The reason goes to PROBLEMS and nothing is stored; it is tried again next session.
    shortcut: stored rows are never rebuilt; to rebuild a game, delete its `milestones` rows."""
    items = milestones.load(conn, game_id)
    if items:
        return items
    catalog = ra_store.get_catalog(conn, ra_id)
    kinds = {a["id"]: a["type"] for a in catalog}
    if not catalog:
        return _cannot(game_id, "Sincronize as conquistas do jogo antes: o Argos usa o tipo delas (progressão) para montar os marcos.")
    if not any(k in milestones.STORY_KINDS for k in kinds.values()):
        return _cannot(game_id, "Este jogo não tem conquistas de progressão no RetroAchievements; o Argos ainda não monta marcos para ele.")
    login = dolphin.ra_login(install)
    if login is None:
        return _cannot(game_id, "O Dolphin não está logado no RetroAchievements; o Argos usa esse login para baixar a lista de marcos. "
                                "Entre nas conquistas do Dolphin, em Oficina.")
    try:
        patch = fetch_patch(ra_id, *login)
    except RAError as exc:
        return _cannot(game_id, str(exc))
    gate = rich_presence.in_game_gates(patch.get("RichPresencePatch"))
    if gate is None:
        return _cannot(game_id, "Não consegui descobrir, pelo rich presence do jogo, quando ele está em partida; sem isso o Argos não lê a memória.")
    items, undetectable = milestones.build(patch, kinds)
    if not items:
        return _cannot(game_id, "Nenhuma conquista de progressão deste jogo pode ser lida da memória.")
    milestones.save(conn, game_id, [{**m, "gates": [*m["gates"], *gate]} for m in items], undetectable)
    PROBLEMS.pop(game_id, None)
    return milestones.load(conn, game_id)


def _poll(db_file: Path, game_id: int, session_id: int, ra_id: int, code: str, install) -> None:
    conn = connect(db_file)
    mem = None
    last = None
    try:
        items = ensure(conn, game_id, ra_id, install)
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
            except ValueError:  # a rule or gate points past MEM1 (24 MB); it would fail every round
                PROBLEMS[game_id] = "Este jogo usa um endereço fora da RAM principal do GameCube; o Argos ainda não lê esse caso."
                break
            except OSError:
                if mem is not None:
                    mem.close()
                mem = None  # Dolphin closed or restarted: attach again next round
            if got is not None and got != last:
                try:
                    scenario, flags = got
                    group = [m for m in items if m["scenario"] == scenario]
                    reached = [m["name"] for m, hit in zip(group, flags) if hit]
                    store_signal(conn, game_id, "milestones",
                                 {"ra_id": ra_id, "scenario": scenario, "reached": reached, "total": len(group)}, session_id)
                    try:
                        from app import progress
                        progress.recompute(conn, game_id)
                    except sqlite3.Error:
                        pass
                    last = got
                except sqlite3.Error:
                    pass  # busy database: offered again next round
    finally:
        if mem is not None:
            mem.close()
        conn.close()


def start(conn: sqlite3.Connection, game_id: int, session_id: int, ra_id: int | None, code: str | None, install) -> bool:
    """Poll in the background for this session if the game is linked to RetroAchievements and its game code is known."""
    if ra_id is None or not code:
        return False
    # shortcut: a session split by a suspend ends this poller; the next play starts a new one (as in presence)
    t = threading.Thread(target=_poll, args=(db_path(), game_id, session_id, ra_id, code, install), daemon=True)
    t.start()
    POLLERS.append(t)
    return True
