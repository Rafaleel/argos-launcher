import os
import stat
import sys
import zipfile
from pathlib import Path

import pytest

from app.emulators import dolphin
from app.emulators.dolphin import Install, VideoSettings
from tests.conftest import REAL_IS_RUNNING

needs_7z = pytest.mark.skipif(not dolphin.seven_zip(), reason="7z not installed")


def flatpak_install():
    return dolphin.detect("/usr/bin/flatpak", ["run", dolphin.FLATPAK_ID, "-b"])


def test_detect_flatpak_native_and_others(tmp_path):
    fp = flatpak_install()
    assert fp.flatpak and fp.config_dir == Path.home() / ".var/app/org.DolphinEmu.dolphin-emu/config/dolphin-emu"
    assert fp.data_dir.name == "dolphin-emu" and "data" in fp.data_dir.parts
    nat = dolphin.detect("/usr/bin/dolphin-emu", ["{rom}"])
    assert nat and not nat.flatpak and nat.data_dir == Path.home() / ".local/share/dolphin-emu"
    assert dolphin.detect("/usr/bin/flatpak", ["run", "org.libretro.RetroArch"]) is None
    assert dolphin.detect("/usr/bin/retroarch", ["{rom}"]) is None


def test_settings_validation_rejects_unknown_and_out_of_range():
    with pytest.raises(ValueError):
        VideoSettings(color="red")
    for bad in ({"internal_resolution": 0}, {"internal_resolution": 9}, {"anisotropy": 5}, {"backend": "D3D"}, {"gpu": "amd"}):
        with pytest.raises(ValueError):
            VideoSettings(**bad)
    assert VideoSettings(internal_resolution=3, vsync=False).model_dump(exclude_none=True) == {
        "internal_resolution": 3,
        "vsync": False,
    }


def test_game_settings_override_defaults_and_none_inherits():
    assert dolphin.effective({"vsync": True, "internal_resolution": 2}, {"internal_resolution": 4, "vsync": None}) == {
        "vsync": True,
        "internal_resolution": 4,
    }


def test_ini_edit_keeps_everything_else(tmp_path):
    ini = tmp_path / "GHAE08.ini"
    ini.write_text("# my note\n[Core]\nCPUCore = 1\n\n[Video_Settings]\nHiresTextures = True\nOther = x\n\n[Video_Hardware]\nVSync = True\n")
    dolphin.set_ini_values(ini, {("Video_Settings", "HiresTextures"): "False", ("Video_Settings", "InternalResolution"): "3", ("Video_Enhancements", "MaxAnisotropy"): "2"})
    text = ini.read_text()
    assert "# my note" in text and "CPUCore = 1" in text and "Other = x" in text and "VSync = True" in text
    assert "HiresTextures = False" in text and text.count("HiresTextures") == 1
    assert "InternalResolution = 3" in text and "[Video_Enhancements]\nMaxAnisotropy = 2" in text
    # the new key landed inside its own section, before the next header
    assert text.index("InternalResolution") < text.index("[Video_Hardware]")


def test_ini_is_created_and_none_settings_do_not_touch_it(tmp_path):
    ins = Install(False, tmp_path / "c", tmp_path / "d")
    dolphin.apply_game_settings(ins, "GHAE08", {})
    assert not (tmp_path / "d" / "GameSettings" / "GHAE08.ini").exists()
    dolphin.apply_game_settings(ins, "GHAE08", {"vsync": False, "hires_textures": True, "backend": "Vulkan", "gpu": "nvidia"})
    text = (tmp_path / "d" / "GameSettings" / "GHAE08.ini").read_text()
    assert "VSync = False" in text and "HiresTextures = True" in text
    assert "Vulkan" not in text and "nvidia" not in text  # those are not INI settings


def test_launch_plan_flatpak_puts_env_before_the_app_id():
    args = ["run", dolphin.FLATPAK_ID, "-b", "-e", "{rom}"]
    new, env = dolphin.launch_plan(flatpak_install(), args, {"gpu": "nvidia", "backend": "Vulkan"})
    assert env == {} and args == ["run", dolphin.FLATPAK_ID, "-b", "-e", "{rom}"]  # input untouched
    assert new[0] == "run" and new[1].startswith("--env=__NV_PRIME_RENDER_OFFLOAD=1")
    assert new.index(dolphin.FLATPAK_ID) == 1 + len(dolphin.NVIDIA_ENV)
    assert new[-2:] == ["-v", "Vulkan"]


