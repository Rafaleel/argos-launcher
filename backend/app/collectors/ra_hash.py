"""RetroAchievements game hashes, to find a game's RA id from a disc image.

GameCube follows rcheevos `rc_hash_nintendo_disc_partition` (src/hash/rc_hash_disc.c): MD5 over the
disc header (its size comes from the apploader), then every non-empty segment of main.dol.
This was written from that source; the reference program was not run here. The RA server is the
real check: a wrong hash is simply not recognised.
"""
import hashlib
import struct
from collections.abc import Callable

BASE_HEADER = 0x2440
MAX_HEADER = 1024 * 1024
MAX_HASHED = 64 * 1024 * 1024  # a real main.dol is a few MB; refuse a bogus header that asks for more
CHUNK = 1024 * 1024
GC_MAGIC = bytes.fromhex("c2339f3d")


def _u32(buf: bytes, at: int) -> int:
    return struct.unpack_from(">I", buf, at)[0]


def gamecube_hash(path: str) -> str | None:
    """MD5 as RetroAchievements computes it for a raw GameCube disc image, or None if it is not one."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(0x1C)
            if f.read(4) != GC_MAGIC:
                return None
            f.seek(BASE_HEADER + 0x14)
            sizes = f.read(8)
            if len(sizes) < 8:
                return None
            header_size = min(BASE_HEADER + 0x20 + _u32(sizes, 0) + _u32(sizes, 4), MAX_HEADER)
            f.seek(0)
            header = f.read(header_size)
            if len(header) < header_size or header_size < 0x424:
                return None
            md5 = hashlib.md5(header)
            dol = _u32(header, 0x420)
            f.seek(dol)
            table = f.read(0xD8)
            if len(table) < 0xD8:
                return None
            total = 0
            segments = []
            for i in range(18):  # 7 code segments, then 11 data segments
                # Deliberately NOT dol + offset: rcheevos seeks to the raw value (real discs store it relative
                # to the dol, so it lands in the header area), and the hash must equal the one RA computed.
                offset, length = _u32(table, i * 4), _u32(table, 0x90 + i * 4)
                if length == 0:
                    continue
                total += length
                if offset + length > size or total > MAX_HASHED:
                    return None  # points outside the image: not a sane disc
                segments.append((offset, length))
            for offset, length in segments:
                f.seek(offset)
                left = length
                while left:
                    chunk = f.read(min(CHUNK, left))
                    if not chunk:
                        return None
                    md5.update(chunk)
                    left -= len(chunk)
            return md5.hexdigest()
    except OSError:
        return None


# platform name (the DAT header name) -> hasher. Add a console here to detect its games too.
HASHERS: dict[str, Callable[[str], str | None]] = {
    "Nintendo - GameCube": gamecube_hash,
}
