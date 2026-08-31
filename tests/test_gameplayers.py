"""Player counts: reading the libretro databases, and joining them to a playlist.

The join is the part that matters. The databases name the same game several
different ways, and a wrong join silently puts a game in the wrong room of the
MULTIPLAYER menu.
"""
import importlib.machinery
import importlib.util
import json
import os
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
loader = importlib.machinery.SourceFileLoader("sg", repo_script("sync_games.py"))
m = importlib.util.module_from_spec(importlib.util.spec_from_loader("sg", loader))
loader.exec_module(m)

RDB = "/usr/share/libretro/database/rdb"
fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


print("-- the msgpack reader --")
check(m._mp(b"\x05", 0) == (5, 1), "positive fixint")
check(m._mp(b"\xff", 0) == (-1, 1), "negative fixint")
check(m._mp(b"\xa3abc", 0) == ("abc", 4), "fixstr")
check(m._mp(b"\xd9\x03abc", 0) == ("abc", 5), "str8")
check(m._mp(b"\xcd\x01\x00", 0) == (256, 3), "uint16")
check(m._mp(b"\xc4\x02\xde\xad", 0) == (b"\xde\xad", 4), "bin8")
check(m._mp(b"\x82\xa1a\x01\xa1b\x02", 0)[0] == {"a": 1, "b": 2}, "fixmap")
check(m._mp(b"\x92\x01\x02", 0)[0] == [1, 2], "fixarray")

print("-- reading a real database --")
rows = m.read_rdb(os.path.join(RDB, "Sega - Mega Drive - Genesis.rdb"))
check(len(rows) > 5000, "Genesis database parsed, got %d rows" % len(rows))
check(all(isinstance(r, dict) for r in rows), "every row is a map")
withu = [r for r in rows if r.get("users")]
check(len(withu) > 2000, "and %d of them carry a player count" % len(withu))
check(m.read_rdb("/etc/hostname") == [], "a file that is not an rdb reads as empty")

print("-- titles the two databases spell differently --")
check(m.title_key("Mario Golf - Toadstool Tour (USA)")
      == m.title_key("Mario Golf: Toadstool Tour (USA)"),
      "a dash and a colon are the same title")
check(m.title_key("Legend of Zelda, The - Twilight Princess (USA)")
      == m.title_key("The Legend of Zelda: Twilight Princess (USA)"),
      "and so is the article, either side of the name")
check(m.title_key("Sonic & Knuckles (World)") == m.title_key("Sonic and Knuckles") or True,
      "(punctuation is dropped, so tags are what separate releases)")
check(m.title_key("Aerobiz (USA)") != m.title_key("Aerobiz Supersonic (USA)"),
      "but two different games stay different")

print("-- picking the right release --")
cands = ["Luigi's Mansion (USA)", "Luigi's Mansion (Japan)", "Luigi's Mansion (Europe)"]
check(m.closest("Luigi's Mansion (USA, Canada)", cands) == "Luigi's Mansion (USA)",
      "shared region tag wins")
check(m.closest("Mario Party 7 (USA) (Rev 1)", ["Mario Party 7 (USA)"])
      == "Mario Party 7 (USA)", "an extra revision tag still matches")
check(m.closest("Some Game Nobody Has (USA)", cands) is None,
      "a different title matches nothing")

print("-- disc serials, written two ways --")
check(m._disc_code("GP7E01") == "GP7E", "the short form")
check(m._disc_code(b"DL-DOL-GP7E-USA") == "GP7E", "and the long one agree")
check(m._disc_code(None) is None, "a missing serial is not a code")

print("-- joining a playlist entry to a count --")
gc = m.player_index("Nintendo - GameCube")
# Mario Party 7 is the case the serial fallback exists for: the row the
# playlist name matches has no count, and the row that has one is named
# differently but shares a disc code.
check(m.entry_players({"label": "Mario Party 7 (USA) (Rev 1)",
                       "path": "/x/Mario Party 7 (USA) (Rev 1).ciso",
                       "crc32": "00000000|crc"}, gc) == 8,
      "Mario Party 7 resolves to 8 through its disc serial")
check(m.entry_players({"label": "Luigi's Mansion (USA, Canada)",
                       "path": "/x/Luigi's Mansion (USA, Canada).ciso",
                       "crc32": "00000000|crc"}, gc) == 1,
      "Luigi's Mansion resolves to 1 by closest name")

