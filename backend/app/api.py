import json
import os
import sqlite3
import threading
from collections.abc import Iterator
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app import covers
from app.collectors import presence
from app.config import db_path
from app.editions import edition_ids
from app.db import connect
from app.collectors.retroachievements import summary as ra_summary
from app.emulators import detect, dolphin, store
from app.launcher.launch import FilesMissing, LaunchError, launch, validate_executable
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
        result = scan(conn, s.rom_dirs, s.dat_dirs)
        result["emulators_configured"] = auto_configure(conn)
        return result
    finally:
        _scan_lock.release()


def _save_emulator(conn: sqlite3.Connection, platform: str, executable: str, args: list[str]) -> None:
    conn.execute(
        "INSERT INTO emulators (platform, executable, args) VALUES (?, ?, ?) "
        "ON CONFLICT(platform) DO UPDATE SET executable = excluded.executable, args = excluded.args",
        (platform, executable, json.dumps(args)),
    )
    conn.commit()


def auto_configure(conn: sqlite3.Connection) -> list[dict]:
    """Give every library platform that has no emulator yet the best one installed. Never replaces a choice."""
    taken = {r["platform"] for r in conn.execute("SELECT platform FROM emulators")}
    missing = [p for p in list_platforms(conn) if p not in taken]
    if not missing:
        return []
    found, done = detect.candidates(), []
    for platform in missing:
        c = detect.best_for(platform, found)
        if c:
            _save_emulator(conn, platform, c.executable, list(c.args))
            done.append({"platform": platform, "name": c.name})
    return done


@router.get("/emulators/detected")
def detected_emulators(conn: sqlite3.Connection = Conn) -> dict:
    """Installed emulators that can run each library platform, best first."""
    found = detect.candidates()
    return {p: [c.as_dict() for c in found if p in c.platforms] for p in list_platforms(conn)}


@router.get("/games")
def list_games(conn: sqlite3.Connection = Conn) -> list[dict]:
    rows = conn.execute(
        """SELECT g.id, g.title, g.platform, g.identified,
                  (e.id IS NOT NULL) AS has_emulator, e.executable AS emu_exe, e.args AS emu_args,
                  EXISTS (SELECT 1 FROM sessions s WHERE s.game_id = g.id AND s.ended_at IS NULL) AS playing
           FROM games g LEFT JOIN emulators e ON e.platform = g.platform
           WHERE EXISTS (SELECT 1 FROM files f WHERE f.game_id = g.id)
           ORDER BY g.platform IS NULL, g.platform, g.title"""
    ).fetchall()
    time = play_time.per_game(conn)
    ra_ids = {r["game_id"]: r["ra_id"] for r in conn.execute("SELECT game_id, ra_id FROM ra_games")}
    latest = conn.execute(
        """SELECT s.game_id, s.payload, s.timestamp FROM signals s
           JOIN (SELECT game_id, MAX(id) AS mid FROM signals WHERE type = 'achievements' GROUP BY game_id) m ON s.id = m.mid"""
    ).fetchall()
    places = {
        r["game_id"]: r["payload"] for r in conn.execute(
            """SELECT s.game_id, s.payload FROM signals s
               JOIN (SELECT game_id, MAX(id) AS mid FROM signals WHERE type = 'presence' GROUP BY game_id) m ON s.id = m.mid""")
    }
    achievements = {}
    for r in latest:
        try:
            payload = json.loads(r["payload"])
            # only a sync of the game that is linked now (a changed or removed link hides the old result)
            if isinstance(payload, dict) and ra_ids.get(r["game_id"]) is not None and payload.get("ra_id") == ra_ids[r["game_id"]]:
                achievements[r["game_id"]] = ra_summary({**payload, "synced_at": r["timestamp"]})
        except ValueError:
            pass  # a broken old signal must not take the library down
    result = []
    for r in rows:
        game = {k: v for k, v in dict(r).items() if k not in ("emu_exe", "emu_args")}
        result.append(
            {
                **game,
                "identified": bool(r["identified"]),
                "has_emulator": bool(r["has_emulator"]),
                "playing": bool(r["playing"]),
                "seconds_played": time.get(r["id"], {}).get("seconds", 0),
                "ra_id": ra_ids.get(r["id"]),
                "achievements": achievements.get(r["id"]),
                "presence": _presence(places.get(r["id"])),
                "dolphin": bool(r["emu_exe"]) and dolphin.detect(r["emu_exe"], json.loads(r["emu_args"])) is not None,
            }
        )
    return result


# shortcut: a cold cover can hold a worker for up to ~30 s on a slow network; fine for a local
# library, revisit (background prefetch after scan) if big libraries stall the API.
@router.get("/games/{game_id}/cover")
def game_cover(game_id: int, conn: sqlite3.Connection = Conn) -> FileResponse:
    game = conn.execute("SELECT title, platform FROM games WHERE id = ?", (game_id,)).fetchone()
    if game is None or game["platform"] is None:
        raise HTTPException(404, "Sem capa")
    path = covers.get(game["platform"], game["title"])
    if path is None:
        raise HTTPException(404, "Sem capa")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "max-age=86400"})


