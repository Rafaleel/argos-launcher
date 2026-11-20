"""Find installed emulators and the launch arguments they need, so the user does not type them.

Platforms are DAT header names (No-Intro/Redump). RetroArch cores say which ones they run in their
`.info` file (`database = "Nintendo - Game Boy|..."`), using those same names.
"""
import functools
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

DOLPHIN_ID = "org.DolphinEmu.dolphin-emu"
RETROARCH_ID = "org.libretro.RetroArch"
DOLPHIN_PLATFORMS = ["Nintendo - GameCube", "Nintendo - Wii"]


@dataclass(frozen=True)
class Candidate:
    name: str  # what the UI shows, e.g. "Dolphin (Flatpak)"
    platforms: tuple[str, ...]
    executable: str
    args: tuple[str, ...]

    def as_dict(self) -> dict:
        return {**asdict(self), "platforms": list(self.platforms), "args": list(self.args)}


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


@functools.lru_cache(maxsize=1)
def flatpak_apps() -> frozenset[str]:
    return frozenset(_run(["flatpak", "list", "--app", "--columns=application"]).split())


def flatpak_location(app: str) -> Path | None:
    out = _run(["flatpak", "info", "--show-location", app]).strip()
    return Path(out) if out else None


def _info_platforms(info: Path) -> list[str]:
    try:
        text = info.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    m = re.search(r'^\s*database\s*=\s*"([^"]*)"', text, re.M)
    return [p.strip() for p in m.group(1).split("|") if p.strip()] if m else []


def retroarch_cores(cores_dir: Path, info_dirs: list[Path]) -> list[tuple[Path, list[str]]]:
    """(core .so, platforms) for every installed core whose .info names its systems."""
    if not cores_dir.is_dir():
        return []
    found = []
    for core in sorted(cores_dir.glob("*_libretro.so")):
        info_name = core.name[: -len(".so")] + ".info"
        for d in [cores_dir, *info_dirs]:
            platforms = _info_platforms(d / info_name)
            if platforms:
                found.append((core, platforms))
                break
    return found


def candidates() -> list[Candidate]:
    """Every emulator setup found, dedicated emulators first (they beat a RetroArch core)."""
    out: list[Candidate] = []
    home, apps, flatpak = Path.home(), flatpak_apps(), shutil.which("flatpak")

    if flatpak and DOLPHIN_ID in apps:
        out.append(Candidate("Dolphin (Flatpak)", tuple(DOLPHIN_PLATFORMS), flatpak, ("run", DOLPHIN_ID, "-b", "-e", "{rom}")))
    if native := shutil.which("dolphin-emu"):
        out.append(Candidate("Dolphin", tuple(DOLPHIN_PLATFORMS), native, ("-b", "-e", "{rom}")))

    if flatpak and RETROARCH_ID in apps:
        loc = flatpak_location(RETROARCH_ID)
        # the app's config dir is mounted at the same path inside the sandbox, so the core path works there
        cores = home / ".var" / "app" / RETROARCH_ID / "config" / "retroarch" / "cores"
        info = [loc / "files" / "share" / "libretro" / "info"] if loc else []
        for core, platforms in retroarch_cores(cores, info):
            out.append(Candidate(f"RetroArch (Flatpak) · {core.stem.removesuffix('_libretro')}", tuple(platforms), flatpak,
                                 ("run", RETROARCH_ID, "-L", str(core), "{rom}")))
    if native := shutil.which("retroarch"):
        cfg = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config") / "retroarch"
        for core, platforms in retroarch_cores(cfg / "cores", [Path("/usr/share/libretro/info"), Path("/usr/lib/libretro")]):
            out.append(Candidate(f"RetroArch · {core.stem.removesuffix('_libretro')}", tuple(platforms), native,
                                 ("-L", str(core), "{rom}")))
    return out


def best_for(platform: str, found: list[Candidate]) -> Candidate | None:
    return next((c for c in found if platform in c.platforms), None)
