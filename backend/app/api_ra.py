import sqlite3
import threading
import time

from fastapi import APIRouter, HTTPException
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from app.api import Conn
from app.collectors import ra_store
from app.collectors.base import latest_signal
from app.collectors.retroachievements import RAError, RetroAchievementsCollector, parse_game_ref, summary

router = APIRouter(prefix="/api")
_sync_lock = threading.Lock()
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


@router.put("/games/{game_id}/ra")
def put_game_ra(game_id: int, body: GameRef, conn: sqlite3.Connection = Conn) -> dict:
    _game(conn, game_id)
    try:
        ra_id = parse_game_ref(body.ra)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    ra_store.set_ra_id(conn, game_id, ra_id)
    return {"ra_id": ra_id}


def _sync(conn: sqlite3.Connection, game_id: int) -> dict:
    if ra_store.get_credentials(conn) is None:
        raise HTTPException(409, "Configure o usuário e a chave de API do RetroAchievements primeiro")
    if ra_store.get_ra_id(conn, game_id) is None:
        raise HTTPException(409, "Informe o ID do jogo no RetroAchievements primeiro")
    try:
        RetroAchievementsCollector().collect(conn, game_id)
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
        results = []
        for i, row in enumerate(rows):
            if i and PAUSE:
                time.sleep(PAUSE)
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
