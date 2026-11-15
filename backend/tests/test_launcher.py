import json
import os
import stat
import sys
import time

import pytest

from app.launcher.launch import LaunchError, build_argv, launch, playable_file


def fake_emulator(tmp_path):
    exe = tmp_path / "fake-emu"
    exe.write_text(f"#!{sys.executable}\nimport json, sys\nopen(sys.argv[1], 'w').write(json.dumps(sys.argv[2:]))\n")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    return str(exe)


def wait_for(path):
    for _ in range(100):
        if os.path.exists(path) and os.path.getsize(path):
            return json.loads(open(path).read())
        time.sleep(0.05)
    raise AssertionError("emulator never ran")


def test_hostile_file_name_stays_one_plain_argument(tmp_path):
    out = tmp_path / "argv.json"
    hostile = tmp_path / 'x"; touch PWNED; $(touch PWNED2) `touch PWNED3`.nes'
    hostile.write_bytes(b"rom")
    pid = launch(fake_emulator(tmp_path), [str(out), "--fullscreen", "{rom}"], [str(hostile)])
    assert pid > 0
    assert wait_for(out) == ["--fullscreen", str(hostile)]
    assert not any(n.startswith("PWNED") for n in os.listdir(os.getcwd()) + os.listdir(tmp_path))


def test_placeholder_inside_a_longer_argument(tmp_path):
    assert build_argv("/bin/emu", ["--rom={rom}"], "/r/a.nes") == ["/bin/emu", "--rom=/r/a.nes"]


def test_rom_with_braces_is_not_reformatted():
    assert build_argv("/bin/emu", ["{rom}"], "/r/{0}.nes") == ["/bin/emu", "/r/{0}.nes"]


def test_cue_is_preferred_then_first_file():
    assert playable_file(["/r/b.bin", "/r/a.cue", "/r/a.bin"]) == "/r/a.cue"
    assert playable_file(["/r/b.nes"]) == "/r/b.nes"
    with pytest.raises(LaunchError):
        playable_file([])


def test_bad_executable_is_refused(tmp_path):
    with pytest.raises(LaunchError):
        launch("emu", ["{rom}"], ["/r/a.nes"])
    with pytest.raises(LaunchError):
        launch(str(tmp_path / "missing"), ["{rom}"], ["/r/a.nes"])