def test_launch_plan_native_uses_the_environment_and_default_changes_nothing():
    nat = dolphin.detect("/usr/bin/dolphin-emu", ["{rom}"])
    new, env = dolphin.launch_plan(nat, ["{rom}"], {"gpu": "nvidia"})
    assert new == ["{rom}"] and env == dolphin.NVIDIA_ENV
    assert dolphin.launch_plan(nat, ["{rom}"], {"internal_resolution": 3}) == (["{rom}"], {})


def test_read_game_id(tmp_path):
    ok, bad, short = tmp_path / "a.iso", tmp_path / "b.iso", tmp_path / "c.iso"
    ok.write_bytes(b"GHAE08" + bytes(10))
    bad.write_bytes(b"ghae08" + bytes(10))
    short.write_bytes(b"GH")
    assert dolphin.read_game_id(str(ok)) == "GHAE08"
    assert dolphin.read_game_id(str(bad)) is None and dolphin.read_game_id(str(short)) is None
    assert dolphin.read_game_id(str(tmp_path / "missing")) is None


# ---------------------------------------------------------------- controls


def test_pad_preset_keeps_other_pads_and_backs_up_once(tmp_path):
    ins = Install(False, tmp_path / "c", tmp_path / "d")
    ins.config_dir.mkdir()
    pad = ins.config_dir / "GCPadNew.ini"
    pad.write_text("[GCPad1]\nDevice = old\nButtons/A = `Q`\n[GCPad2]\nDevice = XInput2/0/Virtual core pointer\nButtons/A = `Z`\n")
    dolphin.write_pad1(ins, "keyboard_wasd", None)
    text = pad.read_text()
    assert "Main Stick/Up = `W`" in text and "Device = old" not in text and "Buttons/A = `Q`" not in text
    assert "[GCPad2]" in text and "Buttons/A = `Z`" in text  # other players untouched
    assert dolphin.read_pad1_device(ins) == dolphin.KB_DEVICE
    first = (ins.config_dir / "GCPadNew.ini.argos-bak").read_text()
    assert "Device = old" in first
    dolphin.write_pad1(ins, "xbox", "SDL/0/Xbox Wireless Controller")
    assert (ins.config_dir / "GCPadNew.ini.argos-bak").read_text() == first  # the original is never overwritten
    assert "Buttons/A = `Button A`" in pad.read_text() and dolphin.read_pad1_device(ins) == "SDL/0/Xbox Wireless Controller"
    assert pad.read_text().count("[GCPad1]") == 1


@pytest.mark.parametrize("device", [None, "", "Xbox", "SDL/0/x\n[GCPad2]", "SDL/0/a=b", "SDL/x/pad", "SDL/0/`rm`"])
def test_bad_controller_devices_are_refused(tmp_path, device):
    ins = Install(False, tmp_path / "c", tmp_path / "d")
    with pytest.raises(ValueError):
        dolphin.write_pad1(ins, "xbox", device)
    assert not (ins.config_dir / "GCPadNew.ini").exists()


def test_unknown_preset_is_refused_and_keyboard_ignores_the_device(tmp_path):
    ins = Install(False, tmp_path / "c", tmp_path / "d")
    with pytest.raises(ValueError):
        dolphin.write_pad1(ins, "mouse", None)
    dolphin.write_pad1(ins, "keyboard_default", "SDL/0/ignored")
    assert dolphin.read_pad1_device(ins) == dolphin.KB_DEVICE


# ---------------------------------------------------------------- texture packs


def make_zip(path, names, *, link=None):
    with zipfile.ZipFile(path, "w") as z:
        for n in names:
            z.writestr(n, b"x" * 100)
        if link:
            info = zipfile.ZipInfo(link)
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(info, "/etc/passwd")


@needs_7z
def test_pack_installs_replaces_and_removes(tmp_path):
    ins = Install(False, tmp_path / "c", tmp_path / "d")
    first, second = tmp_path / "a.zip", tmp_path / "b.zip"
    make_zip(first, ["GHA/Rooms/a.dds", "GHA/Rooms/old.dds"])
    make_zip(second, ["GHA/Rooms/a.dds", "GHA/Rooms/new.dds"])
    dolphin.install_pack(ins, "GHAE08", str(first))
    assert dolphin.pack_status(ins, "GHAE08") == {"installed": True, "folder": "GHA", "files": 2, "bytes": 200}
    dolphin.install_pack(ins, "GHAE08", str(second))
    root = dolphin.textures_root(ins)
    assert not (root / "GHA/Rooms/old.dds").exists() and (root / "GHA/Rooms/new.dds").exists()  # a replace, not a merge
    assert [p.name for p in root.iterdir()] == ["GHA"]  # no staging left behind
    assert dolphin.remove_pack(ins, "GHAE08") and not dolphin.pack_status(ins, "GHAE08")["installed"]
    assert not dolphin.remove_pack(ins, "GHAE08")


