import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field


@dataclass
class DatIndex:
    # hash -> (platform, game title). The platform is the DAT header name.
    by_sha1: dict[str, tuple[str, str]] = field(default_factory=dict)
    by_crc: dict[tuple[str, int], tuple[str, str]] = field(default_factory=dict)

    def find(self, sha1: str | None, crc32: str | None, size: int) -> tuple[str, str] | None:
        """Match on SHA-1 first, then on CRC32 plus size."""
        if sha1 and sha1 in self.by_sha1:
            return self.by_sha1[sha1]
        return self.by_crc.get((crc32, size)) if crc32 else None


def parse_dat(path: str, index: DatIndex) -> None:
    """Add the games of a No-Intro/Redump XML DAT to the index.

    All or nothing: a truncated or header-less DAT adds nothing.
    """
    found = DatIndex()
    _parse_into(path, found)
    for k, v in found.by_sha1.items():
        index.by_sha1.setdefault(k, v)
    for k, v in found.by_crc.items():
        index.by_crc.setdefault(k, v)


def _parse_into(path: str, index: DatIndex) -> None:
    platform = ""
    for _, el in ET.iterparse(path):
        if el.tag == "header":
            platform = (el.findtext("name") or "").strip()
            el.clear()
        elif el.tag == "game":
            if not platform:
                raise ValueError("o DAT não tem nome no cabeçalho")
            title = el.get("name", "").strip()
            for rom in el.findall("rom"):
                entry = (platform, title)
                sha1, crc = (rom.get("sha1") or "").lower(), (rom.get("crc") or "").lower()
                if sha1:
                    index.by_sha1.setdefault(sha1, entry)
                if crc and rom.get("size", "").isdigit():
                    index.by_crc.setdefault((crc, int(rom.get("size"))), entry)
            el.clear()


def load_dats(dirs: list[str]) -> tuple[DatIndex, list[str]]:
    index, errors = DatIndex(), []
    for root in dirs:
        if not os.path.isdir(root):
            errors.append(f"Pasta de DATs não encontrada: {os.fsencode(root).decode('utf-8', 'replace')}")
            continue
        for dirpath, _, names in os.walk(root):
            for name in sorted(names):
                if name.lower().endswith((".dat", ".xml")):
                    full = os.path.join(dirpath, name)
                    try:
                        parse_dat(full, index)
                    except (ET.ParseError, OSError, ValueError) as exc:
                        errors.append(f"DAT inválido {os.fsencode(full).decode('utf-8', 'replace')}: {exc}")
    return index, errors
