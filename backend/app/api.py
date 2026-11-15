import json
import os
import sqlite3
import threading
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db import connect
from app.launcher.launch import LaunchError, launch, validate_executable
from app.scanner.scan import scan
from app.sessions.tracker import AlreadyPlaying, start_session
from app.stats import play_time

router = APIRouter(prefix="/api")
_scan_lock = threading.Lock()


def get_conn() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


Conn = Depends(get_conn)


class Settings(BaseModel):
    rom_dirs: list[str] = []
    dat_dirs: list[str] = []


class EmulatorIn(BaseModel):
    platform: str
    executable: str
    args: list[str]


def _read_settings(conn: sqlite3.Connection) -> Settings:
    rows = dict(conn.execute("SELECT key, value FROM settings").fetchall())
    return Settings(
        rom_dirs=json.loads(rows.get("rom_dirs", "[]")),
        dat_dirs=json.loads(rows.get("dat_dirs", "[]")),
    )


@router.get("/settings")
def get_settings(conn: sqlite3.Connection = Conn) -> Settings:
    return _read_settings(conn)


@router.put("/settings")
def put_settings(body: Settings, conn: sqlite3.Connection = Conn) -> Settings:
    clean = Settings(
        rom_dirs=[os.path.expanduser(d.strip()) for d in body.rom_dirs if d.strip()],
        dat_dirs=[os.path.expanduser(d.strip()) for d in body.dat_dirs if d.strip()],
    )
    for d in clean.rom_dirs + clean.dat_dirs:
        if not os.path.isabs(d):
            raise HTTPException(422, f"O caminho da pasta deve ser absoluto: {d}")
    for key, value in clean.model_dump().items():
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )
    conn.commit()
    return clean


@router.post("/scan")
def run_scan(conn: sqlite3.Connection = Conn) -> dict:
    if not _scan_lock.acquire(blocking=False):
        raise HTTPException(409, "Já existe um scan em andamento")
    try:
        s = _read_settings(conn)
        if not s.rom_dirs:
            # An empty list would delete every game; never do that by accident.
            raise HTTPException(422, "Nenhuma pasta de ROMs configurada")
        return scan(conn, s.rom_dirs, s.dat_dirs)
    finally:
        _scan_lock.release()


@router.get("/games")
def list_games(conn: sqlite3.Connection = Conn) -> list[dict]:
    rows = conn.execute(
        """SELECT g.id, g.title, g.platform, g.identified,
                  (e.id IS NOT NULL) AS has_emulator,
                  EXISTS (SELECT 1 FROM sessions s WHERE s.game_id = g.id AND s.ended_at IS NULL) AS playing
           FROM games g LEFT JOIN emulators e ON e.platform = g.platform
           WHERE EXISTS (SELECT 1 FROM files f WHERE f.game_id = g.id)
           ORDER BY g.platform IS NULL, g.platform, g.title"""
    ).fetchall()
    time = play_time.per_game(conn)
    return [
        {
            **dict(r),
            "identified": bool(r["identified"]),
            "has_emulator": bool(r["has_emulator"]),
            "playing": bool(r["playing"]),
            "seconds_played": time.get(r["id"], {}).get("seconds", 0),
        }
        for r in rows
    ]


@router.get("/platforms")
def list_platforms(conn: sqlite3.Connection = Conn) -> list[str]:
    rows = conn.execute("SELECT DISTINCT platform FROM games WHERE platform IS NOT NULL ORDER BY 1")
    return [r["platform"] for r in rows]


@router.get("/emulators")
def list_emulators(conn: sqlite3.Connection = Conn) -> list[EmulatorIn]:
    rows = conn.execute("SELECT platform, executable, args FROM emulators ORDER BY platform")
    return [EmulatorIn(platform=r["platform"], executable=r["executable"], args=json.loads(r["args"])) for r in rows]


@router.put("/emulators")
def put_emulator(body: EmulatorIn, conn: sqlite3.Connection = Conn) -> EmulatorIn:
    # Platform must be one the library really has, so it matches the DAT name.
    if body.platform not in list_platforms(conn):
        raise HTTPException(422, "Plataforma desconhecida: escolha uma encontrada na biblioteca")
    if not any("{rom}" in a for a in body.args):
        raise HTTPException(422, "Os argumentos devem conter {rom}")
    try:
        validate_executable(body.executable)
    except LaunchError as exc:
        raise HTTPException(422, str(exc)) from exc
    conn.execute(
        "INSERT INTO emulators (platform, executable, args) VALUES (?, ?, ?) "
        "ON CONFLICT(platform) DO UPDATE SET executable = excluded.executable, args = excluded.args",
        (body.platform, body.executable, json.dumps(body.args)),
    )
    conn.commit()
    return body


@router.post("/games/{game_id}/play")
def play(game_id: int, conn: sqlite3.Connection = Conn) -> dict:
    game = conn.execute("SELECT platform FROM games WHERE id = ?", (game_id,)).fetchone()
    if game is None:
        raise HTTPException(404, "Jogo não encontrado")
    if game["platform"] is None:
        raise HTTPException(409, "Jogo não identificado: a plataforma é desconhecida")
    emu = conn.execute("SELECT executable, args FROM emulators WHERE platform = ?", (game["platform"],)).fetchone()
    if emu is None:
        raise HTTPException(409, f"Nenhum emulador configurado para {game['platform']}")
    paths = [r["path"] for r in conn.execute("SELECT path FROM files WHERE game_id = ?", (game_id,))]
    try:
        pid, session_id = start_session(
            conn, game_id, lambda: launch(emu["executable"], json.loads(emu["args"]), paths)
        )
    except AlreadyPlaying:
        raise HTTPException(409, "Este jogo já está aberto") from None
    except LaunchError as exc:
        raise HTTPException(500, str(exc)) from exc
    return {"pid": pid, "session_id": session_id}


@router.get("/stats/games")
def stats_games(conn: sqlite3.Connection = Conn) -> list[dict]:
    titles = {r["id"]: r for r in conn.execute("SELECT id, title, platform FROM games")}
    rows = [
        {"game_id": gid, "title": titles[gid]["title"], "platform": titles[gid]["platform"], **v}
        for gid, v in play_time.per_game(conn).items()
    ]
    return sorted(rows, key=lambda r: -r["seconds"])


@router.get("/stats/platforms")
def stats_platforms(conn: sqlite3.Connection = Conn) -> list[dict]:
    rows = [{"platform": p, "seconds": v} for p, v in play_time.per_platform(conn).items()]
    return sorted(rows, key=lambda r: -r["seconds"])


@router.get("/stats/periods")
def stats_periods(by: str = "day", n: int = 0, conn: sqlite3.Connection = Conn) -> list[dict]:
    if by not in ("day", "week", "month"):
        raise HTTPException(422, "by deve ser day, week ou month")
    return play_time.per_period(conn, by, n or {"day": 14, "week": 12, "month": 12}[by])
