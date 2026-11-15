import os
import subprocess
import threading


class LaunchError(Exception):
    pass


class FilesMissing(LaunchError):
    pass


def playable_file(paths: list[str]) -> str:
    """A game with a .cue plays from the .cue; otherwise from its first file."""
    if not paths:
        raise LaunchError("o jogo não tem arquivos")
    cues = sorted(p for p in paths if p.lower().endswith(".cue"))
    return os.path.abspath(cues[0] if cues else sorted(paths)[0])


def build_argv(executable: str, args: list[str], rom: str) -> list[str]:
    # str.replace per argument, never a shell: a hostile file name stays one
    # plain argument. rom is absolute, so it can never look like an option.
    return [executable] + [a.replace("{rom}", rom) for a in args]


def validate_executable(executable: str) -> None:
    if not os.path.isabs(executable):
        raise LaunchError("o caminho do emulador deve ser absoluto")
    if not (os.path.isfile(executable) and os.access(executable, os.X_OK)):
        raise LaunchError("o caminho do emulador não é um arquivo executável")


def launch(executable: str, args: list[str], paths: list[str]) -> int:
    validate_executable(executable)
    # Files on an unmounted drive are still in the library but cannot be played.
    present = [p for p in paths if os.path.exists(p)]
    if not present:
        raise FilesMissing("os arquivos do jogo não foram encontrados; escaneie a biblioteca de novo")
    argv = build_argv(executable, args, playable_file(present))
    try:
        proc = subprocess.Popen(
            argv,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        raise LaunchError(f"não foi possível abrir o emulador: {exc}") from exc
    threading.Thread(target=proc.wait, daemon=True).start()  # reap, no zombie
    return proc.pid
