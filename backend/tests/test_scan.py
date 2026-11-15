import hashlib
import os
import zlib

from app.launcher.launch import playable_file
from app.scanner import scan as scan_mod
from app.scanner.scan import scan
from tests.conftest import dat_xml

BODY = bytes(range(256)) * 10
NES = "Nintendo - Nintendo Entertainment System"


def sha(b):
    return hashlib.sha1(b).hexdigest()


def crc(b):
    return f"{zlib.crc32(b):08x}"


def setup_nes(tmp_path):
    roms, dats = tmp_path / "roms", tmp_path / "dats"
    roms.mkdir(), dats.mkdir()
    (roms / "mario.nes").write_bytes(b"NES\x1a" + bytes(12) + BODY)  # headered ROM
    (dats / "nes.dat").write_text(dat_xml(NES, [("Mario (USA)", [("Mario (USA).nes", len(BODY), crc(BODY), sha(BODY))])]))
    return str(roms), str(dats)


def games(conn):
    return conn.execute("SELECT title, platform, identified FROM games ORDER BY title").fetchall()


def test_headered_nes_matches_headerless_dat(conn, tmp_path):
    roms, dats = setup_nes(tmp_path)
    scan(conn, [roms], [dats])
    [g] = games(conn)
    assert (g["title"], g["platform"], g["identified"]) == ("Mario (USA)", NES, 1)


def test_unknown_file_is_listed_unidentified(conn, tmp_path):
    roms = tmp_path / "roms"
    roms.mkdir()
    (roms / "homebrew.gba").write_bytes(b"xyz")
    scan(conn, [str(roms)], [])
    [g] = games(conn)
    assert (g["title"], g["platform"], g["identified"]) == ("homebrew", None, 0)


def test_rescan_does_not_duplicate_and_uses_cache(conn, tmp_path, monkeypatch):
    roms, dats = setup_nes(tmp_path)
    first = scan(conn, [roms], [dats])
    calls = []
    real = scan_mod.hash_file
    monkeypatch.setattr(scan_mod, "hash_file", lambda p: calls.append(p) or real(p))
    second = scan(conn, [roms], [dats])
    assert first["files_hashed"] == 1 and second["files_cached"] == 1 and calls == []
    assert len(games(conn)) == 1
    assert conn.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 1


def test_game_id_is_stable_across_rescans(conn, tmp_path):
    roms, dats = setup_nes(tmp_path)
    scan(conn, [roms], [dats])
    before = conn.execute("SELECT id FROM games").fetchone()["id"]
    scan(conn, [roms], [dats])
    assert conn.execute("SELECT id FROM games").fetchone()["id"] == before


def test_vanished_file_and_its_game_are_removed(conn, tmp_path):
    roms, dats = setup_nes(tmp_path)
    scan(conn, [roms], [dats])
    os.remove(os.path.join(roms, "mario.nes"))
    result = scan(conn, [roms], [dats])
    assert result["files_removed"] == 1 and games(conn) == []


def test_missing_root_keeps_its_library(conn, tmp_path):
    roms, dats = setup_nes(tmp_path)
    scan(conn, [roms], [dats])
    result = scan(conn, [str(tmp_path / "unmounted")], [dats])
    assert len(games(conn)) == 1 and result["errors"]


def test_cue_and_tracks_form_one_game_played_from_cue(conn, tmp_path):
    roms, dats = tmp_path / "roms", tmp_path / "dats"
    roms.mkdir(), dats.mkdir()
    cue, t1, t2 = b"FILE t1 BINARY", b"track one", b"track two"
    (roms / "g.cue").write_bytes(cue)
    (roms / "g (Track 1).bin").write_bytes(t1)
    (roms / "g (Track 2).bin").write_bytes(t2)
    rom_rows = [("g.cue", len(cue), crc(cue), sha(cue)), ("t1.bin", len(t1), crc(t1), sha(t1)), ("t2.bin", len(t2), crc(t2), sha(t2))]
    (dats / "ps1.dat").write_text(dat_xml("Sony - PlayStation", [("Game (USA)", rom_rows)]))
    scan(conn, [str(roms)], [str(dats)])
    [g] = games(conn)
    assert g["title"] == "Game (USA)"
    paths = [r["path"] for r in conn.execute("SELECT path FROM files")]
    assert len(paths) == 3 and playable_file(paths).endswith("g.cue")
