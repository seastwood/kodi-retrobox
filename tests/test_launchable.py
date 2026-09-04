"""Which files in a ROM folder become playlist entries.

A single two-disc game put an .m3u into the flat GameCube folder, and from then
on every other game in that folder was treated as a disc that .m3u covered.
Nothing new could ever be added again: a game copied in was scanned, matched by
nothing, and silently never appeared -- and re-running the sync could not help,
because the question was never about that game.
"""
import importlib.machinery
import importlib.util
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.dirname(HERE)

loader = importlib.machinery.SourceFileLoader(
    "sync_games", os.path.join(ROOT, "bin", "sync_games.py"))
spec = importlib.util.spec_from_loader("sync_games", loader)
sync = importlib.util.module_from_spec(spec)
loader.exec_module(sync)

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


def names(entries):
    return sorted(os.path.basename(path) for _stem, path in entries)


DISC = {"ciso", "iso", "m3u"}

print("one multi-disc game does not silence the folder it sits in")
tmp = tempfile.mkdtemp(prefix="launchable-")
files = [
    "Eternal Darkness (Europe).ciso",
    "Luigi Mansion (USA).ciso",
    "Resident Evil 4 (Disc 1).ciso",
    "Resident Evil 4 (Disc 2).ciso",
    "Resident Evil 4.m3u",
]
for name in files:
    open(os.path.join(tmp, name), "w").close()
with open(os.path.join(tmp, "Resident Evil 4.m3u"), "w") as fh:
    fh.write("Resident Evil 4 (Disc 1).ciso\nResident Evil 4 (Disc 2).ciso\n")

got = names(sync.launchable(tmp, files, DISC))
check("Eternal Darkness (Europe).ciso" in got,
      "a game added beside a multi-disc set is still offered")
check("Luigi Mansion (USA).ciso" in got,
      "and so is every other game already in the folder")
check("Resident Evil 4.m3u" in got,
      "the multi-disc game appears once, as its m3u")
check("Resident Evil 4 (Disc 1).ciso" not in got
      and "Resident Evil 4 (Disc 2).ciso" not in got,
      "and its own discs do not appear separately: %s" % got)

print("\nan m3u covers exactly the discs it lists, no more")
second = tempfile.mkdtemp(prefix="launchable-two-")
solo = ["Alone (USA).ciso", "Pair (Disc 1).ciso", "Pair (Disc 2).ciso", "Pair.m3u"]
for name in solo:
    open(os.path.join(second, name), "w").close()
with open(os.path.join(second, "Pair.m3u"), "w") as fh:
    fh.write("# a comment, and a blank line\n\nPair (Disc 1).ciso\nPair (Disc 2).ciso\n")
got = names(sync.launchable(second, solo, DISC))
check("Alone (USA).ciso" in got, "an unrelated game beside an m3u survives")
check("Pair (Disc 1).ciso" not in got, "the discs it names are covered by it")
check(sync.launchable(second, ["Nothing.txt"], DISC) == [],
      "a file no core accepts is still ignored")

print("\nan m3u with nothing in it still speaks for its own discs")
# One written by hand may hold relative paths, or be empty. Reading it is the
# better answer where it works, but the name is what makes the set a set.
blank = tempfile.mkdtemp(prefix="launchable-blank-")
empty = ["Big RPG.m3u", "Big RPG (Disc 1).ciso", "Big RPG (Disc 2).ciso",
         "Unrelated (USA).ciso"]
for name in empty:
    open(os.path.join(blank, name), "w").close()
got = names(sync.launchable(blank, empty, DISC))
check("Big RPG.m3u" in got, "the set appears once")
check(not any("Disc" in g for g in got),
      "its discs are covered by the name alone: %s" % got)
check("Unrelated (USA).ciso" in got,
      "and a game that is not part of the set is still offered")

print("\na cue is still the entry point for its own tracks")
cue = tempfile.mkdtemp(prefix="launchable-cue-")
tracks = ["Game (USA).cue", "Game (USA).bin"]
for name in tracks:
    open(os.path.join(cue, name), "w").close()
got = names(sync.launchable(cue, tracks, {"cue", "bin"}))
check(got == ["Game (USA).cue"], "the cue, not the bin beside it: %s" % got)

print("\nFAILURES: %d" % len(fails))
sys.exit(1 if fails else 0)
