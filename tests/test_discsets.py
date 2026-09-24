"""Multi-disc games, and the complaint about the ones that are not all here.

A four-disc PlayStation game is distributed as four archives, so unpacking it
leaves four folders with one disc in each. The grouping used to happen inside
each directory of the walk, which meant every one of those folders held a
game of one disc -- so no .m3u was ever written for the set, and the
television said

    Incomplete game -- The Legend of Dragoon is missing a disc

every ten minutes, about a game with all four of its discs on the disk. Both
halves of that are tested here: the set has to join up across folders, and a
complaint has to be worth making.
"""
import importlib.machinery
import importlib.util
import json
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
loader = importlib.machinery.SourceFileLoader(
    "sg", os.path.join(REPO, "bin", "sync_games.py"))
sg = importlib.util.module_from_spec(
    importlib.util.spec_from_loader("sg", loader))
loader.exec_module(sg)

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


def disc(root, *parts):
    """One disc image, at whatever depth the parts describe."""
    path = os.path.join(root, *parts)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").write(b"\0" * 64)
    return path


def run(build):
    """Build a ROM tree with `build`, then group its discs."""
    tmp = tempfile.mkdtemp(prefix="discs-")
    roms = os.path.join(tmp, "emulation")
    os.makedirs(os.path.join(roms, "playstation"))
    build(os.path.join(roms, "playstation"))
    was, sg.ROMS = sg.ROMS, roms
    try:
        made, missing, covered = sg.disc_sets()
    finally:
        sg.ROMS = was
    return tmp, roms, made, missing, covered


NAME = "Legend of Dragoon, The (USA, Canada)"

print("four discs, one folder each, is one game")


def four_folders(ps):
    for n in (1, 2, 3, 4):
        stem = "%s (Disc %d)" % (NAME, n)
        disc(ps, stem, stem + ".cue")
        disc(ps, stem, stem + ".bin")


tmp, roms, made, missing, covered = run(four_folders)
check(not missing, "nothing is reported missing, got %s" % missing)
check(len(made) == 1 and "4 discs" in made[0],
      "one four-disc set was joined, got %s" % made)
m3u = os.path.join(roms, "playstation", NAME + ".m3u")
check(os.path.exists(m3u),
      "and the .m3u sits at the folder that holds all four, not inside one "
      "of them")
if os.path.exists(m3u):
    listed = [l for l in open(m3u).read().splitlines() if l]
    check(len(listed) == 4, "it names four discs, got %s" % listed)
    check(all(not os.path.isabs(l) for l in listed),
          "by relative path, which is what RetroArch resolves against the "
          "file's own folder, got %s" % listed)
    check(all(os.path.exists(os.path.join(os.path.dirname(m3u), l))
              for l in listed),
          "and every one of them resolves to a disc that is there")
    check(listed == sorted(listed, key=lambda l: l),
          "in disc order, got %s" % listed)
check(len(covered) == 4,
      "all four discs are covered, so they stop being games of their own, "
      "got %d" % len(covered))
shutil.rmtree(tmp, ignore_errors=True)

print("\nrunning it again changes nothing")
tmp, roms, made, missing, covered = run(four_folders)
was, sg.ROMS = sg.ROMS, roms
try:
    made2, missing2, covered2 = sg.disc_sets()
finally:
    sg.ROMS = was
check(made2 == [], "the second pass writes nothing, got %s" % made2)
check(covered2 == covered, "and covers the same discs")
shutil.rmtree(tmp, ignore_errors=True)

print("\ndiscs sitting side by side still work")


def flat(ps):
    for n in (1, 2):
        stem = "Metal Gear Solid (USA) (Disc %d) (Rev 1)" % n
        disc(ps, stem + ".chd")


tmp, roms, made, missing, covered = run(flat)
check(not missing, "nothing missing, got %s" % missing)
check(os.path.exists(os.path.join(roms, "playstation",
                                  "Metal Gear Solid (USA).m3u")),
      "the .m3u is beside them, where it always was")
shutil.rmtree(tmp, ignore_errors=True)

print("\na set that really is short of a disc still says so, once")


def only_one(ps):
    stem = "Xenogears (USA) (Disc 1)"
    disc(ps, stem, stem + ".cue")


tmp, roms, made, missing, covered = run(only_one)
check(len(missing) == 1, "one complaint, got %s" % missing)
check("Xenogears" in (missing[0] if missing else ""),
      "about the right game, got %s" % missing)
check(not made, "and no .m3u was written for it")
shutil.rmtree(tmp, ignore_errors=True)

