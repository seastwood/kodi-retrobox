"""Adding games from disk without the database.

The risk is not missing a game, it is adding the wrong file: a disc game's
track data must not become an entry of its own, while a cartridge game really
is a bare .bin. Both go through the same core, so the decision has to come
from what is in the folder.
"""
import importlib.machinery
import importlib.util
import json
import os
import shutil
import sys
import tempfile

loader = importlib.machinery.SourceFileLoader("sg", "/home/retro/.local/bin/sync_games.py")
m = importlib.util.module_from_spec(importlib.util.spec_from_loader("sg", loader))
loader.exec_module(m)

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


tmp = tempfile.mkdtemp()
roms = os.path.join(tmp, "roms")
plists = os.path.join(tmp, "plists")
cores = os.path.join(tmp, "cores")
for d in (roms, plists, cores):
    os.makedirs(d)

m.ROMS, m.PLDIR, m.COREDIR = roms, plists, cores
m.CORES = {"Fake - Cube": "cubecore", "Fake - Disc": "disccore",
           "Fake - Cart": "cartcore", "Fake - Multi": "disccore"}
EXTS = {"cubecore": {"ciso", "iso", "m3u"},
        "disccore": {"cue", "bin", "iso", "m3u", "chd"},
        "cartcore": {"bin", "md", "gen"}}
m.core_extensions = lambda core: EXTS[core]
m.display_name = lambda core: core.upper()
for core in EXTS:
    open(os.path.join(cores, core + ".so"), "w").close()


def touch(*parts):
    path = os.path.join(roms, *parts)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").close()
    return path


def playlist(system, folder, items):
    """A playlist that already lists `items` from `folder`."""
    data = {"version": "1.5", "items": [
        {"path": os.path.join(roms, folder, i), "label": i.rsplit(".", 1)[0],
         "core_path": "x", "core_name": "x", "crc32": "0|crc",
         "db_name": system + ".lpl"} for i in items]}
    json.dump(data, open(os.path.join(plists, system + ".lpl"), "w"), indent=2)


def labels(system):
    data = json.load(open(os.path.join(plists, system + ".lpl")))
    return sorted(i["label"] for i in data["items"])


# A compressed-image system: one game listed, one dropped in afterwards.
touch("cube", "Already There.ciso")
touch("cube", "Mario Party 7 (USA) (Rev 1).ciso")
playlist("Fake - Cube", "cube", ["Already There.ciso"])

# A disc system: cue plus its track data, in a per-game folder.
touch("disc", "Some Game (USA)", "Some Game (USA).cue")
touch("disc", "Some Game (USA)", "Some Game (USA) (Track 1).bin")
touch("disc", "Some Game (USA)", "Some Game (USA) (Track 2).bin")
playlist("Fake - Disc", "disc", ["Listed Game.cue"])

# A cartridge system on the same kind of core: a bare .bin is the game.
touch("cart", "Sonic (USA).bin")
touch("cart", "Ristar (USA).md")
playlist("Fake - Cart", "cart", ["Listed Cart.bin"])

# Multi-disc: an m3u stands for the whole set.
touch("multi", "Big RPG", "Big RPG.m3u")
touch("multi", "Big RPG", "Big RPG (Disc 1).cue")
touch("multi", "Big RPG", "Big RPG (Disc 1).bin")
touch("multi", "Big RPG", "Big RPG (Disc 2).cue")
playlist("Fake - Multi", "multi", ["Listed Multi.m3u"])

# A BIOS dropped at the top of a disc system's folder: a bare .bin with no
# .cue beside it, which is exactly the shape of a cartridge game.
touch("disc", "us_scd1_9210.bin")

added = m.fill_gaps()
print("added: %s" % added)

print("-- a stray BIOS in a disc system's folder is not a game --")
check("us_scd1_9210" not in labels("Fake - Disc"),
      "the BIOS was not listed, got %r" % labels("Fake - Disc"))

print("-- a new compressed image is picked up --")
check("Mario Party 7 (USA) (Rev 1)" in labels("Fake - Cube"),
      "Mario Party 7 added, got %r" % labels("Fake - Cube"))
check(labels("Fake - Cube").count("Already There") == 1,
      "the existing entry was not duplicated")

