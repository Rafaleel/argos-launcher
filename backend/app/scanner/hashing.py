import hashlib
import zlib
from dataclasses import dataclass

CHUNK = 1024 * 1024
NES_MAGIC = b"NES\x1a"
NES_HEADER = 16


@dataclass(frozen=True)
class Hashes:
    crc32: str
    sha1: str
    # Hashes without the 16-byte iNES header. No-Intro NES DATs are headerless.
    crc32_nohdr: str | None = None
    sha1_nohdr: str | None = None


def hash_file(path: str) -> Hashes:
    """CRC32 and SHA-1 in one streaming pass."""
    with open(path, "rb") as f:
        head = f.read(CHUNK)
        crc, sha = zlib.crc32(head), hashlib.sha1(head)
        has_header = head[:4] == NES_MAGIC and len(head) >= NES_HEADER
        if has_header:
            crc2, sha2 = zlib.crc32(head[NES_HEADER:]), hashlib.sha1(head[NES_HEADER:])
        while chunk := f.read(CHUNK):
            crc, sha = zlib.crc32(chunk, crc), _feed(sha, chunk)
            if has_header:
                crc2, sha2 = zlib.crc32(chunk, crc2), _feed(sha2, chunk)
    return Hashes(
        f"{crc:08x}",
        sha.hexdigest(),
        f"{crc2:08x}" if has_header else None,
        sha2.hexdigest() if has_header else None,
    )


def _feed(sha, chunk: bytes):
    sha.update(chunk)
    return sha
