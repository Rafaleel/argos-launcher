import json
import os
import sqlite3

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api import Conn
from app.emulators import dolphin, store

router = APIRouter(prefix="/api")


class Archive(BaseModel):
    archive: str


class Controls(BaseModel):
    preset: str
    device: str | None = None


def _first_install(conn: sqlite3.Connection) -> dolphin.Install | None:
    for row in conn.execute("SELECT executable, args FROM emulators ORDER BY platform"):
        install = dolphin.detect(row["executable"], json.loads(row["args"]))
        if install:
            return install
    return None


def _need_install(conn: sqlite3.Connection) -> dolphin.Install:
    install = _first_install(conn)
    if install is None:
        raise HTTPException(409, "Nenhum emulador Dolphin cadastrado")
    return install


def _game_context(conn: sqlite3.Connection, game_id: int) -> tuple[dolphin.Install, str | None]:
    game = conn.execute("SELECT platform FROM games WHERE id = ?", (game_id,)).fetchone()
    if game is None:
        raise HTTPException(404, "Jogo não encontrado")
    emu = conn.execute("SELECT executable, args FROM emulators WHERE platform = ?", (game["platform"],)).fetchone()
    install = dolphin.detect(emu["executable"], json.loads(emu["args"])) if emu else None
    if install is None:
        raise HTTPException(409, "Este jogo não usa o Dolphin")
    paths = [r["path"] for r in conn.execute("SELECT path FROM files WHERE game_id = ?", (game_id,))]
    code = next((c for p in paths if os.path.exists(p) and (c := dolphin.read_game_id(p))), None)
    return install, code


def _not_running() -> None:
    if dolphin.is_running():
        raise HTTPException(409, "Feche o Dolphin antes de fazer isso")


@router.get("/dolphin/info")
def info(conn: sqlite3.Connection = Conn) -> dict:
    install = _first_install(conn)
    return {
        "detected": install is not None,
        "flatpak": install.flatpak if install else None,
        "running": dolphin.is_running(),
        "gpus": dolphin.gpu_names(),
        "nvidia_ready": dolphin.nvidia_flatpak_ready() if install and install.flatpak else None,
        "controllers": dolphin.controller_candidates(),
        "seven_zip": dolphin.seven_zip() is not None,
        "pad_device": dolphin.read_pad1_device(install) if install else None,
        "presets": list(dolphin.PRESETS),
    }


@router.get("/dolphin/defaults")
def get_defaults(conn: sqlite3.Connection = Conn) -> dict:
    return store.get_defaults(conn)


@router.put("/dolphin/defaults")
def put_defaults(body: dolphin.VideoSettings, conn: sqlite3.Connection = Conn) -> dict:
    return store.set_defaults(conn, body)


@router.get("/games/{game_id}/profile")
def get_profile(game_id: int, conn: sqlite3.Connection = Conn) -> dict:
    install, code = _game_context(conn, game_id)
    game, defaults = store.get_game(conn, game_id), store.get_defaults(conn)
    return {
        "settings": game,
        "defaults": defaults,
        "effective": dolphin.effective(defaults, game),
        "game_code": code,
        "textures": dolphin.pack_status(install, code) if code else None,
    }


@router.put("/games/{game_id}/profile")
def put_profile(game_id: int, body: dolphin.VideoSettings, conn: sqlite3.Connection = Conn) -> dict:
    _game_context(conn, game_id)
    return store.set_game(conn, game_id, body)


@router.post("/games/{game_id}/textures", status_code=202)
def install_textures(game_id: int, body: Archive, conn: sqlite3.Connection = Conn) -> dict:
    install, code = _game_context(conn, game_id)
    if code is None:
        raise HTTPException(409, "Não consegui ler o ID do jogo; escaneie de novo")
    _not_running()
    archive = body.archive.strip()
    if not os.path.isabs(archive) or not os.path.isfile(archive):
        raise HTTPException(422, "Informe o caminho absoluto de um arquivo existente")
    if not dolphin.seven_zip():
        raise HTTPException(409, "7z não encontrado: instale o p7zip")
    if not dolphin.start_install(install, code, archive):
        raise HTTPException(409, "Já existe uma instalação em andamento")
    return {"started": True}


@router.get("/dolphin/textures/job")
def textures_job() -> dict:
    return dict(dolphin.JOB)


@router.delete("/games/{game_id}/textures")
def remove_textures(game_id: int, conn: sqlite3.Connection = Conn) -> dict:
    install, code = _game_context(conn, game_id)
    if code is None:
        raise HTTPException(409, "Não consegui ler o ID do jogo; escaneie de novo")
    _not_running()
    return {"removed": dolphin.remove_pack(install, code)}


@router.get("/dolphin/controls")
def get_controls(conn: sqlite3.Connection = Conn) -> dict:
    install = _need_install(conn)
    return {"device": dolphin.read_pad1_device(install), "presets": list(dolphin.PRESETS)}


@router.put("/dolphin/controls")
def put_controls(body: Controls, conn: sqlite3.Connection = Conn) -> dict:
    install = _need_install(conn)
    _not_running()
    try:
        dolphin.write_pad1(install, body.preset, body.device)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(500, f"Não foi possível gravar a configuração dos controles: {exc}") from exc
    return {"device": dolphin.read_pad1_device(install)}
