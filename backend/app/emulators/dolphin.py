"""Dolphin adapter: video settings, GPU choice, texture packs and GC pad presets.

Facts verified on a real Dolphin 2609b (Flatpak) with a hybrid Intel + NVIDIA laptop:
- `-C GFX.*` options are ignored, so video settings go to GameSettings/<ID>.ini.
- `-v` selects the backend; the PRIME environment variables select the NVIDIA GPU
  for both OpenGL and Vulkan (checked with nvidia-smi and Dolphin's own log).
"""
import functools
import os
import re
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FLATPAK_ID = "org.DolphinEmu.dolphin-emu"
NVIDIA_ENV = {
    "__NV_PRIME_RENDER_OFFLOAD": "1",
    "__GLX_VENDOR_LIBRARY_NAME": "nvidia",
    "__VK_LAYER_NV_optimus": "NVIDIA_only",
}


@dataclass(frozen=True)
class Install:
    flatpak: bool
    config_dir: Path
    data_dir: Path


def detect(executable: str, args: list[str]) -> Install | None:
    """Return the Dolphin install an emulator entry points at, or None."""
    home = Path.home()
    # `flatpak run <id>` or the exported wrapper script named after the app id
    if (os.path.basename(executable) == "flatpak" and FLATPAK_ID in args) or os.path.basename(executable) == FLATPAK_ID:
        base = home / ".var" / "app" / FLATPAK_ID
        return Install(True, base / "config" / "dolphin-emu", base / "data" / "dolphin-emu")
    if "dolphin-emu" in os.path.basename(executable).lower():
        # shortcut: XDG defaults only; the legacy ~/.dolphin-emu layout is not handled.
        cfg = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config") / "dolphin-emu"
        data = Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share") / "dolphin-emu"
        return Install(False, cfg, data)
    return None


def is_running(proc: str = "/proc") -> bool:
    for entry in os.scandir(proc):
        if entry.name.isdigit():
            try:
                with open(f"{proc}/{entry.name}/comm") as f:
                    # the kernel cuts comm at 15 chars: "dolphin-emu-nogui" reads "dolphin-emu-nog"
                    if f.read().strip().startswith("dolphin-emu"):
                        return True
            except OSError:
                pass
    return False


# ---------------------------------------------------------------- video settings


class VideoSettings(BaseModel):
    """None means "leave it as Dolphin has it"."""

    model_config = ConfigDict(extra="forbid")
    backend: Literal["Vulkan", "OGL"] | None = None
    gpu: Literal["nvidia"] | None = None  # None = whatever the system picks
    internal_resolution: int | None = Field(None, ge=1, le=6)
    anisotropy: int | None = Field(None, ge=0, le=4)  # 0 = 1x ... 4 = 16x
    vsync: bool | None = None
    hires_textures: bool | None = None
    prefetch_textures: bool | None = None


# setting -> (ini section, key) in GameSettings/<ID>.ini
INI_KEYS = {
    "internal_resolution": ("Video_Settings", "InternalResolution"),
    "hires_textures": ("Video_Settings", "HiresTextures"),
    "prefetch_textures": ("Video_Settings", "CacheHiresTextures"),
    "anisotropy": ("Video_Enhancements", "MaxAnisotropy"),
    "vsync": ("Video_Hardware", "VSync"),
}


def effective(defaults: dict, game: dict) -> dict:
    merged = {k: v for k, v in defaults.items() if v is not None}
    merged.update({k: v for k, v in game.items() if v is not None})
    return merged


def _fmt(value) -> str:
    return ("True" if value else "False") if isinstance(value, bool) else str(value)


def _read_text(path: Path) -> str:
    # surrogateescape keeps bytes that are not UTF-8 intact, so a Latin-1 comment
    # neither crashes a launch nor gets mangled when we write the file back.
    return path.read_bytes().decode("utf-8", "surrogateescape")