print("\ntwo rips of the same disc do not become a set")


def twice(ps):
    for where in ("redump", "other"):
        stem = "Xenogears (USA) (Disc 1)"
        disc(ps, where, stem + ".cue")


tmp, roms, made, missing, covered = run(twice)
check(not made,
      "the same disc found twice is not two discs of a game, got %s" % made)
shutil.rmtree(tmp, ignore_errors=True)

print("\nthe discs an .m3u stands for do not come back as games")
# The half of this that reached the television. disc_sets wrote the .m3u and
# drop_entries took the four discs out of the playlist -- and then fill_gaps
# walked the folders, found no .m3u in any of them, because it is one level
# up, and put all four straight back. Five Legend of Dragoons, four of which
# start a game that cannot be finished.
tmp, roms, made, missing, covered = run(four_folders)
ps = os.path.join(roms, "playstation")
loose = []
for dirpath, _dirs, files in os.walk(ps):
    loose += [path for _stem, path in
              sg.launchable(dirpath, files, {"cue", "bin", "m3u"}, True,
                            covered)]
names = sorted(os.path.basename(p) for p in loose)
check(names == [NAME + ".m3u"],
      "only the .m3u is offered as a game, got %s" % names)

# And without being told, it would still put them back -- which is what makes
# passing `covered` load-bearing rather than tidiness.
blind = []
for dirpath, _dirs, files in os.walk(ps):
    blind += [path for _stem, path in
              sg.launchable(dirpath, files, {"cue", "bin", "m3u"}, True)]
check(len(blind) > len(loose),
      "the check is doing something: without it %d files are offered, with "
      "it %d" % (len(blind), len(loose)))

# A game that is genuinely on its own in the same system folder is untouched.
disc(ps, "Tekken 3 (USA)", "Tekken 3 (USA).cue")
alone = []
for dirpath, _dirs, files in os.walk(ps):
    alone += [os.path.basename(path) for _stem, path in
              sg.launchable(dirpath, files, {"cue", "bin", "m3u"}, True,
                            covered)]
check("Tekken 3 (USA).cue" in alone,
      "a game that is not part of any set is still found, got %s"
      % sorted(alone))
shutil.rmtree(tmp, ignore_errors=True)

print("\nand the sync drops them after adding, not before")
main_src = open(os.path.join(REPO, "bin", "sync_games.py")).read()
body = main_src.split("def main():")[1]
check(body.index("fill_gaps(") < body.index("drop_entries("),
      "RetroArch's own scanner lists the discs as well as the .m3u, so "
      "dropping them before the scan only means being handed them back")
check("fill_gaps(covered)" in body,
      "and fill_gaps is told what an .m3u already stands for")

print("\nthe complaint is only made when it is news")
tmp = tempfile.mkdtemp(prefix="discs-said-")
said = []
was_tell, sg.tell_kodi = sg.tell_kodi, lambda *a, **k: said.append(a)
was_file, sg.COMPLAINED = sg.COMPLAINED, os.path.join(tmp, "discs.json")
try:
    first = sg.told_about_discs(["Xenogears (USA): only disc 1 is here"])
    check(first and len(said) == 1, "the first time, it goes on the screen")
    check(bool(said) and "Xenogears" in said[0][1],
          "naming the game, got %r" % (said[0] if said else None,))
    again = sg.told_about_discs(["Xenogears (USA): only disc 1 is here"])
    check(not again and len(said) == 1,
          "the ten-minute timer running again says nothing, got %d "
          "notifications" % len(said))
    more = sg.told_about_discs(["Xenogears (USA): only disc 1 is here",
                                "Riven (USA): only disc 3 is here"])
    check(more and len(said) == 2, "a game that has newly gone short does")
    check(len(said) > 1 and "Riven" in said[-1][1],
          "and it is the new one that is named, got %r"
          % (said[-1] if said else None,))
    fixed = sg.told_about_discs([])
    check(not fixed and len(said) == 2,
          "and putting the discs back is not something to interrupt anybody "
          "about, got %d notifications" % len(said))
    kept = json.load(open(sg.COMPLAINED)).get("incomplete")
    check(kept == [], "though it is remembered, so the next one is news again")
finally:
    sg.tell_kodi, sg.COMPLAINED = was_tell, was_file
    shutil.rmtree(tmp, ignore_errors=True)

print()
if fails:
    print("FAILED: %d" % len(fails))
    for line in fails:
        print("  " + line)
    sys.exit(1)
print("test_discsets: all ok")
