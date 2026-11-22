import os
import sqlite3
import threading
import time

from fastapi import APIRouter, HTTPException
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from app import milestones
from app.api import Conn
from app.collectors import ra_store, ra_sync, ram_milestones
from app.collectors.base import latest_signal, store_signal
from app.editions import edition_ids
from app.collectors.ra_hash import HASHERS
from app.collectors.retroachievements import RAError, RetroAchievementsCollector, parse_game_ref, resolve_game_id, summary

router = APIRouter(prefix="/api")
_sync_lock = ra_sync.LOCK  # shared with the sync that runs when a session ends
PAUSE = 1.0  # seconds between calls when syncing many games: the API asks for reasonable use


class Credentials(BaseModel):
    user: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64, pattern=r"^[^\x00-\x1f]+$")]
    key: str | None = Field(None, max_length=128, pattern=r"^[^\x00-\x1f\s]*$")  # None keeps the stored key


class GameRef(BaseModel):
    ra: str | None = None


@router.get("/ra/settings")
def get_settings(conn: sqlite3.Connection = Conn) -> dict:
    # The key is write-only: it never leaves the database.
    return {"user": ra_store.get_user(conn), "has_key": ra_store.get_credentials(conn) is not None}


@router.put("/ra/settings")
def put_settings(body: Credentials, conn: sqlite3.Connection = Conn) -> dict:
    ra_store.set_credentials(conn, body.user, body.key)
    return get_settings(conn)


def current_summary(conn: sqlite3.Connection, game_id: int, ra_id: int | None) -> dict | None:
    """The latest sync, but only if it belongs to the game currently linked (not an old link)."""
    signal = latest_signal(conn, game_id, "achievements")
    return summary(signal) if signal and ra_id is not None and signal.get("ra_id") == ra_id else None


def _game(conn: sqlite3.Connection, game_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT id, title FROM games WHERE id = ?", (game_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Jogo não encontrado")
    return row


@router.get("/games/{game_id}/ra")
def get_game_ra(game_id: int, conn: sqlite3.Connection = Conn) -> dict:
    _game(conn, game_id)
    ra_id = ra_store.get_ra_id(conn, game_id)
    return {"ra_id": ra_id, "summary": current_summary(conn, game_id, ra_id)}


@router.get("/games/{game_id}/achievements")
def get_achievements(game_id: int, conn: sqlite3.Connection = Conn) -> dict:
    """Every achievement of the linked set, what it takes to earn it and whether (and when) it was earned,
    from the last sync. Empty until the first sync stores the list."""
    _game(conn, game_id)
    ra_id = ra_store.get_ra_id(conn, game_id)
    if ra_id is None:
        return {"ra_id": None, "items": []}
    signal = latest_signal(conn, game_id, "achievements")
    earned_list = signal.get("earned_list") if signal and signal.get("ra_id") == ra_id else None
    earned = {e["id"]: e for e in earned_list or [] if isinstance(e, dict) and isinstance(e.get("id"), int)}
    items = [{**a, "earned": a["id"] in earned, "at": earned[a["id"]]["at"] if a["id"] in earned else None,
              "hardcore": bool(earned.get(a["id"], {}).get("hardcore"))} for a in ra_store.get_catalog(conn, ra_id)]
    return {"ra_id": ra_id, "items": items}


@router.get("/games/{game_id}/milestones")
def get_milestones(game_id: int, conn: sqlite3.Connection = Conn) -> dict:
    """Story milestones of a game read from the emulator's RAM: which are reached (from the latest signal),
    and why the reader cannot work if it cannot. `supported` is false for games without a hand-picked story."""
    _game(conn, game_id)
    ra_id = ra_store.get_ra_id(conn, game_id)
    if ra_id not in ram_milestones.STORIES:
        return {"supported": False}
    items = milestones.load(conn, game_id)
    signal = latest_signal(conn, game_id, "milestones")
    done = signal.get("reached") if signal and signal.get("ra_id") == ra_id else None
    done = set(done) if isinstance(done, list) else set()
    return {"supported": True, "total": len(items), "reached": sum(m["name"] in done for m in items),
            "items": [{"name": m["name"], "reached": m["name"] in done} for m in items],
            "read_at": signal["synced_at"] if signal and signal.get("ra_id") == ra_id else None,
            "problem": ram_milestones.PROBLEMS.get(game_id)}