def _presence(payload: str | None) -> dict | None:
    """The last rich presence line of a game, for "where you stopped"."""
    try:
        p = json.loads(payload) if payload else None
    except ValueError:
        return None  # a broken old signal must not take the library down
    if not isinstance(p, dict) or not isinstance(p.get("message"), str):
        return None
    return {"message": p["message"], "at": p.get("at")}


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
    _save_emulator(conn, body.platform, body.executable, body.args)
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
    discs = edition_ids(conn, game_id)
    others = [d for d in discs if d != game_id]
    if others and conn.execute(
        f"SELECT 1 FROM sessions WHERE game_id IN ({','.join('?' * len(others))}) AND ended_at IS NULL", others
    ).fetchone():
        raise HTTPException(409, "Outro disco deste jogo já está aberto")
    args, env = json.loads(emu["args"]), {}
    install = dolphin.detect(emu["executable"], args)
    if install:
        # Check first: a refused play must not rewrite the INI of a game that is already open.
        if conn.execute("SELECT 1 FROM sessions WHERE game_id = ? AND ended_at IS NULL", (game_id,)).fetchone():
            raise HTTPException(409, "Este jogo já está aberto")
        settings = store.effective_for(conn, game_id)
        game_code = next((c for p in paths if os.path.exists(p) and (c := dolphin.read_game_id(p))), None)
        if dolphin.install_running() and dolphin.JOB["game_id"] == game_code:
            raise HTTPException(409, "O pacote de texturas deste jogo ainda está sendo instalado")
        try:
            if game_code:
                written = dolphin.apply_game_settings(install, game_code, settings, store.get_written(conn, game_id))
                store.set_written(conn, game_id, written)
            args, env = dolphin.launch_plan(install, args, settings)
            at = discs.index(game_id)  # Dolphin swaps to the *next* entry: chosen disc, then the following ones
            if others and (playlist := _disc_playlist(conn, discs[at:] + discs[:at])):
                # Dolphin boots the first entry and swaps to the next one when the game asks for it
                paths = [playlist]
                args = [*args, "-C", "Dolphin.Core.AutoDiscChange=True"]
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(500, f"Não foi possível gravar a configuração do Dolphin: {exc}") from exc
    try:
        pid, session_id = start_session(
            conn, game_id, lambda: launch(emu["executable"], args, paths, env), tuple(others)
        )
    except AlreadyPlaying:
        raise HTTPException(409, "Este jogo já está aberto") from None
    except FilesMissing as exc:
        raise HTTPException(409, str(exc)) from exc
    except sqlite3.OperationalError:
        raise HTTPException(503, "Banco de dados ocupado; tente de novo") from None
    except LaunchError as exc:
        raise HTTPException(500, str(exc)) from exc
    started = conn.execute("SELECT started_at FROM sessions WHERE id = ?", (session_id,)).fetchone()["started_at"]
    presence.start(conn, game_id, session_id, datetime.fromisoformat(started.replace("Z", "+00:00")))
    return {"pid": pid, "session_id": session_id}


def _disc_playlist(conn: sqlite3.Connection, game_ids: list[int]) -> str | None:
    """An .m3u with one existing disc per game, in the given order (the chosen one first).

    None unless the chosen disc and at least one other are there: the clicked disc must boot."""
    files = []
    for gid in game_ids:
        rows = conn.execute("SELECT path FROM files WHERE game_id = ? ORDER BY path", (gid,)).fetchall()
        path = next((r["path"] for r in rows if os.path.isfile(r["path"])), None)
        if path and "\n" not in path and "\r" not in path:  # one path per line
            files.append((gid, path))
    if len(files) < 2 or files[0][0] != game_ids[0]:
        return None
    target = db_path().parent / "playlists" / f"{game_ids[0]}.m3u"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(f"{path}\n" for _, path in files), encoding="utf-8")
    return str(target)


@router.get("/stats/games")
def stats_games(conn: sqlite3.Connection = Conn) -> list[dict]:
    titles = {r["id"]: r for r in conn.execute("SELECT id, title, platform FROM games")}
    rows = [
        {"game_id": gid, "title": titles[gid]["title"], "platform": titles[gid]["platform"], **v}
        for gid, v in play_time.per_game(conn).items()
    ]
    return sorted(rows, key=lambda r: -r["seconds"])


@router.get("/stats/journal")
def stats_journal(before: date | None = None, conn: sqlite3.Connection = Conn) -> dict:
    return play_time.journal(conn, before)


@router.get("/stats/platforms")
def stats_platforms(conn: sqlite3.Connection = Conn) -> list[dict]:
    rows = [{"platform": p, "seconds": v} for p, v in play_time.per_platform(conn).items()]
    return sorted(rows, key=lambda r: -r["seconds"])


@router.get("/stats/periods")
def stats_periods(by: str = "day", n: int = Query(0, ge=0, le=366), conn: sqlite3.Connection = Conn) -> list[dict]:
    if by not in ("day", "week", "month"):
        raise HTTPException(422, "by deve ser day, week ou month")
    return play_time.per_period(conn, by, n or {"day": 14, "week": 12, "month": 12}[by])