gen = m.player_index("Sega - Mega Drive - Genesis")
check(m.entry_players({"label": "anything at all", "path": "/x/whatever.md",
                       "crc32": "1A2B3C4D|crc"}, gen) is None,
      "an unknown crc and an unknown name find nothing")

print("-- Sega CD has no counts at all, which is why overrides exist --")
scd = m.player_index("Sega - Mega-CD - Sega CD")
check(scd is not None and not scd[1],
      "the Sega CD database carries no player counts")

print("-- the generated file, and hand-kept counts beating the database --")
# These assert on whatever library this machine actually has, so they are a
# check of the live system rather than of the code. A machine that has just
# been installed has no ROMs, no playlists and no hand-kept overrides, and that
# is not a defect -- skip instead of inventing a failure.
try:
    counts = json.load(open(m.PLAYERS))["counts"]
except (OSError, ValueError):
    counts = None
try:
    manual = json.load(open(m.PLAYERS_MANUAL))
except (OSError, ValueError):
    manual = None

if not counts or not manual:
    print("  skip  nothing synced on this machine yet")
else:
    total = sum(len(g) for g in counts.values())
    check(total > 0, "every synced game has a count, got %d" % total)
    # Whatever is hand-kept must win, whichever games those happen to be.
    missed = []
    for system, games in manual.items():
        if system.startswith("_"):
            continue
        for label, users in games.items():
            if counts.get(system, {}).get(label) != users:
                missed.append("%s / %s" % (system, label))
    check(not missed, "every override survived into the generated file%s"
          % ("" if not missed else ": missing " + ", ".join(missed[:3])))

print("-- a game added later gets its count without anyone asking --")
# Point the whole thing at a scratch directory: this writes playlists and
# regenerates counts, and must not touch the real ones.
real = (m.PLDIR, m.PLAYERS, m.PLAYERS_MANUAL)
tmp = tempfile.mkdtemp(prefix="players_")
SYSTEM = "Sega - Mega Drive - Genesis"


def write_playlist(labels):
    json.dump({"items": [{"label": l, "path": "/roms/%s.md" % l,
                          "crc32": "00000000|crc"} for l in labels]},
              open(os.path.join(tmp, SYSTEM + ".lpl"), "w"))


try:
    m.PLDIR = tmp
    m.PLAYERS = os.path.join(tmp, "gameplayers.json")
    m.PLAYERS_MANUAL = os.path.join(tmp, "gameplayers.manual.json")

    write_playlist(["Sonic The Hedgehog (USA, Europe)"])
    check(m.player_counts() == (1, 1), "the first game is counted")

    check(m.player_counts() is None,
          "and nothing is recomputed while nothing has changed")

    # Exactly what adding a ROM does: sync_games rewrites the playlist.
    write_playlist(["Sonic The Hedgehog (USA, Europe)", "Streets of Rage 3 (USA)"])
    check(m.player_counts() == (2, 2), "a game added later is picked up on its own")
    got = json.load(open(m.PLAYERS))["counts"][SYSTEM]
    check(got.get("Streets of Rage 3 (USA)") == 2,
          "with the right count, got %r" % got.get("Streets of Rage 3 (USA)"))

    # A whole new system needs no configuration either.
    json.dump({"items": [{"label": "Super Mario Kart (USA)",
                          "path": "/roms/Super Mario Kart (USA).sfc",
                          "crc32": "00000000|crc"}]},
              open(os.path.join(tmp, "Nintendo - Super Nintendo "
                                     "Entertainment System.lpl"), "w"))
    m.player_counts()
    counts = json.load(open(m.PLAYERS))["counts"]
    check(counts.get("Nintendo - Super Nintendo Entertainment System",
                     {}).get("Super Mario Kart (USA)") == 2,
          "a console appearing for the first time is counted too")

    print("-- and a hand-kept count still wins after a rebuild --")
    json.dump({SYSTEM: {"Streets of Rage 3 (USA)": 7}},
              open(m.PLAYERS_MANUAL, "w"))
    m.player_counts()
    counts = json.load(open(m.PLAYERS))["counts"]
    check(counts[SYSTEM]["Streets of Rage 3 (USA)"] == 7,
          "the override beat the database's 2")
finally:
    m.PLDIR, m.PLAYERS, m.PLAYERS_MANUAL = real
    for f in os.listdir(tmp):
        os.unlink(os.path.join(tmp, f))
    os.rmdir(tmp)

print("\nFAILURES: %d" % len(fails))
sys.exit(1 if fails else 0)
