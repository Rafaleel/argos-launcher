"""Box art from libretro-thumbnails, cached on disk.

Those repositories name each image after the No-Intro/Redump title, the same name the DATs give
our games, so no account or search is needed. Only the platform and title are sent.
"""
import hashlib
import os
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from app.config import db_path

BASE = "https://raw.githubusercontent.com/libretro-thumbnails/"
MAX_BYTES = 5 * 1024 * 1024
RETRY_MISSING = 7 * 24 * 3600  # a cover that did not exist is asked for again after a week
PNG = b"\x89PNG\r\n\x1a\n"
DISC = re.compile(r"\s*\(Disc \d+\)", re.I)


def cover_dir() -> Path:
    return db_path().parent / "covers"


def _name(text: str) -> str:
    return re.sub(r'[&*/:`<>?\\|"]', "_", text)  # libretro-thumbnails' rule for file names


def urls(platform: str, title: str) -> list[str]:
    repo = urllib.parse.quote(platform.replace(" ", "_"))
    names = [title] + ([DISC.sub("", title)] if DISC.search(title) else [])
    return [f"{BASE}{repo}/master/Named_Boxarts/{urllib.parse.quote(_name(n))}.png" for n in names]


def _download(url: str) -> bytes | None:
    """The PNG, None if the server has no such image. Raises OSError when it cannot be reached."""
    req = urllib.request.Request(url, headers={"User-Agent": "ArgosLauncher/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise OSError(f"HTTP {exc.code}") from None
    except urllib.error.URLError as exc:
        raise OSError(str(exc.reason)) from None
    return data if len(data) <= MAX_BYTES and data.startswith(PNG) else None


def _write(path: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".cover.")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def get(platform: str, title: str) -> Path | None:
    """Local file with the cover, fetching it once. None if there is none (or the site is unreachable)."""
    folder = cover_dir()
    folder.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(f"{platform}\0{title}".encode()).hexdigest()
    path, missing = folder / f"{key}.png", folder / f"{key}.none"
    if path.exists():
        return path
    if missing.exists() and time.time() - missing.stat().st_mtime < RETRY_MISSING:
        return None
    try:
        data = next((d for u in urls(platform, title) if (d := _download(u))), None)
    except OSError:
        return None  # offline: try again next time, remember nothing
    if data is None:
        missing.touch()
        return None
    _write(path, data)
    missing.unlink(missing_ok=True)
    return path
