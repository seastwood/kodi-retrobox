"""A game that cannot start says so before it is started.

preflight exists so that a game which cannot run does not present as the
screen going black and coming straight back with nothing said -- the plugin
sends RetroArch's output to /dev/null, so there is no other clue anywhere.

It was checking one system. The list of systems that cannot run a game without
a BIOS was a dict written out in the add-on with a single entry in it, Sega CD,
while system/bios.tsv -- which retrobox-ready reads, and which
bios-required.txt is the prose version of -- has twelve. So PlayStation,
Saturn, Dreamcast, 32X, 3DO, the Lynx and the rest were launched with nothing
checked at all. Two machines here have PlayStation games and no PlayStation
BIOS, and bios-required.txt promises in writing that "if a game refuses to
start, the launcher puts the reason on screen and names the file".

There is one list now, and it is the .tsv. What this checks is that the
add-on really reads it, that "any" and "all" mean different things, and that
the message names the file and where to put it.
"""
import importlib.machinery
import importlib.util
import os
import shutil
import sys
import tempfile
import types

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
MAIN = os.path.join(REPO, "addons", "plugin.program.retroarch", "main.py")

for name in ("xbmc", "xbmcgui", "xbmcplugin", "xbmcaddon", "xbmcvfs"):
    module = types.ModuleType(name)
    module.__getattr__ = lambda attr: (lambda *a, **k: None)
    sys.modules[name] = module
sys.argv = ["plugin://x", "1", ""]

loader = importlib.machinery.SourceFileLoader("ra", MAIN)
ra = importlib.util.module_from_spec(
    importlib.util.spec_from_loader("ra", loader))
loader.exec_module(ra)

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


def with_bios(*names):
    """A system directory holding exactly these files."""
    folder = tempfile.mkdtemp(prefix="bios-")
    for name in names:
        path = os.path.join(folder, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "wb").write(b"\0" * 16)
    return folder


print("every system in bios.tsv is known to the add-on")
rules = ra.bios_rules()
rows = [l.split("\t") for l in
        open(os.path.join(REPO, "system", "bios.tsv"), encoding="utf-8")
        if l.strip() and not l.lstrip().startswith("#")]
check(len(rows) >= 12, "bios.tsv describes %d systems" % len(rows))
check(len(rules) == len(rows),
      "and all %d are reachable by system name, got %d -- a folder with no "
      "line in systems.tsv would silently drop out"
      % (len(rows), len(rules)))
check("Sony - PlayStation" in rules,
      "PlayStation among them, got %s" % sorted(rules)[:4])
check("Sega - Mega-CD - Sega CD" in rules, "and Sega CD, which used to be all "
      "of it")

