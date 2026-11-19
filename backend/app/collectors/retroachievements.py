"""RetroAchievements collector: achievements earned for a game, as one `achievements` signal.

Endpoint and fields follow https://api-docs.retroachievements.org/v1/get-game-info-and-user-progress.html.
The docs show both PascalCase and camelCase names and no real call could be made while writing this,
so the parser accepts both and fails with a readable message when the shape is unexpected.
"""
import json
import re
import sqlite3
import urllib.error
import urllib.parse
import urllib.request

from app.collectors.base import store_signal
from app.collectors.ra_store import get_credentials, get_ra_id

BASE = "https://retroachievements.org/API/"
USER_AGENT = "ArgosLauncher/0.1"
MAX_BYTES = 8 * 1024 * 1024  # the biggest sets have a few hundred achievements; this is far above that
GAME_URL = re.compile(r"retroachievements\.org/game/(\d+)", re.I)


class RAError(Exception):
    """A problem to show the user. Never carries the URL: it holds the API key."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None  # the API does not redirect; following one could leak the key to another host


def get_json(url: str, timeout: float = 15.0):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.build_opener(_NoRedirect).open(req, timeout=timeout) as resp:
            raw = resp.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise RAError("O RetroAchievements recusou o usuário ou a chave de API. Confira os dois em Configurações.") from None
        if exc.code == 404:
            raise RAError("O RetroAchievements não achou esse jogo.") from None
        if exc.code == 429:
            raise RAError("Limite de uso do RetroAchievements atingido. Tente de novo em alguns minutos.") from None
        raise RAError(f"O RetroAchievements respondeu com erro {exc.code}.") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise RAError("Não consegui falar com o RetroAchievements. Verifique a internet e tente de novo.") from None
    if len(raw) > MAX_BYTES:
        raise RAError("Resposta grande demais do RetroAchievements; ignorada.")
    try:
        return json.loads(raw)
    except ValueError:
        raise RAError("O RetroAchievements devolveu algo que não é JSON.") from None


def _pick(d: dict, *names):
    for n in names:
        if n in d and d[n] is not None:
            return d[n]
    return None


def _int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def parse_progress(data, ra_id: int) -> dict:
    if not isinstance(data, dict):
        raise RAError("Resposta inesperada do RetroAchievements (não é um objeto).")
    err = _pick(data, "Error", "error", "message", "Message")
    if err and _pick(data, "ID", "id", "Achievements", "achievements") is None:
        raise RAError(f"O RetroAchievements respondeu: {str(err)[:120]}")
    raw = _pick(data, "Achievements", "achievements")
    if raw is None and _int(_pick(data, "NumAchievements", "numAchievements")) is None:
        raise RAError("Resposta inesperada do RetroAchievements (sem conquistas). Chaves: " + ", ".join(sorted(map(str, data))[:12]))
    items = list(raw.values()) if isinstance(raw, dict) else list(raw or [])
    items = [a for a in items if isinstance(a, dict)]

    def when(a):
        return _pick(a, "DateEarned", "dateEarned"), _pick(a, "DateEarnedHardcore", "dateEarnedHardcore")

    earned_items = [a for a in items if any(when(a))]
    total = _int(_pick(data, "NumAchievements", "numAchievements"))
    total = len(items) if total is None else total
    earned = _int(_pick(data, "NumAwardedToUser", "numAwardedToUser"))
    hard = _int(_pick(data, "NumAwardedToUserHardcore", "numAwardedToUserHardcore"))
    earned = len(earned_items) if earned is None else earned
    hard = sum(1 for a in items if when(a)[1]) if hard is None else hard
    points = lambda a: _int(_pick(a, "Points", "points")) or 0  # noqa: E731
    return {
        "ra_id": ra_id,
        "title": str(_pick(data, "Title", "title") or ""),
        "console": str(_pick(data, "ConsoleName", "consoleName") or ""),
        "total": total,
        "earned": earned,
        "earned_hardcore": hard,
        "points_total": sum(points(a) for a in items),
        "points_earned": sum(points(a) for a in earned_items),
        # only what was earned: enough for the progress filter later, small for big sets
        "earned_list": [
            {"id": _int(_pick(a, "ID", "id")), "points": points(a), "at": when(a)[0] or when(a)[1], "hardcore": bool(when(a)[1])}
            for a in earned_items
        ],
    }


def fetch_progress(user: str, key: str, ra_id: int) -> dict:
    query = urllib.parse.urlencode({"y": key, "u": user, "g": ra_id})
    return parse_progress(get_json(f"{BASE}API_GetGameInfoAndUserProgress.php?{query}"), ra_id)


class RetroAchievementsCollector:
    name = "retroachievements"

    def collect(self, conn: sqlite3.Connection, game_id: int) -> dict | None:
        creds, ra_id = get_credentials(conn), get_ra_id(conn, game_id)
        if creds is None or ra_id is None:
            return None
        payload = fetch_progress(creds[0], creds[1], ra_id)
        store_signal(conn, game_id, "achievements", payload)
        return payload


def parse_game_ref(text: str | None) -> int | None:
    """An RA game id, or the URL of its page. None/empty clears the link."""
    text = (text or "").strip()
    if not text:
        return None
    m = GAME_URL.search(text) or re.fullmatch(r"(\d{1,9})", text)
    if not m:
        raise ValueError("Informe o número do jogo no RetroAchievements ou o endereço da página dele (retroachievements.org/game/1234)")
    n = int(m.group(1))
    if n < 1:
        raise ValueError("ID inválido")
    return n


def summary(payload: dict | None) -> dict | None:
    if not payload:
        return None
    total, earned = payload.get("total") or 0, payload.get("earned") or 0
    return {
        "title": payload.get("title", ""),
        "total": total,
        "earned": earned,
        "earned_hardcore": payload.get("earned_hardcore", 0),
        "percent": round(min(100.0, 100.0 * earned / total), 1) if total else None,
        "synced_at": payload.get("synced_at"),
    }
