"""The config guard, and the launch failures the picker now reports.

config_save_on_exit rewrites retroarch.cfg on every exit, so a bad write is
permanent -- this is the thing standing between that and every game silently
refusing to start.
"""
import importlib.machinery
import importlib.util
import os
import shutil
import sys
import tempfile

def repo_script(name):
    """The copy in this checkout, falling back to the installed one.

    These tests used to load ~/.local/bin/<name> outright -- the deployed copy.
    On the machine this was written on those are the same file, because the
    installer symlinks them; on a fresh clone they are not, so the suite
    quietly judged whatever happened to be installed and passed or failed on
    code that was not in front of it. A clone's tests should test the clone.
    """
    here = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "bin", name)
    return here if os.path.exists(here) else os.path.expanduser("~/.local/bin/" + name)


sys.argv = ["x"]


def load(name, path):
    ldr = importlib.machinery.SourceFileLoader(name, path)
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, ldr))
    ldr.exec_module(mod)
    return mod


g = load("guard", repo_script("ra_guard.py"))
rp = load("rp", repo_script("ra_players.py"))

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


SANE = ('video_driver = "gl"\n'
        'audio_driver = "pulse"\n'
        'input_driver = "x"\n'
        'input_joypad_driver = "udev"\n'
        'menu_driver = "ozone"\n'
        'some_other_setting = "left alone"\n')

print("-- what counts as a broken config --")
check(g.faults(g.read_cfg.__wrapped__ if False else
               {"video_driver": "gl", "audio_driver": "pulse",
                "input_driver": "x", "input_joypad_driver": "udev",
                "menu_driver": "ozone"}) == [],
      "a healthy config has no faults")
bad = g.faults({"video_driver": "sdl2", "input_driver": "null",
                "menu_driver": "ozone"})
check(("video_driver", "sdl2") in bad, "sdl2 is caught -- it segfaults on this GPU")
check(("input_driver", "null") in bad, "a null input driver is caught")
check(len(bad) == 2, "and nothing else is, got %r" % bad)
check(g.faults({"menu_driver": "ozone"}) == [],
      "a key that is simply absent is RetroArch's own default, not a fault")
check(g.faults(None) != [], "an unreadable config is a fault")

print("-- repairing touches the broken keys and nothing else --")
tmp = tempfile.mkdtemp(prefix="guard_")
real = (g.CFG, g.GOOD, g.MIN_SETTINGS)
try:
    g.CFG = os.path.join(tmp, "retroarch.cfg")
    g.GOOD = os.path.join(tmp, "known-good")
    g.MIN_SETTINGS = 3

    open(g.CFG, "w").write(SANE)
    check(g.main() == 0, "a healthy config passes")
    check(os.path.exists(g.GOOD), "and is kept as the known-good copy")

    # Exactly the damage that broke every launch on 2026-08-21.
    open(g.CFG, "w").write(SANE.replace('"gl"', '"sdl2"')
                               .replace('"pulse"', '"null"')
                               .replace('"ozone"', '"null"'))
    g.main()
    fixed = g.read_cfg(g.CFG)
    check(fixed["video_driver"] == "gl", "video driver restored")
    check(fixed["audio_driver"] == "pulse", "audio driver restored")
    check(fixed["menu_driver"] == "ozone", "menu driver restored")
    check(fixed["some_other_setting"] == "left alone",
          "and an unrelated setting was not touched")

    print("-- a truncated config is replaced outright --")
    # Half a line and nothing else: no complete setting survives.
    open(g.CFG, "w").write("video_dri")
    g.main()
    check(g.read_cfg(g.CFG)["input_joypad_driver"] == "udev",
          "the whole known-good copy came back")

    print("-- with no known-good copy it reports rather than guessing --")
    os.unlink(g.GOOD)
    open(g.CFG, "w").write("x")
    check(g.main() == 1, "a truncated config and no backup is an error")
finally:
    g.CFG, g.GOOD, g.MIN_SETTINGS = real
    shutil.rmtree(tmp)

print("-- deciding whether the picker is worth showing --")
check(rp.needs_picker(0, None) is False, "no pads: straight into the game")
check(rp.needs_picker(1, 1) is False, "one pad, one-player game: nothing to ask")
check(rp.needs_picker(2, 1) is True, "two pads on a one-player game: ask who plays")
check(rp.needs_picker(1, 2) is True, "one pad on a two-player game: ask")
check(rp.needs_picker(1, None) is True, "and ask when the count is unknown")

print("-- the board never offers more slots than the game can use --")
pads = [object()] * 3
check(rp.player_slots(pads, 2) == 2, "a two-player game shows two slots")
check(rp.player_slots(pads, None) == 4, "an unknown count shows the usual four")
check(rp.player_slots([object()] * 6, 8) == 8, "six pads on an eight-player game")
check(rp.player_slots([object()] * 6, 2) == 2, "but the game still decides")

print("-- what the player is told when a launch fails --")
log = os.path.join(tempfile.gettempdir(), "diag.log")
open(log, "w").write('[libretro ERROR] Unable to open CD BIOS: '
                     'os.path.expanduser("~/.local/share/retroarch/system/bios_CD_U.bin").\n')
check(rp.diagnose(log, 1, 2.0) == "Missing BIOS file: bios_CD_U.bin",
      "the missing BIOS is named, got %r" % rp.diagnose(log, 1, 2.0))
open(log, "w").write("RetroArch [ERROR] :: Failed to load content\n")
check(rp.diagnose(log, 1, 2.0) == "This game would not load", "a load failure")
open(log, "w").write("nothing interesting\n")
check(rp.diagnose(log, 0, 900.0) is None,
      "a game played for a quarter of an hour is not a failure")
check(rp.diagnose(log, 1, 900.0) is None,
      "and neither is quitting one, whatever the exit code")
check(rp.diagnose(log, 134, 1.0) == "RetroArch stopped straight away (code 134)",
      "a crash on startup is reported even with nothing in the log")
os.unlink(log)

print("\nFAILURES: %d" % len(fails))
sys.exit(1 if fails else 0)