print("\nany means one is enough; all means all of them")
was = ra.SYSTEM_DIR
try:
    # Sega CD: any one region's BIOS lets the discs of that region run.
    ra.SYSTEM_DIR = with_bios("bios_CD_U.bin")
    here, missing, rule = ra.bios_state("Sega - Mega-CD - Sega CD")
    check(rule == "any" and not missing,
          "one Sega CD BIOS is enough, got missing=%s" % missing)
    shutil.rmtree(ra.SYSTEM_DIR, ignore_errors=True)

    ra.SYSTEM_DIR = with_bios()
    here, missing, rule = ra.bios_state("Sega - Mega-CD - Sega CD")
    check(len(missing) == 3, "and none is not, got %s" % missing)
    shutil.rmtree(ra.SYSTEM_DIR, ignore_errors=True)

    # Dreamcast wants both, and they live in a subdirectory.
    ra.SYSTEM_DIR = with_bios("dc/dc_boot.bin")
    here, missing, rule = ra.bios_state("Sega - Dreamcast")
    check(rule == "all" and missing == ["dc/dc_flash.bin"],
          "half a Dreamcast BIOS is missing the other half, got %s" % missing)
    shutil.rmtree(ra.SYSTEM_DIR, ignore_errors=True)

    ra.SYSTEM_DIR = with_bios("dc/dc_boot.bin", "dc/dc_flash.bin")
    check(not ra.bios_state("Sega - Dreamcast")[1],
          "and both is both, found in the subdirectory they belong in")
    shutil.rmtree(ra.SYSTEM_DIR, ignore_errors=True)

    print("\na system that needs nothing is never complained about")
    ra.SYSTEM_DIR = with_bios()
    for system in ("Nintendo - Super Nintendo Entertainment System",
                   "Nintendo - Nintendo 64", "Sega - Mega Drive - Genesis"):
        check(ra.bios_problem(system) is None,
              "%s needs no BIOS and is not asked for one" % ra.short_name(system))

    print("\nand the refusal names the file and where it goes")
    problem = ra.bios_problem("Sony - PlayStation")
    check(problem is not None, "PlayStation with no BIOS is refused")
    if problem:
        check("scph5500.bin" in problem and "scph5501.bin" in problem,
              "naming the files that would do, got %r" % problem[:90])
        check(" or " in problem,
              "as alternatives, because any one of them is enough")
        check(ra.SYSTEM_DIR in problem,
              "and saying which folder to put it in, whatever that folder is")
        check("games folder" in problem,
              "and where not to -- a BIOS in with the games is dropped from "
              "the playlist for looking like a game")

    print("\npreflight is what actually stops the launch")
    rom = tempfile.mkstemp(suffix=".cue")[1]
    core = tempfile.mkstemp(suffix=".so")[1]
    stopped = ra.preflight(core, rom, "Sony - PlayStation")
    check(stopped and "scph" in stopped,
          "a PlayStation game is refused with the reason, got %r"
          % (stopped or "")[:60])
    check(ra.preflight(core, rom, "Nintendo - Nintendo 64") is None,
          "an N64 game is not")
    check("missing" in (ra.preflight(core, "/gone.n64", "Nintendo - Nintendo 64")
                        or "").lower(),
          "and a ROM that is not there is still caught")
    os.unlink(rom)
    os.unlink(core)
finally:
    ra.SYSTEM_DIR = was

print("\nand that folder is RetroArch's own system directory")
check(ra.SYSTEM_DIR.endswith("retroarch/system"),
      "which is where bios-required.txt tells people to put them, got %s"
      % ra.SYSTEM_DIR)

print("\nthe one list is the .tsv, not a copy of it")
source = open(MAIN).read()
check("REQUIRED_BIOS" not in source,
      "the hand-written dict is gone -- it is what went eleven systems out "
      "of date without anybody noticing")
check('"bios.tsv"' in source, "and bios.tsv is read directly")
check('"systems.tsv"' in source,
      "with systems.tsv joining folder names to system names, rather than a "
      "second mapping written out here")

print("\nand a console that cannot play anything says so in the list")
check("bios_state(system)" in source.split("def list_systems")[1][:2200],
      "the console list asks before drawing a row, so the answer is on screen "
      "before a game is chosen rather than after")

print("\na console list shows consoles, not the first game on each")
# "CONSOLES" opened onto a Mario box for the NES and a Sonic box for the
# Genesis, which reads as a list of games. sync_games.py has been putting a
# picture of each machine in ~/.kodi/media/consoles all along, and kodi_menu.py
# has drawn the home rows with them all along; this screen was the one place
# that did not look.
listing = source.split("def list_systems")[1][:1600]
check("CONSOLE_ICONS" in listing,
      "the console's own picture is what the tile uses")
check(listing.index("CONSOLE_ICONS") < listing.index('cover.get("thumb"'),
      "and the game's box art is only the fallback, not the first choice")
check("fanart" in listing,
      "with the game's screenshot kept for the background, which is what made "
      "the old behaviour look right at a glance")
check("consoles" in ra.CONSOLE_ICONS,
      "and it is the directory sync_games.py writes to, got %r"
      % ra.CONSOLE_ICONS)

print("\nthe sofa can see all of it")
check("retrobox-ready" in source,
      "the readiness check is reachable from Settings -- it has always known "
      "this and always said it on a terminal, where nobody using a games "
      "console is looking")

print()
if fails:
    print("FAILED: %d" % len(fails))
    for line in fails:
        print("  " + line)
    sys.exit(1)
print("test_biosgate: all ok")
