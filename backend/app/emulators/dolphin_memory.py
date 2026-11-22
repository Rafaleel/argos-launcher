"""Read the emulated RAM of a running Dolphin through /proc/<pid>/mem.

Dolphin keeps the GameCube/Wii MEM1 (24 MB, at 0x80000000 in the console) in a shared-memory file
named /dev/shm/dolphin-emu.N and maps it into its own process. Linux lets a process of the same user
read that memory, with or without the Flatpak sandbox (checked live with Resident Evil 2).
Addresses here are offsets into MEM1, the same numbers RetroAchievements rules use."""

import os
import re

MEM1_SIZE = 0x1800000
# shortcut: assumes the default 24 MB MEM1; Dolphin's RAM override breaks the match, upgrade if anyone uses it
# "start-end perms offset dev inode  path"; MEM1 is the mapping of the shm file at offset 0
_MAPPING = re.compile(r"^([0-9a-f]+)-([0-9a-f]+) \S+ ([0-9a-f]+) \S+ \d+\s+(\S.*)$")


def _mem1_base(maps: str) -> int | None:
    for line in maps.splitlines():
        m = _MAPPING.match(line)
        if m and "dolphin-emu." in m[4] and int(m[3], 16) == 0 and int(m[2], 16) - int(m[1], 16) == MEM1_SIZE:
            return int(m[1], 16)
    return None


class DolphinMemory:
    def __init__(self, pid: int, base: int, proc: str = "/proc"):
        self.pid, self.base = pid, base
        self._mem = open(f"{proc}/{pid}/mem", "rb", buffering=0)

    @classmethod
    def attach(cls, proc: str = "/proc") -> "DolphinMemory | None":
        """The first Dolphin process that has a game loaded, or None."""
        for entry in os.scandir(proc):
            if not entry.name.isdigit():
                continue
            try:
                with open(f"{proc}/{entry.name}/comm") as f:
                    if not f.read().startswith("dolphin-emu"):
                        continue
                with open(f"{proc}/{entry.name}/maps") as f:
                    base = _mem1_base(f.read())
                if base is not None:
                    return cls(int(entry.name), base, proc)
            except OSError:
                pass  # the process ended, or is not ours to read
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