def set_ini_values(
    path: Path, changes: dict[tuple[str, str], str], remove: frozenset[tuple[str, str]] = frozenset()
) -> None:
    """Set or remove keys in a Dolphin INI, keeping every other line (and CRLF).

    Section and key names are matched ignoring case, like Dolphin does.
    """
    text = _read_text(path) if path.exists() else ""
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()

    def find(section: str, key: str):
        start = next((i for i, l in enumerate(lines) if l.strip().lower() == f"[{section}]".lower()), None)
        if start is None:
            return None, None, None
        end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("[")), len(lines))
        hit = next((i for i in range(start + 1, end) if re.match(rf"\s*{re.escape(key)}\s*=", lines[i], re.I)), None)
        return start, end, hit

    for section, key in remove:
        _, _, hit = find(section, key)
        if hit is not None:
            del lines[hit]
    for (section, key), value in changes.items():
        start, end, hit = find(section, key)
        if start is None:
            lines += ([""] if lines else []) + [f"[{section}]", f"{key} = {value}"]
        elif hit is not None:
            lines[hit] = f"{key} = {value}"
        else:
            at = end
            while at > start + 1 and not lines[at - 1].strip():
                at -= 1
            lines.insert(at, f"{key} = {value}")
    _write_atomic(path, nl.join(lines) + nl)


def _write_atomic(path: Path, text: str) -> None:
    target = Path(os.path.realpath(path))  # write through a symlink instead of replacing it
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=target.name + ".")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(text.encode("utf-8", "surrogateescape"))
        if target.exists():
            shutil.copymode(target, tmp)  # mkstemp makes 0600; keep the file's own mode
        else:
            os.chmod(tmp, 0o644)
        os.replace(tmp, target)
    except BaseException:
        os.unlink(tmp)
        raise


def apply_game_settings(install: Install, game_id: str, settings: dict, previous: frozenset[str] = frozenset()) -> set[str]:
    """Write the managed keys. Keys Argos wrote earlier and that are now "Padrão" are
    removed, so the Dolphin default comes back; keys it never wrote are left alone.
    Returns the settings now written, to remember for the next launch."""
    now = {k for k in settings if k in INI_KEYS}
    changes = {INI_KEYS[k]: _fmt(settings[k]) for k in now}
    gone = frozenset(INI_KEYS[k] for k in previous if k in INI_KEYS and k not in now)
    if changes or gone:
        set_ini_values(install.data_dir / "GameSettings" / f"{game_id}.ini", changes, gone)
    return now


def launch_plan(install: Install, args: list[str], settings: dict) -> tuple[list[str], dict[str, str]]:
    """Extra arguments and environment for the launch. `args` is the emulator template."""
    args, env = list(args), {}
    if settings.get("gpu") == "nvidia":
        if install.flatpak and "run" not in args:
            raise ValueError(
                "Para escolher a placa de vídeo com o Flatpak, cadastre o emulador como /usr/bin/flatpak "
                f"com os argumentos run, {FLATPAK_ID}, … (o script exportado não repassa o ambiente)"
            )
        if install.flatpak:
            at = args.index("run") + 1  # Flatpak options must come before the app id
            args[at:at] = [f"--env={k}={v}" for k, v in NVIDIA_ENV.items()]
        else:
            env.update(NVIDIA_ENV)
    if settings.get("backend"):
        args += ["-v", settings["backend"]]
    return args, env


GAME_ID = re.compile(r"^[A-Z0-9]{6}$")


def read_game_id(path: str) -> str | None:
    """GameCube and Wii discs start with their 6-character game id."""
    try:
        with open(path, "rb") as f:
            head = f.read(6).decode("ascii", "strict")
    except (OSError, UnicodeDecodeError):
        return None
    return head if GAME_ID.match(head) else None


# ---------------------------------------------------------------- hardware info