@needs_7z
@pytest.mark.parametrize(
    "names",
    [["GLE/Rooms/a.dds"], ["GHA/ok.dds", "evil.txt"], ["GHA/../../evil.dds"], ["/abs/evil.dds"], ["GHAX/a.dds"]],
    ids=["other-game", "file-outside-folder", "dotdot", "absolute", "similar-name"],
)
def test_pack_for_another_game_or_with_unsafe_paths_is_refused(tmp_path, names):
    ins = Install(False, tmp_path / "c", tmp_path / "d")
    z = tmp_path / "bad.zip"
    make_zip(z, names)
    with pytest.raises(dolphin.PackError):
        dolphin.install_pack(ins, "GHAE08", str(z))
    assert not list(tmp_path.glob("evil*")) and not (tmp_path / "d" / "Load" / "Textures" / "GHA").exists()


@needs_7z
def test_pack_with_a_symlink_is_refused_and_cleaned_up(tmp_path):
    ins = Install(False, tmp_path / "c", tmp_path / "d")
    z = tmp_path / "link.zip"
    make_zip(z, ["GHA/a.dds"], link="GHA/link")
    with pytest.raises(dolphin.PackError):
        dolphin.install_pack(ins, "GHAE08", str(z))
    root = dolphin.textures_root(ins)
    assert not (root / "GHA").exists() and not any(p.name.startswith(".argos") for p in root.iterdir())


@needs_7z
def test_pack_needs_disk_space_and_a_readable_archive(tmp_path, monkeypatch):
    ins = Install(False, tmp_path / "c", tmp_path / "d")
    z = tmp_path / "a.zip"
    make_zip(z, ["GHA/a.dds"])
    junk = tmp_path / "junk.zip"
    junk.write_bytes(b"not an archive")
    with pytest.raises(dolphin.PackError):
        dolphin.install_pack(ins, "GHAE08", str(junk))
    monkeypatch.setattr(dolphin.shutil, "disk_usage", lambda p: type("U", (), {"free": 1024})())
    with pytest.raises(dolphin.PackError, match="espaço"):
        dolphin.install_pack(ins, "GHAE08", str(z))
    assert not dolphin.pack_status(ins, "GHAE08")["installed"]


@needs_7z
def test_background_install_reports_progress_and_blocks_a_second_one(tmp_path):
    ins = Install(False, tmp_path / "c", tmp_path / "d")
    z = tmp_path / "a.zip"
    make_zip(z, ["GHA/a.dds"])
    assert dolphin.start_install(ins, "GHAE08", str(z))
    assert dolphin.JOB["state"] == "running"
    for t in list(dolphin.MONITORS):
        t.join(timeout=30)
    assert dolphin.JOB["state"] == "done" and dolphin.pack_status(ins, "GHAE08")["installed"]
    dolphin._pack_lock.acquire()  # an install is "running": a second one must be refused
    try:
        assert not dolphin.start_install(ins, "GHAE08", str(z))
    finally:
        dolphin._pack_lock.release()
    bad = tmp_path / "bad.zip"
    make_zip(bad, ["XXX/a.dds"])
    assert dolphin.start_install(ins, "GHAE08", str(bad))
    for t in list(dolphin.MONITORS):
        t.join(timeout=30)
    assert dolphin.JOB["state"] == "error" and "não é deste jogo" in dolphin.JOB["message"]


LSPCI = (
    '00:02.0 "VGA compatible controller" "Intel Corporation" "Raptor Lake-P [UHD Graphics]" -r04 -p00 "Acer Incorporated [ALI]" "Device 171e"\n'
    '00:1f.3 "Audio device" "Intel Corporation" "Raptor Lake-P/U/H cAVS" -r01 -p80 "Acer Incorporated [ALI]" "Device 171e"\n'
    '01:00.0 "VGA compatible controller" "NVIDIA Corporation" "AD107M [GeForce RTX 4060 Max-Q / Mobile]" -ra1 -p00 "Acer Incorporated [ALI]" "Device 171e"\n'
)


def test_gpu_names_use_the_chip_vendor_not_the_board_vendor(monkeypatch):
    monkeypatch.setattr(dolphin.subprocess, "run", lambda *a, **k: type("R", (), {"stdout": LSPCI})())
    assert dolphin.gpu_names() == (
        "Intel Corporation Raptor Lake-P [UHD Graphics]",
        "NVIDIA Corporation AD107M [GeForce RTX 4060 Max-Q / Mobile]",
    )