@router.put("/games/{game_id}/ra")
def put_game_ra(game_id: int, body: GameRef, conn: sqlite3.Connection = Conn) -> dict:
    _game(conn, game_id)
    try:
        ra_id = parse_game_ref(body.ra)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    for disc in edition_ids(conn, game_id):  # the discs of an edition share one RetroAchievements set
        ra_store.set_ra_id(conn, disc, ra_id)
    return {"ra_id": ra_id}


def _sync(conn: sqlite3.Connection, game_id: int) -> dict:
    if ra_store.get_credentials(conn) is None:
        raise HTTPException(409, "Configure o usuário e a chave de API do RetroAchievements primeiro")
    if ra_store.get_ra_id(conn, game_id) is None:
        raise HTTPException(409, "Informe o ID do jogo no RetroAchievements primeiro")
    try:
        ra_sync.sync(conn, game_id)
    except RAError as exc:
        raise HTTPException(502, str(exc)) from exc
    return current_summary(conn, game_id, ra_store.get_ra_id(conn, game_id))


@router.post("/games/{game_id}/ra/sync")
def sync_game(game_id: int, conn: sqlite3.Connection = Conn) -> dict:
    _game(conn, game_id)
    if not _sync_lock.acquire(blocking=False):
        raise HTTPException(409, "Já existe uma sincronização em andamento")
    try:
        return _sync(conn, game_id)
    finally:
        _sync_lock.release()


@router.post("/ra/sync")
def sync_all(conn: sqlite3.Connection = Conn) -> list[dict]:
    if ra_store.get_credentials(conn) is None:
        raise HTTPException(409, "Configure o usuário e a chave de API do RetroAchievements primeiro")
    if not _sync_lock.acquire(blocking=False):
        raise HTTPException(409, "Já existe uma sincronização em andamento")
    try:
        rows = conn.execute("SELECT g.id, g.title FROM ra_games r JOIN games g ON g.id = r.game_id ORDER BY g.title").fetchall()
        results, done = [], set()
        for row in rows:
            if row["id"] in done:
                continue  # another disc of this edition was synced already
            if done and PAUSE:
                time.sleep(PAUSE)
            ra_id = ra_store.get_ra_id(conn, row["id"])
            # only discs linked to the same set get this answer; a disc linked elsewhere still syncs
            done.update(d for d in edition_ids(conn, row["id"]) if ra_store.get_ra_id(conn, d) == ra_id)
            try:
                s = _sync(conn, row["id"])
                results.append({"game_id": row["id"], "title": row["title"], "ok": True, "message": f"{s['earned']} de {s['total']}"})
            except HTTPException as exc:
                results.append({"game_id": row["id"], "title": row["title"], "ok": False, "message": exc.detail})
                if "recusou" in str(exc.detail) or "Limite" in str(exc.detail):
                    break  # a bad key or a rate limit will fail every other game too
            except Exception:  # noqa: BLE001 - one odd game must not abort the batch
                results.append({"game_id": row["id"], "title": row["title"], "ok": False, "message": "Erro inesperado ao sincronizar este jogo"})
        return results
    finally:
        _sync_lock.release()


