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
    (tmp_path / "roms" / "other.gba").write_bytes(b"x")
    scan(conn, [roms], [dats])
    os.remove(os.path.join(roms, "mario.nes"))
    result = scan(conn, [roms], [dats])
    assert result["files_removed"] == 1
    assert [g["title"] for g in games(conn)] == ["other"]


def test_missing_root_keeps_its_library(conn, tmp_path):
    roms, dats = setup_nes(tmp_path)
    scan(conn, [roms], [dats])
    os.rename(roms, str(tmp_path / "gone"))  # drive unmounted: folder is missing
    result = scan(conn, [roms], [dats])
    assert len(games(conn)) == 1 and result["errors"]


def test_empty_root_keeps_its_library(conn, tmp_path):
    roms, dats = setup_nes(tmp_path)
    scan(conn, [roms], [dats])
    os.remove(os.path.join(roms, "mario.nes"))  # mount point left behind, empty
    result = scan(conn, [roms], [dats])
    assert len(games(conn)) == 1 and result["files_removed"] == 0 and result["errors"]


def test_unreadable_subfolder_keeps_its_games(conn, tmp_path):
    roms, dats = setup_nes(tmp_path)
    sub = tmp_path / "roms" / "sub"
    sub.mkdir()
    (sub / "hidden.gba").write_bytes(b"x")
    (tmp_path / "roms" / "other.gba").write_bytes(b"y")
    scan(conn, [roms], [dats])
    sub.chmod(0)
    try:
        result = scan(conn, [roms], [dats])
    finally:
        sub.chmod(0o755)
    assert result["files_removed"] == 0 and result["errors"]
    assert {g["title"] for g in games(conn)} == {"Mario (USA)", "hidden", "other"}


def test_folder_removed_from_settings_is_cleared(conn, tmp_path):
    roms, dats = setup_nes(tmp_path)
    other = tmp_path / "more"
    other.mkdir()
    (other / "b.gba").write_bytes(b"b")
    scan(conn, [roms, str(other)], [dats])
    scan(conn, [str(other)], [dats])
    assert [g["title"] for g in games(conn)] == ["b"]


def test_symlinked_root_does_not_duplicate_files(conn, tmp_path):
    roms, dats = setup_nes(tmp_path)
    (tmp_path / "link").symlink_to(roms)
    scan(conn, [roms, str(tmp_path / "link")], [dats])
    assert conn.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 1


def test_non_utf8_file_name_is_skipped_not_fatal(conn, tmp_path):
    roms = tmp_path / "roms"
    roms.mkdir()
    (roms / "ok.gba").write_bytes(b"x")
    open(os.path.join(os.fsencode(str(roms)), b"bad\xff.nes"), "wb").write(b"y")
    result = scan(conn, [str(roms)], [])
    assert [g["title"] for g in games(conn)] == ["ok"] and result["errors"]


def test_zip_and_chd_are_listed_as_unidentified(conn, tmp_path):
    roms = tmp_path / "roms"
    roms.mkdir()
    for n in ("g.zip", "g.chd", "g.rvz"):
        (roms / n).write_bytes(b"data")
    scan(conn, [str(roms)], [])
    assert len(games(conn)) == 3 and all(g["identified"] == 0 for g in games(conn))


def test_edited_cue_joins_its_identified_tracks(conn, tmp_path):
    roms, dats = tmp_path / "roms", tmp_path / "dats"
    roms.mkdir(), dats.mkdir()
    t1 = b"track one"
    (roms / "g (Track 1).bin").write_bytes(t1)
    (roms / "g.cue").write_bytes(b'FILE "g (Track 1).bin" BINARY\r\n')  # differs from the DAT's cue
    (dats / "ps1.dat").write_text(dat_xml("Sony - PlayStation", [("Game (USA)", [("t.bin", len(t1), crc(t1), sha(t1))])]))
    scan(conn, [str(roms)], [str(dats)])
    [g] = games(conn)
    assert g["title"] == "Game (USA)" and g["identified"] == 1
    paths = [r["path"] for r in conn.execute("SELECT path FROM files")]
    assert len(paths) == 2 and playable_file(paths).endswith("g.cue")


def test_unidentified_cue_and_tracks_are_one_game(conn, tmp_path):
    roms = tmp_path / "roms"
    roms.mkdir()
    (roms / "y (Track 1).bin").write_bytes(b"1")
    (roms / "y (Track 2).bin").write_bytes(b"2")
    (roms / "y.cue").write_bytes(b'FILE "y (Track 1).bin" BINARY\nFILE "y (Track 2).bin" BINARY\n')
    scan(conn, [str(roms)], [])
    [g] = games(conn)
    assert (g["title"], g["identified"]) == ("y", 0)


def test_truncated_dat_adds_nothing_and_headerless_dat_is_refused(conn, tmp_path):
    from app.scanner.dat import load_dats

    dats = tmp_path / "dats"
    dats.mkdir()
    full = dat_xml(NES, [("G", [("g.nes", 3, "00000001", "a" * 40)])])
    (dats / "cut.dat").write_text(full[: full.index("</game>")])
    (dats / "nohdr.dat").write_text('<datafile><game name="H"><rom name="h" size="3" crc="00000002" sha1="' + "b" * 40 + '"/></game></datafile>')
    index, errors = load_dats([str(dats)])
    assert not index.by_sha1 and len(errors) == 2


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