def test_gpu_names_survive_a_missing_lspci(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError("lspci")

    monkeypatch.setattr(dolphin.subprocess, "run", boom)
    assert dolphin.gpu_names() == ()


XPAD = 'I: Bus=0005 Vendor=045e Product=0b13\nN: Name="Xbox Wireless Controller"\nH: Handlers=event12\nB: KEY=7cdb000000000000 0 0 0 0\n'
KEYBOARD = 'I: Bus=0011\nN: Name="AT Translated Set 2 keyboard"\nH: Handlers=sysrq kbd event3\nB: KEY=402000000 3803078f800d001 feffffdfffefffff fffffffffffffffe\n'
STICK = 'I: Bus=0003\nN: Name="Old Joystick"\nH: Handlers=event9 js0\nB: KEY=ffff00000000 0 0 0 0\n'


def test_kernel_fallback_finds_pads_by_their_buttons_not_by_js(tmp_path, monkeypatch):
    fake = tmp_path / "devices"
    fake.write_text("\n".join([XPAD, KEYBOARD, STICK]))
    real = Path
    monkeypatch.setattr(dolphin, "Path", lambda p: fake if p == "/proc/bus/input/devices" else real(p))
    monkeypatch.setattr(dolphin, "sdl_gamepads", lambda: None)  # no SDL3 installed
    assert [c["name"] for c in dolphin.controller_candidates()] == ["Xbox Wireless Controller", "Old Joystick"]
    assert dolphin.controller_candidates()[0] == {"name": "Xbox Wireless Controller", "device": "SDL/0/Xbox Wireless Controller", "source": "kernel"}


def test_sdl_names_win_and_identical_pads_are_numbered_like_dolphin(monkeypatch):
    monkeypatch.setattr(dolphin, "sdl_gamepads", lambda: [("Xbox Series X Controller", "Xbox Wireless Controller"), ("PS5 Controller", "PS5 Controller"), ("Xbox Series X Controller", "Xbox Wireless Controller")])
    assert [c["name"] for c in dolphin.controller_candidates()][0] == "Xbox Wireless Controller"  # shown name is the hardware one
    assert [c["device"] for c in dolphin.controller_candidates()] == [
        "SDL/0/Xbox Series X Controller", "SDL/0/PS5 Controller", "SDL/1/Xbox Series X Controller"]
    assert all(c["source"] == "sdl" for c in dolphin.controller_candidates())


def test_no_sdl_library_is_not_an_error(monkeypatch):
    def missing(name):
        raise OSError("libSDL3.so.0: cannot open shared object file")
    monkeypatch.setattr(dolphin.ctypes, "CDLL", missing)
    assert dolphin.sdl_gamepads() is None


def test_gpu_lookup_runs_lspci_only_once(monkeypatch):
    calls = []
    monkeypatch.setattr(dolphin.subprocess, "run", lambda *a, **k: calls.append(1) or type("R", (), {"stdout": LSPCI})())
    dolphin.gpu_names(), dolphin.gpu_names(), dolphin.gpu_names()
    assert len(calls) == 1  # lspci took 2 s and woke the sleeping NVIDIA card on every refresh


def test_detect_exported_flatpak_wrapper_and_nogui_running(tmp_path):
    wrapper = dolphin.detect("/var/lib/flatpak/exports/bin/org.DolphinEmu.dolphin-emu", ["-b", "-e", "{rom}"])
    assert wrapper.flatpak and "/.var/app/" in str(wrapper.data_dir)  # not the native folders
    for comm, expected in (("dolphin-emu", True), ("dolphin-emu-nog", True), ("firefox", False)):
        proc = tmp_path / comm
        (proc / "123").mkdir(parents=True)
        (proc / "123" / "comm").write_text(comm + "\n")
        assert REAL_IS_RUNNING(str(proc)) is expected


def test_wrapper_cannot_select_the_gpu_and_says_so():
    wrapper = dolphin.detect("/var/lib/flatpak/exports/bin/org.DolphinEmu.dolphin-emu", [])
    with pytest.raises(ValueError, match="flatpak"):
        dolphin.launch_plan(wrapper, ["-b"], {"gpu": "nvidia"})
    assert dolphin.launch_plan(wrapper, ["-b"], {"internal_resolution": 2}) == (["-b"], {})  # no GPU asked: fine


def test_default_undoes_what_argos_wrote_but_not_what_the_user_wrote(tmp_path):
    ins = Install(False, tmp_path / "c", tmp_path / "d")
    ini = ins.data_dir / "GameSettings" / "GHAE08.ini"
    ini.parent.mkdir(parents=True)
    ini.write_text("[Video_Settings]\nHiresTextures = True\n[Video_Hardware]\nVSync = True\n")  # the user's own keys
    wrote = dolphin.apply_game_settings(ins, "GHAE08", {"internal_resolution": 6, "vsync": False})
    assert "InternalResolution = 6" in ini.read_text() and "VSync = False" in ini.read_text()
    wrote = dolphin.apply_game_settings(ins, "GHAE08", {}, frozenset(wrote))  # back to "Padrão"
    text = ini.read_text()
    assert "InternalResolution" not in text and "VSync" not in text  # Argos' keys are gone
    assert "HiresTextures = True" in text  # the user's own key survives
    dolphin.apply_game_settings(ins, "GHAE08", {}, frozenset())  # nothing recorded: nothing removed
    assert "HiresTextures = True" in ini.read_text()


def test_ini_keeps_crlf_non_utf8_bytes_case_and_symlink_and_mode(tmp_path):
    real = tmp_path / "real.ini"
    real.write_bytes(b"; Ol\xe1\r\n[Video_Hardware]\r\nvsync = True\r\n")  # Latin-1 comment, CRLF, lower-case key
    real.chmod(0o640)
    link = tmp_path / "GHAE08.ini"
    link.symlink_to(real)
    dolphin.set_ini_values(link, {("Video_Hardware", "VSync"): "False", ("Video_Settings", "InternalResolution"): "3"})
    assert link.is_symlink()  # written through, not replaced
    raw = real.read_bytes()
    assert b"; Ol\xe1\r\n" in raw and raw.count(b"\r\n") == raw.count(b"\n")  # bytes and CRLF kept
    assert raw.lower().count(b"vsync") == 1 and b"VSync = False" in raw  # same key, no duplicate
    assert (real.stat().st_mode & 0o777) == 0o640
    fresh = tmp_path / "new.ini"
    dolphin.set_ini_values(fresh, {("A", "b"): "1"})
    assert (fresh.stat().st_mode & 0o777) == 0o644


def test_pad_device_with_trailing_newline_is_refused_and_unreadable_pad_file_is_tolerated(tmp_path):
    ins = Install(False, tmp_path / "c", tmp_path / "d")
    with pytest.raises(ValueError):
        dolphin.write_pad1(ins, "xbox", "SDL/0/Pad\n")
    ins.config_dir.mkdir()
    (ins.config_dir / "GCPadNew.ini").write_bytes(b"[GCPad1]\nDevice = SDL/0/Pad\xe9\n")
    assert dolphin.read_pad1_device(ins).startswith("SDL/0/Pad")  # used to raise UnicodeDecodeError
    dolphin.write_pad1(ins, "keyboard_wasd", None)  # and writing over it works


def test_pack_status_survives_a_broken_symlink(tmp_path):
    ins = Install(False, tmp_path / "c", tmp_path / "d")
    pack = dolphin.textures_root(ins) / "GHA"
    pack.mkdir(parents=True)
    (pack / "a.dds").write_bytes(b"x" * 10)
    (pack / "broken").symlink_to(tmp_path / "nowhere")
    assert dolphin.pack_status(ins, "GHAE08")["installed"] is True


def test_window_and_input_options_become_config_overrides():
    nat = dolphin.detect("/usr/bin/dolphin-emu", ["-b", "-e", "{rom}"])
    args, env = dolphin.launch_plan(nat, ["-e", "{rom}"], {"render_to_main": True, "background_input": False, "keep_on_top": True})
    assert args == ["-e", "{rom}", "-C", "Dolphin.Display.RenderToMain=True", "-C", "Dolphin.Input.BackgroundInput=False",
                    "-C", "Dolphin.Display.KeepWindowOnTop=True"] and env == {}
    assert dolphin.launch_plan(nat, ["{rom}"], {"vsync": True}) == (["{rom}"], {})  # not set: nothing added
    for bad in ({"render_to_main": "yes please"},):
        with pytest.raises(ValueError):
            VideoSettings(**bad)


@pytest.mark.parametrize("flag", ["-b", "--batch"])
def test_render_to_main_is_refused_in_batch_mode(flag):
    # batch mode never shows Dolphin's main window: rendering there would hide the game
    nat = dolphin.detect("/usr/bin/dolphin-emu", [])
    with pytest.raises(ValueError, match="-b"):
        dolphin.launch_plan(nat, [flag, "-e", "{rom}"], {"render_to_main": True})
    assert dolphin.launch_plan(nat, [flag, "-e", "{rom}"], {"render_to_main": False})[0][-1] == "Dolphin.Display.RenderToMain=False"
