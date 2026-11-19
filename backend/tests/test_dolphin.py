import os
import stat
import sys
import zipfile
from pathlib import Path

import pytest

from app.emulators import dolphin
from app.emulators.dolphin import Install, VideoSettings

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
    assert dolphin.gpu_names() == [
        "Intel Corporation Raptor Lake-P [UHD Graphics]",
        "NVIDIA Corporation AD107M [GeForce RTX 4060 Max-Q / Mobile]",
    ]


def test_gpu_names_survive_a_missing_lspci(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError("lspci")

    monkeypatch.setattr(dolphin.subprocess, "run", boom)
    assert dolphin.gpu_names() == []


def test_controller_candidates_only_list_devices_with_a_js_handler(tmp_path, monkeypatch):
    text = (
        'I: Bus=0003 Vendor=045e Product=0b13\nN: Name="Xbox Wireless Controller"\nH: Handlers=event12 js0\n\n'
        'I: Bus=0011\nN: Name="AT Translated Set 2 keyboard"\nH: Handlers=sysrq kbd event3\n\n'
    )
    fake = tmp_path / "devices"
    fake.write_text(text)
    real = Path
    monkeypatch.setattr(dolphin, "Path", lambda p: fake if p == "/proc/bus/input/devices" else real(p))
    assert dolphin.controller_candidates() == [{"name": "Xbox Wireless Controller", "device": "SDL/0/Xbox Wireless Controller"}]