def _detect(conn: sqlite3.Connection, game_id: int, keep_existing: bool = False) -> dict:
    """Hash the game's disc image and ask RetroAchievements which game it is. Needs no credentials."""
    game = conn.execute("SELECT platform FROM games WHERE id = ?", (game_id,)).fetchone()
    hasher = HASHERS.get(game["platform"] or "")
    if hasher is None:
        raise HTTPException(409, f"Ainda não sei calcular o hash do RetroAchievements para {game['platform'] or 'jogos não identificados'}")
    paths = [r["path"] for r in conn.execute("SELECT path FROM files WHERE game_id = ?", (game_id,)) if os.path.exists(r["path"])]
    if not paths:
        raise HTTPException(409, "Os arquivos do jogo não foram encontrados; escaneie a biblioteca de novo")
    digest = next((h for p in paths if (h := hasher(p))), None)
    if digest is None:
        raise HTTPException(409, "Este arquivo não é uma imagem de disco que eu consiga identificar (formatos comprimidos, como RVZ, não servem)")
    try:
        ra_id = resolve_game_id(digest)
    except RAError as exc:
        raise HTTPException(502, str(exc)) from exc
    if ra_id is None:
        return {"found": False, "ra_id": None, "hash": digest}
    discs = edition_ids(conn, game_id)  # the other discs of the edition share the set
    if keep_existing:
        # the bulk run read its list a while ago: a link saved meanwhile is the user's choice, never overwrite it
        insert = "INSERT INTO ra_games (game_id, ra_id) VALUES (?, ?) ON CONFLICT(game_id) DO NOTHING"
        cur = conn.execute(insert, (game_id, ra_id))
        for disc in discs:
            if disc != game_id:
                conn.execute(insert, (disc, ra_id))
        conn.commit()
        if cur.rowcount == 0:
            return {"found": True, "ra_id": ra_id, "hash": digest, "kept": True}
    else:
        for disc in discs:
            ra_store.set_ra_id(conn, disc, ra_id)
    return {"found": True, "ra_id": ra_id, "hash": digest}


@router.post("/games/{game_id}/ra/detect")
def detect_game(game_id: int, conn: sqlite3.Connection = Conn) -> dict:
    _game(conn, game_id)
    if not _sync_lock.acquire(blocking=False):
        raise HTTPException(409, "Já existe uma operação do RetroAchievements em andamento")
    try:
        return _detect(conn, game_id)
    finally:
        _sync_lock.release()


@router.post("/ra/detect")
def detect_all(conn: sqlite3.Connection = Conn) -> list[dict]:
    """Try every identified game that has no link yet and a console we can hash."""
    if not _sync_lock.acquire(blocking=False):
        raise HTTPException(409, "Já existe uma operação do RetroAchievements em andamento")
    try:
        rows = conn.execute(
            """SELECT g.id, g.title FROM games g
               WHERE g.identified = 1 AND g.platform IN ({}) AND g.id NOT IN (SELECT game_id FROM ra_games)
                 AND EXISTS (SELECT 1 FROM files f WHERE f.game_id = g.id)
               ORDER BY g.title""".format(",".join("?" * len(HASHERS))),
            list(HASHERS),
        ).fetchall()
        results, linked = [], set()
        for row in rows:
            if row["id"] in linked:
                continue  # linked together with another disc of its edition a moment ago
            if results and PAUSE:
                time.sleep(PAUSE)
            try:
                r = _detect(conn, row["id"], keep_existing=True)
                if r["found"]:
                    linked.update(edition_ids(conn, row["id"]))
                msg = "você vinculou este jogo enquanto eu detectava; mantive o seu vínculo" if r.get("kept") else f"jogo {r['ra_id']} no RetroAchievements" if r["found"] else "o RetroAchievements não reconheceu este disco"
                results.append({"game_id": row["id"], "title": row["title"], "ok": r["found"], "message": msg})
            except HTTPException as exc:
                results.append({"game_id": row["id"], "title": row["title"], "ok": False, "message": exc.detail})
                if exc.status_code == 502:
                    break  # the site is unreachable or answering oddly: the rest would fail the same way
            except Exception:  # noqa: BLE001 - one odd disc must not abort the batch
                results.append({"game_id": row["id"], "title": row["title"], "ok": False, "message": "Erro inesperado ao detectar este jogo"})
        return results
    finally:
        _sync_lock.release()
