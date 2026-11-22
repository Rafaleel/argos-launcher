"""RetroAchievements collector: achievements earned for a game, as one `achievements` signal.

Endpoint and fields follow https://api-docs.retroachievements.org/v1/get-game-info-and-user-progress.html.
The docs show both PascalCase and camelCase names and no real call could be made while writing this,
so the parser accepts both and fails with a readable message when the shape is unexpected.
"""
import http.client
import json
import math
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request

from app.collectors.base import store_signal
from app.collectors.ra_store import get_credentials, get_ra_id

BASE = "https://retroachievements.org/API/"
DOREQUEST = "https://retroachievements.org/dorequest.php"  # what emulators ask for a game id; no key needed
USER_AGENT = "ArgosLauncher/0.1"
MAX_BYTES = 8 * 1024 * 1024  # the biggest sets have a few hundred achievements; this is far above that
TOTAL_TIMEOUT = 30.0  # the whole answer, not each socket operation: a trickling server must not hold the sync forever
MAX_COUNT = 1_000_000  # no real game has anything close to this many achievements or points
GAME_URL = re.compile(r"^(?:https?://)?(?:www\.)?retroachievements\.org/game/([0-9]{1,9})(?:[/?#].*)?$", re.I)


class RAError(Exception):
    """A problem to show the user. Never carries the URL: it holds the API key."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None  # the API does not redirect; following one could leak the key to another host


def _reject_constant(name):
    raise ValueError(name)  # NaN / Infinity are not JSON; they would poison the arithmetic later


def get_json(url: str, timeout: float = 15.0, data: bytes | None = None):
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, headers=headers)
    deadline = time.monotonic() + TOTAL_TIMEOUT
    try:
        with urllib.request.build_opener(_NoRedirect).open(req, timeout=timeout) as resp:
            chunks, size = [], 0
            while chunk := resp.read1(65536):  # read1: returns what arrived, so the deadline is checked
                size += len(chunk)
                if size > MAX_BYTES:
                    raise RAError("Resposta grande demais do RetroAchievements; ignorada.")
                if time.monotonic() > deadline:
                    raise RAError("O RetroAchievements demorou demais para responder.")
                chunks.append(chunk)
            raw = b"".join(chunks)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise RAError("O RetroAchievements recusou o usuário ou a chave de API. Confira os dois em Configurações.") from None
        if exc.code == 404:
            raise RAError("O RetroAchievements não achou esse jogo.") from None
        if exc.code == 429:
            raise RAError("Limite de uso do RetroAchievements atingido. Tente de novo em alguns minutos.") from None
        raise RAError(f"O RetroAchievements respondeu com erro {exc.code}.") from None
    except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError):
        # URLError, a garbled status line, a cut chunk, huge headers: all "could not talk to it"
        raise RAError("Não consegui falar com o RetroAchievements. Verifique a internet e tente de novo.") from None
    try:
        return json.loads(raw, parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        raise RAError("O RetroAchievements devolveu algo que não é JSON.") from None


def _pick(d: dict, *names):
    for n in names:
        if n in d and d[n] is not None:
            return d[n]
    return None


def _int(v) -> int | None:
    """A whole number in 0..MAX_COUNT, or None. Booleans, floats, negatives and huge values are not counts."""
    if isinstance(v, bool):
        return None
    if isinstance(v, float):
        if not math.isfinite(v) or v != int(v):
            return None
        v = int(v)
    try:
        n = int(v)
    except (TypeError, ValueError, OverflowError):
        return None
    return n if 0 <= n <= MAX_COUNT else None


def parse_progress(data, ra_id: int) -> dict:
    if not isinstance(data, dict):
        raise RAError("Resposta inesperada do RetroAchievements (não é um objeto).")
    err = _pick(data, "Error", "error", "message", "Message")
    if err and _pick(data, "ID", "id", "Achievements", "achievements") is None:
        raise RAError(f"O RetroAchievements respondeu: {str(err)[:120]}")
    raw = _pick(data, "Achievements", "achievements")
    if raw is None and _int(_pick(data, "NumAchievements", "numAchievements")) is None:
        raise RAError("Resposta inesperada do RetroAchievements (sem conquistas). Chaves: " + ", ".join(sorted(map(str, data))[:12]))
    if raw is not None and not isinstance(raw, (dict, list)):
        raise RAError("Resposta inesperada do RetroAchievements (a lista de conquistas tem outro formato).")
    items = list(raw.values()) if isinstance(raw, dict) else list(raw or [])
    items = [a for a in items if isinstance(a, dict)]

    def when(a):
        return _pick(a, "DateEarned", "dateEarned"), _pick(a, "DateEarnedHardcore", "dateEarnedHardcore")

    earned_items, seen = [], set()
    for a in items:
        ident = _int(_pick(a, "ID", "id"))
        if any(when(a)) and (ident is None or ident not in seen):  # the same achievement twice counts once
            earned_items.append(a)
            if ident is not None:
                seen.add(ident)
    total = _int(_pick(data, "NumAchievements", "numAchievements"))
    total = len(items) if total is None else total
    earned = _int(_pick(data, "NumAwardedToUser", "numAwardedToUser"))
    hard = _int(_pick(data, "NumAwardedToUserHardcore", "numAwardedToUserHardcore"))
    earned = len(earned_items) if earned is None else earned
    hard = sum(1 for a in earned_items if when(a)[1]) if hard is None else hard
    points = lambda a: _int(_pick(a, "Points", "points")) or 0  # noqa: E731
    title = _pick(data, "Title", "title")
    console = _pick(data, "ConsoleName", "consoleName")
    return {
        "ra_id": ra_id,
        "title": title[:200] if isinstance(title, str) else "",
        "console": console[:80] if isinstance(console, str) else "",
        "total": total,
        "earned": earned,
        "earned_hardcore": hard,
        "points_total": sum(points(a) for a in items),
        "points_earned": sum(points(a) for a in earned_items),
        # only what was earned: enough for the progress filter later, small for big sets
        "earned_list": [
            {"id": _int(_pick(a, "ID", "id")), "points": points(a), "at": str(when(a)[0] or when(a)[1])[:40], "hardcore": bool(when(a)[1])}
            for a in earned_items
        ],
    }


def fetch_progress(user: str, key: str, ra_id: int) -> dict:
    query = urllib.parse.urlencode({"y": key, "u": user, "g": ra_id})
    try:
        return parse_progress(get_json(f"{BASE}API_GetGameInfoAndUserProgress.php?{query}"), ra_id)
    except RAError as exc:
        # a server may repeat what it was sent in its error text: the key must not travel back
        raise RAError(str(exc).replace(key, "•••")) from None
    except (TypeError, ValueError, OverflowError, AttributeError, KeyError, RecursionError):
        raise RAError("Resposta inesperada do RetroAchievements.") from None


def resolve_game_id(md5: str) -> int | None:
    """Ask RetroAchievements which game a hash belongs to (what an emulator does). Sends only the hash."""
    if not re.fullmatch(r"[0-9a-f]{32}", md5):
        raise RAError("Hash inválido.")
    data = get_json(DOREQUEST, data=urllib.parse.urlencode({"r": "gameid", "m": md5}).encode())
    if not isinstance(data, dict):
        raise RAError("Resposta inesperada do RetroAchievements.")
    if data.get("Success") is False:
        raise RAError("O RetroAchievements não conseguiu procurar esse disco.")
    game = _int(data.get("GameID"))
    return game or None  # 0 means "unknown hash"


def fetch_patch(game_id: int, user: str, token: str) -> dict:
    """The rules of a game's achievements and its rich presence, the way emulators ask for them (`patch`).
    Needs the login token. It goes in the POST body, never in the URL, and no error text carries it."""
    try:
        data = get_json(DOREQUEST, data=urllib.parse.urlencode({"r": "patch", "g": game_id, "u": user, "t": token}).encode())
    except RAError as exc:
        if "recusou" in str(exc):  # 401/403: the token, not the API key that get_json talks about
            raise RAError("O RetroAchievements recusou o login do Dolphin (o token pode ter expirado). "
                          "Entre de novo nas conquistas do Dolphin, em Oficina.") from None
        raise
    patch = data.get("PatchData") if isinstance(data, dict) else None
    if not isinstance(patch, dict) or not isinstance(patch.get("Achievements"), list):
        raise RAError("O RetroAchievements não devolveu as regras desse jogo. Confira o login no Dolphin.")
    return patch


def login_token(user: str, password: str) -> tuple[str, str]:
    """Log in the way emulators do (rcheevos `login2`) and return (user name, token). The password is not kept."""
    try:
        data = get_json(DOREQUEST, data=urllib.parse.urlencode({"r": "login2", "u": user, "p": password}).encode())
    except RAError as exc:
        if "recusou" in str(exc):  # a 401/403 here means a wrong user or password, not the API key
            raise RAError("Login recusado: confira o usuário e a senha do RetroAchievements.") from None
        raise RAError(str(exc).replace(password, "•••")) from None
    if not isinstance(data, dict) or data.get("Success") is not True:
        err = data.get("Error") if isinstance(data, dict) else None
        msg = str(err)[:160].replace(password, "•••") if err else "o RetroAchievements recusou o login"
        raise RAError(f"Login recusado: {msg}")
    name, token = data.get("User"), data.get("Token")
    if not (isinstance(name, str) and isinstance(token, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", name)
            and re.fullmatch(r"[A-Za-z0-9]{8,128}", token)):
        raise RAError("Resposta inesperada do RetroAchievements ao fazer login.")
    return name, token


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
    m = GAME_URL.search(text) or re.fullmatch(r"([0-9]{1,9})", text)  # ASCII only: \d also matches other scripts
    if not m:
        raise ValueError("Informe o número do jogo no RetroAchievements ou o endereço da página dele (retroachievements.org/game/1234)")
    n = int(m.group(1))
    if n < 1:
        raise ValueError("ID inválido")
    return n


def summary(payload: dict | None) -> dict | None:
    """Shape for the UI. Must never raise: it runs for the whole games list."""
    if not isinstance(payload, dict):
        return None
    total, earned = _int(payload.get("total")) or 0, _int(payload.get("earned")) or 0
    return {
        "title": str(payload.get("title") or ""),
        "total": total,
        "earned": earned,
        "earned_hardcore": _int(payload.get("earned_hardcore")) or 0,
        "percent": round(min(100.0, 100.0 * earned / total), 1) if total else None,
        "synced_at": payload.get("synced_at"),
    }
