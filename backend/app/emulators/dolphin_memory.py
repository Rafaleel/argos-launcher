"""Read the emulated RAM of a running Dolphin through /proc/<pid>/mem.

Dolphin keeps the GameCube/Wii MEM1 (24 MB, at 0x80000000 in the console) in a shared-memory file
named /dev/shm/dolphin-emu.N and maps it into its own process. Linux lets a process of the same user
read that memory, with or without the Flatpak sandbox (checked live with Resident Evil 2).
Addresses here are offsets into MEM1, the same numbers RetroAchievements rules use."""

import os
import re

MEM1_SIZE = 0x1800000
# "start-end perms offset dev inode  path"; MEM1 is the mapping of the shm file at offset 0
_MAPPING = re.compile(r"^([0-9a-f]+)-([0-9a-f]+) \S+ ([0-9a-f]+) \S+ \d+\s+(\S.*)$")


class DolphinMemoryError(Exception):
    """Dolphin is running but its RAM cannot be read; the message says why."""


def _mem1_base(maps: str) -> tuple[int | None, list[int]]:
    """(start of MEM1, sizes of every Dolphin shm mapping at offset 0), the sizes to explain a miss."""
    sizes = []
    for line in maps.splitlines():
        m = _MAPPING.match(line)
        if m and "dolphin-emu." in m[4] and int(m[3], 16) == 0:
            size = int(m[2], 16) - int(m[1], 16)
            # shortcut: matches the default 24 MB MEM1 by size. UNVERIFIED: with Dolphin's memory override
            # (Config > Advanced) the size may change and this misses; the error below then says so.
            # To check: set the override, run a game, compare the mappings. Not tested yet.
            if size == MEM1_SIZE:
                return int(m[1], 16), sizes
            sizes.append(size)
    return None, sizes


class DolphinMemory:
    def __init__(self, pid: int, base: int, proc: str = "/proc"):
        self.pid, self.base = pid, base
        self._mem = open(f"{proc}/{pid}/mem", "rb", buffering=0)

    @classmethod
    def attach(cls, proc: str = "/proc") -> "DolphinMemory | None":
        """The first Dolphin process that has a game loaded; None when there is no Dolphin or no game.
        Raises DolphinMemoryError when a Dolphin is there but its RAM cannot be found or read."""
        found = []
        for entry in os.scandir(proc):
            if not entry.name.isdigit():
                continue
            try:
                with open(f"{proc}/{entry.name}/comm") as f:
                    if not f.read().startswith("dolphin-emu"):
                        continue
                with open(f"{proc}/{entry.name}/maps") as f:
                    base, sizes = _mem1_base(f.read())
                if base is not None:
                    return cls(int(entry.name), base, proc)
                found += sizes
            except PermissionError:
                raise DolphinMemoryError(
                    "Sem permissão para ler a memória do Dolphin. Ele precisa rodar como o mesmo usuário do Argos "
                    "e o sistema não pode bloquear a leitura entre processos (kernel.yama.ptrace_scope)."
                ) from None
            except OSError:
                pass  # the process ended
        if found:
            lista = ", ".join(f"{n / 2**20:g} MB" for n in sorted(set(found)))
            raise DolphinMemoryError(
                f"Encontrei memória do Dolphin ({lista}), mas nenhuma com os 24 MB da RAM principal do GameCube. "
                "A RAM pode ter sido aumentada nas opções avançadas do Dolphin, ou esta versão do Dolphin "
                "guarda a memória de outro jeito. O Argos ainda não lê esses casos."
            )
        return None

    def read(self, address: int, size: int) -> bytes:
        """`size` bytes at MEM1 offset `address`. OSError when Dolphin has closed the game."""
        if address < 0 or size < 1 or address + size > MEM1_SIZE:
            raise ValueError(f"fora da RAM do jogo: 0x{address:X} + {size}")
        data = os.pread(self._mem.fileno(), size, self.base + address)
        if len(data) != size:
            raise OSError("leitura incompleta; o Dolphin fechou o jogo?")
        return data

    def close(self) -> None:
        self._mem.close()
