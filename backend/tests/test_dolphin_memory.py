import pytest

from app.emulators.dolphin_memory import MEM1_SIZE, DolphinMemory, DolphinMemoryError

BASE = 0x1000  # any value works: the reader only seeks to base + address


def fake_proc(tmp_path, pid, comm, maps, ram=b""):
    d = tmp_path / str(pid)
    d.mkdir()
    (d / "comm").write_text(comm + "\n")
    (d / "maps").write_text(maps)
    mem = bytearray(BASE) + ram
    (d / "mem").write_bytes(bytes(mem))


def mapping(start, size, offset, path):
    return f"{start:x}-{start + size:x} rw-s {offset:08x} 00:50 2   {path}\n"


def test_reads_mem1_and_skips_wrapper_and_other_mappings(tmp_path):
    # the Flatpak wrapper shell also has a comm starting with dolphin-emu, but no shm mapping
    fake_proc(tmp_path, 100, "dolphin-emu-wra", "")
    maps = mapping(0x7000, 0x2000000, 0x2040000, "/dev/shm/dolphin-emu.33 (deleted)") + \
        mapping(BASE, MEM1_SIZE, 0, "/dev/shm/dolphin-emu.33 (deleted)")
    fake_proc(tmp_path, 200, "dolphin-emu", maps, b"GHAE08" + b"\x00" * (0x168A4D - 6) + b"\x00\x00\x01")
    mem = DolphinMemory.attach(str(tmp_path))
    assert (mem.pid, mem.base) == (200, BASE)
    assert mem.read(0, 6) == b"GHAE08"
    assert mem.read(0x168A4D, 3) == b"\x00\x00\x01"
    mem.close()


def test_no_dolphin_or_no_game_is_none(tmp_path):
    assert DolphinMemory.attach(str(tmp_path)) is None
    fake_proc(tmp_path, 1, "dolphin-emu", "")
    fake_proc(tmp_path, 2, "firefox", mapping(BASE, MEM1_SIZE, 0, "/dev/shm/dolphin-emu.1"))
    assert DolphinMemory.attach(str(tmp_path)) is None


def test_reads_outside_mem1_are_refused(tmp_path):
    fake_proc(tmp_path, 3, "dolphin-emu", mapping(BASE, MEM1_SIZE, 0, "/dev/shm/dolphin-emu.1"))
    mem = DolphinMemory.attach(str(tmp_path))
    for addr, size in ((-1, 1), (MEM1_SIZE - 1, 2), (0, 0)):
        with pytest.raises(ValueError):
            mem.read(addr, size)


def test_dolphin_memory_of_another_size_is_explained(tmp_path):
    fake_proc(tmp_path, 4, "dolphin-emu", mapping(BASE, 0x4000000, 0, "/dev/shm/dolphin-emu.1") +
              mapping(BASE * 8, 0x2000000, 0, "/dev/shm/dolphin-emu.1"))
    with pytest.raises(DolphinMemoryError, match=r"32 MB, 64 MB.*24 MB"):
        DolphinMemory.attach(str(tmp_path))


def test_unreadable_maps_say_it_is_a_permission_problem(tmp_path):
    fake_proc(tmp_path, 5, "dolphin-emu", "")
    (tmp_path / "5" / "maps").chmod(0)
    with pytest.raises(DolphinMemoryError, match="permissão"):
        DolphinMemory.attach(str(tmp_path))
