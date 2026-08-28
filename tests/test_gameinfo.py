"""The info panel: what is actually known about one game.

Most of it is only interesting when it is wrong -- a core that is not
installed, a ROM that has gone, a BIOS that is missing -- so those are what
this checks, along with the save state, which is the line that tells you
whether "Start fresh" will change anything.

The add-on imports Kodi's modules, which only exist inside Kodi, so they are
stubbed here. Nothing in game_info draws anything.
"""
import importlib.machinery
import importlib.util
import json
import os
import sys
import tempfile
import types

for name in ("xbmc", "xbmcgui", "xbmcplugin", "xbmcaddon", "xbmcvfs"):
    module = types.ModuleType(name)
    module.__getattr__ = lambda attr: (lambda *a, **k: None)
    sys.modules[name] = module
sys.modules["xbmcgui"].ListItem = lambda *a, **k: types.SimpleNamespace(
    setLabel2=lambda *a: None, setInfo=lambda *a: None, setArt=lambda *a: None,
    setProperty=lambda *a: None, addContextMenuItems=lambda *a: None)
sys.modules["xbmcgui"].Dialog = lambda: types.SimpleNamespace(
    ok=lambda *a: None, textviewer=lambda *a, **k: None)
sys.argv = ["plugin://x", "1", ""]

# The repository this test lives in, rather than a path with a clone name in
# it. The README promises the clone can go anywhere and be called anything;
# hard-coding one machine's name for it broke every one of these on a fresh
# install, where it is called something else.
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
loader = importlib.machinery.SourceFileLoader(
    "ra", os.path.join(REPO, "addons", "plugin.program.retroarch",
                       "main.py"))
ra = importlib.util.module_from_spec(
    importlib.util.spec_from_loader("ra", loader))
loader.exec_module(ra)

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


tmp = tempfile.mkdtemp(prefix="gameinfo-")
rom = os.path.join(tmp, "Super Test (USA).sfc")
open(rom, "wb").write(b"\0" * 4096)
core = os.path.join(tmp, "snes9x_libretro.so")
open(core, "wb").write(b"\0")

SYSTEM = "Nintendo - Super Nintendo Entertainment System"
entry = {"path": rom, "label": "Super Test (USA)", "core_path": core,
         "core_name": "Nintendo - SNES (Snes9x)", "crc32": "6A187C70|crc"}

print("what is on disk")
text = ra.game_info(SYSTEM, entry)
check(rom in text, "the full path is there, which is the point of the panel")
check("4.0 kB" in text, "and how big it is: %s" %
      [l for l in text.splitlines() if "kB" in l])
check("Super Nintendo" in text, "the console reads as its short name")
check("CRC 6A187C70" in text, "and the CRC it was identified by")

print("a core that is not installed says so")
text = ra.game_info(SYSTEM, dict(entry, core_path=os.path.join(tmp, "gone.so")))
check("NOT INSTALLED" in text, "because otherwise it is a black screen and no reason")

print("a ROM that has gone says so")
text = ra.game_info(SYSTEM, dict(entry, path=os.path.join(tmp, "gone.sfc")))
check("MISSING" in text, "rather than showing a size for a file that is not there")

print("a game found on disk rather than in the database")
text = ra.game_info(SYSTEM, dict(entry, crc32="00000000|crc"))
check("no CRC" in text, "says where it came from instead of showing a fake CRC")

print("the save state is what says whether Start fresh changes anything")
was_states, ra.STATES_DIR = ra.STATES_DIR, tmp
was_saves, ra.SAVES_DIR = ra.SAVES_DIR, tmp
try:
    text = ra.game_info(SYSTEM, entry)
    check("No save state" in text, "with none there, it starts at the title screen")

    sorted_dir = os.path.join(tmp, "Nintendo - SNES (Snes9x)")
    os.makedirs(sorted_dir, exist_ok=True)
    state = os.path.join(sorted_dir, "Super Test (USA).state.auto")
    open(state, "wb").write(b"\0" * 2048)
    text = ra.game_info(SYSTEM, entry)
    check("Resumes from" in text, "with one there, it says when it was made")
    check(state in text, "and where it is, wherever RetroArch filed it")
    check("Start fresh" in text, "and what to do about it")

    srm = os.path.join(sorted_dir, "Super Test (USA).srm")
    open(srm, "wb").write(b"\0" * 512)
    text = ra.game_info(SYSTEM, entry)
    check("In-game save" in text,
          "the battery save is listed separately, being a different thing")
finally:
    ra.STATES_DIR, ra.SAVES_DIR = was_states, was_saves

print("a system that needs a BIOS says whether it has one")
text = ra.game_info("Sega - Mega-CD - Sega CD",
                    dict(entry, core_name="Genesis Plus GX"))
check("BIOS" in text, "the requirement is named: %s" %
      [l.strip() for l in text.splitlines() if "BIOS" in l])

print(("FAILED: %d" % len(fails)) if fails else "test_gameinfo: all ok")
sys.exit(1 if fails else 0)