print("-- a disc game adds the cue, never the tracks --")
got = labels("Fake - Disc")
check("Some Game (USA)" in got, "the cue was added, got %r" % got)
check(not any("Track" in g for g in got), "no track entries, got %r" % got)

print("-- but a bare cartridge dump is the game --")
got = labels("Fake - Cart")
check("Sonic (USA)" in got and "Ristar (USA)" in got,
      "both carts added, got %r" % got)

print("-- an m3u stands in for its discs --")
got = labels("Fake - Multi")
check("Big RPG" in got, "the m3u was added, got %r" % got)
check(not any("Disc" in g for g in got), "no per-disc entries, got %r" % got)

print("-- entries are shaped the way RetroArch writes them --")
data = json.load(open(os.path.join(plists, "Fake - Cube.lpl")))
entry = next(i for i in data["items"] if i["label"].startswith("Mario Party"))
for field in ("path", "label", "core_path", "core_name", "crc32", "db_name"):
    check(field in entry, "has %s" % field)
check(entry["db_name"] == "Fake - Cube.lpl", "db_name names the playlist")
check(entry["core_path"].endswith("cubecore.so"), "points at the right core")
check(os.path.exists(entry["path"]), "the path exists on disk")

print("-- running twice adds nothing the second time --")
again = m.fill_gaps()
check(not again, "second run is a no-op, got %r" % again)

print("-- a folder no playlist covers is reported, not silently dropped --")
os.makedirs(os.path.join(roms, "dreamcast"))
lines = []
m.log = lambda msg: lines.append(msg)
m.fill_gaps()
check(any("dreamcast" in l for l in lines),
      "said something about dreamcast/, got %r" % lines)

shutil.rmtree(tmp)
print()
print("-- multi-disc games are joined into one .m3u --")
touch("playstation", "Xenogears (USA)", "Xenogears (USA) (Disc 1).cue")
touch("playstation", "Xenogears (USA)", "Xenogears (USA) (Disc 2).cue")
touch("playstation", "Metal Gear Solid (USA)",
      "Metal Gear Solid (USA) (Disc 1) (Rev 1).cue")
made, incomplete, covered = m.disc_sets()
m3u = os.path.join(m.ROMS, "playstation", "Xenogears (USA)", "Xenogears (USA).m3u")
check(os.path.exists(m3u), "an .m3u was written for the complete set")
check(open(m3u).read().splitlines()
      == ["Xenogears (USA) (Disc 1).cue", "Xenogears (USA) (Disc 2).cue"],
      "listing both discs in order, got %r" % open(m3u).read().splitlines())
check(len(covered) == 2, "and both discs are marked as covered, got %d" % len(covered))
check(any("Metal Gear" in line for line in incomplete),
      "the one-disc game is reported as incomplete, got %r" % incomplete)
check(not any("Xenogears" in line for line in incomplete),
      "and the complete one is not")

print("-- and writing it again changes nothing --")
made2, _inc, _cov = m.disc_sets()
check(made2 == [], "a second run rewrites nothing, got %r" % made2)

print("-- a disc entry the .m3u replaces is dropped from the playlist --")
disc1 = os.path.join(m.ROMS, "playstation", "Xenogears (USA)",
                     "Xenogears (USA) (Disc 1).cue")
os.makedirs(m.PLDIR, exist_ok=True)
json.dump({"items": [{"label": "Xenogears (USA) (Disc 1)", "path": disc1,
                     "crc32": "00000000|crc"}]},
          open(os.path.join(m.PLDIR, "Sony - PlayStation.lpl"), "w"))
dropped = m.drop_entries(covered)
check(dropped == ["Xenogears (USA) (Disc 1)"],
      "the per-disc entry went, got %r" % dropped)
check(labels("Sony - PlayStation") == [],
      "leaving the playlist without it")

print("-- revisions are not mixed into one set --")
touch("playstation", "Parasite Eve (USA)", "Parasite Eve (USA) (Disc 1).cue")
touch("playstation", "Parasite Eve (USA)", "Parasite Eve (USA) (Disc 2) (Rev 1).cue")
_made, incomplete, _cov = m.disc_sets()
check(sum(1 for line in incomplete if "Parasite Eve" in line) == 2,
      "two differently tagged discs are two incomplete sets, not one game")


print("FAILURES: %d" % len(fails))
sys.exit(1 if fails else 0)
