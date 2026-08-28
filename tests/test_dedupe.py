"""One game, one entry, when the same ROM is on disk twice.

A .sfc filed under nes/ is still a SNES game, so the database scan puts the
misfiled copy and the correctly filed one in the same playlist: same label,
same CRC, two paths. Both of them launch, so nothing fails and nothing
complains -- the game just appears twice on the television, which is how this
was noticed.
"""
import importlib.machinery
import importlib.util
import json
import os
import sys
import tempfile

# The repository this test lives in, rather than a path with a clone name in
# it. The README promises the clone can go anywhere and be called anything;
# hard-coding one machine's name for it broke every one of these on a fresh
# install, where it is called something else.
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
loader = importlib.machinery.SourceFileLoader(
    "sg", os.path.join(REPO, "bin", "sync_games.py"))
sg = importlib.util.module_from_spec(
    importlib.util.spec_from_loader("sg", loader))
loader.exec_module(sg)

fails = []
notes = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


def playlist(tmp, name, items):
    path = os.path.join(tmp, name + ".lpl")
    json.dump({"items": items}, open(path, "w"))
    return path


def rom(folder, stem):
    return os.path.join(sg.ROMS, folder, stem, stem + ".sfc")


def entry(folder, stem, crc="6A187C70"):
    return {"path": rom(folder, stem), "label": stem,
            "core_path": "/x/snes9x_libretro.so", "core_name": "snes9x",
            "crc32": crc + "|crc", "db_name": "s.lpl"}


def run(items, name="Nintendo - Super Nintendo Entertainment System"):
    tmp = tempfile.mkdtemp(prefix="dedupe-")
    path = playlist(tmp, name, items)
    was, sg.PLDIR = sg.PLDIR, tmp
    was_log, sg.log = sg.log, notes.append
    try:
        dropped = sg.dedupe_entries()
        return dropped, json.load(open(path))["items"]
    finally:
        sg.PLDIR, sg.log = was, was_log


print("the same ROM in two folders is listed once")
dropped, kept = run([
    entry("snes", "Super Godzilla (USA)"),
    entry("nes", "Super Godzilla (USA)"),        # the same CRC: the same ROM
    entry("snes", "Super Mario World", crc="AAAA1111"),
    entry("snes", "F-Zero", crc="BBBB2222"),
])
check(len(kept) == 3, "three entries left, not four")
paths = [i["path"] for i in kept]
check(rom("snes", "Super Godzilla (USA)") in paths,
      "the copy in the folder the system lives in is kept")
check(rom("nes", "Super Godzilla (USA)") not in paths,
      "the one in the wrong folder is dropped")
check(dropped and dropped[0].endswith("-1"), "and it says one went: %s" % dropped)
check(any("also on disk at" in line for line in notes),
      "the log says where the stray file is, since it is still there")

print("the folder the rest of the playlist lives in decides, not the order")
dropped, kept = run([
    entry("nes", "Super Godzilla (USA)"),      # first in the list, wrong folder
    entry("snes", "Super Godzilla (USA)"),
    entry("snes", "Super Mario World", crc="AAAA1111"),
])
check(rom("snes", "Super Godzilla (USA)") in [i["path"] for i in kept],
      "still keeps the snes copy when the nes one comes first")

print("different games are left alone")
dropped, kept = run([
    entry("snes", "Super Mario World", crc="AAAA1111"),
    entry("snes", "F-Zero", crc="BBBB2222"),
])
check(len(kept) == 2 and not dropped, "two different games stay two")

print("and so are two unidentified games that merely share a placeholder CRC")
dropped, kept = run([
    entry("snes", "Homebrew A", crc="00000000"),
    entry("snes", "Homebrew B", crc="00000000"),
])
check(len(kept) == 2 and not dropped,
      "the placeholder CRC says nothing, so the label decides")

print("two copies of an unidentified game are still one game")
dropped, kept = run([
    entry("snes", "Homebrew A", crc="00000000"),
    entry("nes", "Homebrew A", crc="00000000"),
])
check(len(kept) == 1, "same label, no CRC to go on, one entry left")

print(("FAILED: %d" % len(fails)) if fails else "test_dedupe: all ok")
sys.exit(1 if fails else 0)
