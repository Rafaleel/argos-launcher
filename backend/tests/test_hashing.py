import hashlib
import zlib

from app.scanner.hashing import hash_file

BODY = bytes(range(256)) * 10


def test_plain_file_has_no_headerless_hash(tmp_path):
    p = tmp_path / "a.sfc"
    p.write_bytes(BODY)
    h = hash_file(str(p))
    assert h.sha1 == hashlib.sha1(BODY).hexdigest()
    assert h.crc32 == f"{zlib.crc32(BODY):08x}"
    assert h.sha1_nohdr is None


def test_ines_header_is_stripped_for_second_hash(tmp_path):
    data = b"NES\x1a" + bytes(12) + BODY
    p = tmp_path / "a.nes"
    p.write_bytes(data)
    h = hash_file(str(p))
    assert h.sha1 == hashlib.sha1(data).hexdigest()
    assert h.sha1_nohdr == hashlib.sha1(BODY).hexdigest()
    assert h.crc32_nohdr == f"{zlib.crc32(BODY):08x}"


def test_multi_chunk_file_matches_one_shot(tmp_path):
    data = b"NES\x1a" + bytes(12) + b"x" * (3 * 1024 * 1024 + 5)
    p = tmp_path / "big.nes"
    p.write_bytes(data)
    h = hash_file(str(p))
    assert h.sha1 == hashlib.sha1(data).hexdigest()
    assert h.sha1_nohdr == hashlib.sha1(data[16:]).hexdigest()
    assert h.crc32_nohdr == f"{zlib.crc32(data[16:]):08x}"