@functools.lru_cache(maxsize=1)
def gpu_names() -> tuple[str, ...]:
    """Cached: lspci can take seconds and wakes a sleeping discrete GPU."""
    try:
        out = subprocess.run(["lspci", "-mm"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return ()
    names = []
    for line in out.splitlines():
        if re.search(r'"(VGA compatible controller|3D controller|Display controller)"', line):
            parts = re.findall(r'"([^"]*)"', line)
            if len(parts) >= 3:  # class, vendor, device; the rest is the board's subsystem
                names.append(f"{parts[1]} {parts[2]}")
    return tuple(names)


@functools.lru_cache(maxsize=1)
def nvidia_flatpak_ready() -> bool | None:
    """True if a Flatpak NVIDIA GL extension is installed; None if flatpak is missing."""
    try:
        out = subprocess.run(
            ["flatpak", "list", "--runtime", "--columns=application"], capture_output=True, text=True, timeout=20
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return "org.freedesktop.Platform.GL.nvidia" in out


def controller_candidates() -> list[dict]:
    """Gamepads the kernel sees. The name is a hint: Dolphin's SDL name can differ."""
    try:
        text = Path("/proc/bus/input/devices").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    found = []
    for block in text.split("\n\n"):
        name = re.search(r'^N: Name="(.*)"$', block, re.M)
        if name and re.search(r"Handlers=.*\bjs\d+\b", block):
            found.append({"name": name.group(1), "device": f"SDL/{len(found)}/{name.group(1)}"})
    return found


# ---------------------------------------------------------------- texture packs

_pack_lock = threading.Lock()
JOB: dict = {"state": "idle", "message": "", "game_id": None}
MONITORS: list[threading.Thread] = []  # tests join these


def seven_zip() -> str | None:
    return next((p for n in ("7z", "7zz", "7za") if (p := shutil.which(n))), None)


def textures_root(install: Install) -> Path:
    return install.data_dir / "Load" / "Textures"


def pack_names(game_id: str) -> list[str]:
    return [game_id, game_id[:3]]


def pack_status(install: Install, game_id: str) -> dict:
    for name in pack_names(game_id):
        d = textures_root(install) / name
        if d.is_dir() and not d.is_symlink():
            files = size = 0
            for dp, _, fs in os.walk(d):
                for f in fs:
                    try:
                        size += os.lstat(os.path.join(dp, f)).st_size  # a broken symlink must not 500
                    except OSError:
                        continue
                    files += 1
            return {"installed": True, "folder": name, "files": files, "bytes": size}
    return {"installed": False, "folder": None, "files": 0, "bytes": 0}


def list_archive(archive: str) -> list[dict]:
    sz = seven_zip()
    if not sz:
        raise PackError("7z não encontrado: instale o p7zip para extrair pacotes")
    res = subprocess.run([sz, "l", "-slt", "-ba", "--", archive], capture_output=True, text=True)
    if res.returncode != 0:
        raise PackError("não foi possível ler o arquivo (corrompido ou formato não suportado)")
    entries = []
    for block in res.stdout.split("\n\n"):
        fields = dict(l.split(" = ", 1) for l in block.splitlines() if " = " in l)
        if "Path" in fields:
            entries.append(fields)
    return entries


class PackError(Exception):
    pass


def check_entries(entries: list[dict], game_id: str) -> int:
    """Every path must live under the game's folder. Returns the unpacked size."""
    if not entries:
        raise PackError("o arquivo está vazio")
    total = 0
    for e in entries:
        parts = e["Path"].replace("\\", "/").split("/")
        if e["Path"].startswith(("/", "\\")) or ".." in parts or parts[0] not in pack_names(game_id):
            raise PackError(
                f"o pacote não é deste jogo: esperado uma pasta {game_id[:3]}/ ou {game_id}/, achei '{e['Path']}'"
            )
        if e.get("Folder") != "+":
            total += int(e.get("Size") or 0)
    return total


def install_pack(install: Install, game_id: str, archive: str) -> None:
    """Validate, extract into a staging folder, then swap it in. Raises PackError."""
    total = check_entries(list_archive(archive), game_id)
    root = textures_root(install)
    root.mkdir(parents=True, exist_ok=True)
    need = int(total * 1.05) + 512 * 1024 * 1024
    if shutil.disk_usage(root).free < need:
        raise PackError(f"espaço insuficiente: preciso de cerca de {need // 2**30 + 1} GB livres")
    staging = root / f".argos-staging-{game_id}"
    shutil.rmtree(staging, ignore_errors=True)
    try:
        res = subprocess.run(
            [seven_zip(), "x", "-y", "-bso0", "-bsp0", f"-o{staging}", "--", archive], capture_output=True
        )
        if res.returncode != 0:
            raise PackError("falha ao extrair o pacote")
        top = sorted(p.name for p in staging.iterdir())
        if len(top) != 1 or top[0] not in pack_names(game_id):
            raise PackError("o conteúdo extraído não tem a pasta esperada")
        for dp, dns, fns in os.walk(staging):
            if any(os.path.islink(os.path.join(dp, n)) for n in dns + fns):
                raise PackError("o pacote contém links simbólicos e foi recusado")
        target, old = root / top[0], root / f".argos-old-{game_id}"
        shutil.rmtree(old, ignore_errors=True)
        if target.exists():
            os.rename(target, old)
        os.rename(staging / top[0], target)
        shutil.rmtree(old, ignore_errors=True)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def start_install(install: Install, game_id: str, archive: str) -> bool:
    """Run install_pack in the background. False if another install is running."""
    if not _pack_lock.acquire(blocking=False):
        return False

    def work() -> None:
        try:
            JOB.update(state="running", message="Extraindo o pacote…", game_id=game_id)
            install_pack(install, game_id, archive)
            JOB.update(state="done", message="Pacote instalado.")
        except PackError as exc:
            JOB.update(state="error", message=str(exc))
        except Exception as exc:  # noqa: BLE001 - the job must never die silently
            JOB.update(state="error", message=f"erro inesperado: {exc}")
        finally:
            _pack_lock.release()

    JOB.update(state="running", message="Extraindo o pacote…", game_id=game_id)
    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    MONITORS.append(thread)
    return True


def install_running() -> bool:
    return _pack_lock.locked()


def remove_pack(install: Install, game_id: str) -> bool:
    root = textures_root(install)
    removed = False
    for name in pack_names(game_id):
        d = root / name
        if d.is_dir() and not d.is_symlink() and d.resolve().parent == root.resolve():
            shutil.rmtree(d)
            removed = True
    return removed


# ---------------------------------------------------------------- GameCube pad 1

KB_DEVICE = "XInput2/0/Virtual core pointer"
_KB_COMMON = {
    "Buttons/Start": "`Return`",
    "Main Stick/Modifier": "`Shift`",
    "Main Stick/Calibration": "100.00 141.42 100.00 141.42 100.00 141.42 100.00 141.42",
    "C-Stick/Modifier": "`Ctrl`",
    "C-Stick/Calibration": "100.00 141.42 100.00 141.42 100.00 141.42 100.00 141.42",
    "D-Pad/Up": "`T`", "D-Pad/Down": "`G`", "D-Pad/Left": "`F`", "D-Pad/Right": "`H`",
}
PRESETS: dict[str, dict[str, str]] = {
    # Dolphin's own default keyboard layout.
    "keyboard_default": {
        **_KB_COMMON,
        "Buttons/A": "`X`", "Buttons/B": "`Z`", "Buttons/X": "`C`", "Buttons/Y": "`S`", "Buttons/Z": "`D`",
        "Main Stick/Up": "`Up`", "Main Stick/Down": "`Down`", "Main Stick/Left": "`Left`", "Main Stick/Right": "`Right`",
        "C-Stick/Up": "`I`", "C-Stick/Down": "`K`", "C-Stick/Left": "`J`", "C-Stick/Right": "`L`",
        "Triggers/L": "`Q`", "Triggers/R": "`W`",
    },
    "keyboard_wasd": {
        **_KB_COMMON,
        "Buttons/A": "`K`", "Buttons/B": "`J`", "Buttons/X": "`L`", "Buttons/Y": "`I`", "Buttons/Z": "`U`",
        "Main Stick/Up": "`W`", "Main Stick/Down": "`S`", "Main Stick/Left": "`A`", "Main Stick/Right": "`D`",
        "C-Stick/Up": "`Up`", "C-Stick/Down": "`Down`", "C-Stick/Left": "`Left`", "C-Stick/Right": "`Right`",
        "Triggers/L": "`Q`", "Triggers/R": "`E`",
    },
    # Dolphin's bundled "SDL Gamepad" profile (Sys/Profiles/GCPad/SDL Gamepad.ini).
    "xbox": {
        "Buttons/A": "`Button A`", "Buttons/B": "`Button B`", "Buttons/X": "`Button X`", "Buttons/Y": "`Button Y`",
        "Buttons/Z": "`Shoulder R`", "Buttons/Start": "`Start`",
        "Main Stick/Up": "`Left Y+`", "Main Stick/Down": "`Left Y-`", "Main Stick/Left": "`Left X-`",
        "Main Stick/Right": "`Left X+`", "Main Stick/Calibration": "100.00",
        "C-Stick/Up": "`Right Y+`", "C-Stick/Down": "`Right Y-`", "C-Stick/Left": "`Right X-`",
        "C-Stick/Right": "`Right X+`", "C-Stick/Calibration": "100.00",
        "Triggers/L": "`Trigger L`", "Triggers/R": "`Trigger R`",
        "Triggers/L-Analog": "`Trigger L`", "Triggers/R-Analog": "`Trigger R`",
        "D-Pad/Up": "`Pad N`", "D-Pad/Down": "`Pad S`", "D-Pad/Left": "`Pad W`", "D-Pad/Right": "`Pad E`",
        "Rumble/Motor": "`Motor L` | `Motor R`",
    },
}
DEVICE = re.compile(r"^[A-Za-z0-9_]+/\d+/[^\r\n=`\[\]]+$")


def write_pad1(install: Install, preset: str, device: str | None) -> None:
    if preset not in PRESETS:
        raise ValueError("preset desconhecido")
    device = KB_DEVICE if preset.startswith("keyboard") else device
    if not device or not DEVICE.fullmatch(device):  # fullmatch: "$" would accept a trailing newline
        raise ValueError("dispositivo inválido (esperado algo como SDL/0/Nome do controle)")
    path = install.config_dir / "GCPadNew.ini"
    old = _read_text(path) if path.exists() else ""
    backup = path.with_name(path.name + ".argos-bak")
    if old and not backup.exists():
        shutil.copy2(path, backup)  # keep the very first file, never overwrite the backup
    body = [f"[GCPad1]", f"Device = {device}"] + [f"{k} = {v}" for k, v in PRESETS[preset].items()]
    kept, skipping = [], False
    for line in old.splitlines():
        if line.startswith("["):
            skipping = line.strip() == "[GCPad1]"
        if not skipping:
            kept.append(line)
    _write_atomic(path, "\n".join(body + kept) + "\n")


def read_pad1_device(install: Install) -> str | None:
    path = install.config_dir / "GCPadNew.ini"
    try:
        text = _read_text(path)
    except OSError:
        return None  # missing or unreadable: the info page must still load
    inside = False
    for line in text.splitlines():
        if line.startswith("["):
            inside = line.strip() == "[GCPad1]"
        elif inside and line.startswith("Device"):
            value = line.split("=", 1)[1].strip()
            return value.encode("utf-8", "surrogateescape").decode("utf-8", "replace")  # JSON-safe
    return None
