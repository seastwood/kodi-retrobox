"""Pads put back on their players after one drops out mid-game.

RetroArch numbers pads once at startup, then gives a pad that arrives the
LOWEST free slot (udev_find_vacant_pad). The picker writes which slot is which
player, so after a dropout the question is only: where did RetroArch put each
person's pad, and is it still the slot their player reads? These tests drive
the model of that with the scenarios that happen on a sofa.
"""
import importlib.machinery
import importlib.util
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.argv = ["x"]
loader = importlib.machinery.SourceFileLoader(
    "rp", os.path.join(REPO, "bin", "ra_players.py"))
m = importlib.util.module_from_spec(importlib.util.spec_from_loader("rp", loader))
loader.exec_module(m)

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


# What sysfs would say about each node. A Bluetooth pad that reconnects comes
# back on a new node with the same address; a wired one replugged into the
# same socket keeps its USB port.
IDENT = {
    "/dev/input/event3": ("Core (Plus) Wired Controller", "", "usb-1/input0"),
    "/dev/input/event4": ("Core (Plus) Wired Controller", "", "usb-2/input0"),
    "/dev/input/event19": ("8BitDo Micro gamepad", "e4:17:d8", "08:be:ac"),
    "/dev/input/event18": ("Xbox Series", "", "usb-9/input0"),
    "/dev/input/event30": ("8BitDo Micro gamepad", "e4:17:d8", "08:be:ac"),
    "/dev/input/event31": ("Core (Plus) Wired Controller", "", "usb-2/input0"),
    "/dev/input/event32": ("Stranger Pad", "", "usb-5/input0"),
    "/dev/input/event33": ("Core (Plus) Wired Controller", "", "usb-7/input0"),
}
m.sysfs_ident = lambda path: IDENT[path]

START = ["/dev/input/event3", "/dev/input/event4",
         "/dev/input/event19", "/dev/input/event18"]


def seats():
    """Everyone sat where the picker put them: player N on slot N-1."""
    return [{"slot": i, "kind": "pad", "index": i, "ident": IDENT[path]}
            for i, path in enumerate(START)]


def wrong(model):
    return sorted(seat["slot"] + 1 for seat in m.seats_misplaced(seats(), model))


print("-- nothing moved, nothing to do --")
model = m.SlotModel(START)
check(wrong(model) == [], "everyone on their own player")

print("-- one Bluetooth pad drops and comes back: same slot, nothing to do --")
model = m.SlotModel(START)
model.remove("/dev/input/event19")
model.add("/dev/input/event30")          # a new node, the same pad
check(model.slots[2] == "/dev/input/event30",
      "it takes the lowest free slot, which is its own, got %r" % model.slots)
check(wrong(model) == [], "so nobody is misplaced")

print("-- two drop and come back the other way round: both are swapped --")
model = m.SlotModel(START)
model.remove("/dev/input/event4")        # player 2's PowerA
model.remove("/dev/input/event19")       # player 3's 8BitDo
model.add("/dev/input/event30")          # the 8BitDo is back first...
model.add("/dev/input/event31")          # ...then the PowerA, same socket
check(wrong(model) == [2, 3], "players 2 and 3 are on each other's pads, got %r"
      % wrong(model))

print("-- a stranger arrives while a pad is away: the pad comes back elsewhere --")
model = m.SlotModel(START)
model.remove("/dev/input/event19")
model.add("/dev/input/event32")          # takes slot 3, player 3's
model.add("/dev/input/event30")          # player 3's pad lands in slot 5
check(model.slots[4] == "/dev/input/event30", "in a new slot, got %r" % model.slots)
check(wrong(model) == [3], "player 3 is misplaced, got %r" % wrong(model))

print("-- a pad away and not back yet is not misplaced, just absent --")
model = m.SlotModel(START)
model.remove("/dev/input/event18")
check(wrong(model) == [], "nothing to fix until it returns")

print("-- a change is a leave and an arrival, as in RetroArch --")
model = m.SlotModel(START)
model.remove("/dev/input/event3")        # player 1 away
model.change("/dev/input/event18")       # player 4's pad re-announces itself
check(model.slots[0] == "/dev/input/event18",
      "player 4's pad drops to the lowest free slot, got %r" % model.slots)
check(wrong(model) == [4], "and is on player 1's slot, got %r" % wrong(model))

print("-- identical pads are told apart by their USB port --")
found = m.match_seats(
    [IDENT["/dev/input/event3"], IDENT["/dev/input/event4"]],
    [(0, IDENT["/dev/input/event4"]), (1, IDENT["/dev/input/event3"])])
check(found == {0: 1, 1: 0}, "each twin found by port, got %r" % found)

print("-- a twin moved to a new socket is found only if nothing else fits --")
found = m.match_seats(
    [IDENT["/dev/input/event3"], IDENT["/dev/input/event4"]],
    [(0, IDENT["/dev/input/event3"]), (5, IDENT["/dev/input/event33"])])
check(found == {0: 0, 1: 5}, "the one twin left, on its new port, got %r" % found)
found = m.match_seats(
    [IDENT["/dev/input/event3"], IDENT["/dev/input/event4"]],
    [(5, IDENT["/dev/input/event33"]),
     (6, ("Core (Plus) Wired Controller", "", "usb-8/input0"))])
check(found == {}, "two twins both on new sockets: no guess, got %r" % found)

print("-- a Bluetooth pad is found by its address, whatever node --")
found = m.match_seats([IDENT["/dev/input/event19"]],
                      [(7, IDENT["/dev/input/event30"])])
check(found == {0: 7}, "got %r" % found)

print("-- relaunching seats everyone by who they are, not where they were --")


class Dev:
    def __init__(self, ident):
        self.name, self.uniq, self.phys = ident

    def close(self):
        pass


now = [("pad", 0, "/dev/input/event3"), ("pad", 1, "/dev/input/event31"),
       ("pad", 2, "/dev/input/event32"), ("pad", 3, "/dev/input/event18"),
       ("pad", 4, "/dev/input/event30")]
m.input_devices = lambda: [(kind, index, path, Dev(IDENT[path]))
                           for kind, index, path in now]
m.pad_controls = lambda dev: ({}, {})
m.guest_names = lambda: {}
pads = m.reseat_pads(seats())
where = {p.path: p.slot for p in pads}
check(where == {"/dev/input/event3": 0, "/dev/input/event31": 1,
                "/dev/input/event32": None, "/dev/input/event18": 3,
                "/dev/input/event30": 2},
      "each person back on their player, the stranger on none, got %r" % where)
seated = {p.slot: p.index for p in pads if p.slot is not None}
check(seated == {0: 0, 1: 1, 2: 4, 3: 3},
      "with the indices RetroArch now has them on, got %r" % seated)

print("-- the relaunch writes those indices, resumes the parked slot, keeps watching --")
import tempfile
m.OVERRIDE_DIR = tempfile.mkdtemp()
m.ADAPTER_FILES = os.path.join(m.OVERRIDE_DIR, "owned.json")
m.REMAP_DIR = os.path.join(m.OVERRIDE_DIR, "remaps")
got = {}


def fake_run(args, override, shader, repick=None, load_slot=None, seats=None):
    got.update(text=open(override).read(), slot=load_slot, seats=seats)
    return 0


m.run_retroarch = fake_run
r = m.Repick()
r.seats, r.board, r.slot, r.reseat = seats(), 4, 7, True
r.set()
code = m.reseat_once(["-L", "/c/snes9x_libretro.so", "/g/Bomber.sfc"], None, False, r)
text = got.get("text", "")
check(code == 0 and 'input_player3_joypad_index = "4"' in text
      and 'input_player1_joypad_index = "0"' in text,
      "player 3 follows their pad to its new index, got %r"
      % [l for l in text.splitlines() if "joypad_index" in l][:4])
check('input_player5_joypad_index = "%d"' % m.PARKED in text,
      "the stranger's slot is parked, not given to anybody")
check(got.get("slot") == 7, "the parked game is what comes back")
check(got.get("seats") and not r.reseat and not r.is_set(),
      "and the next run keeps watching, with the request cleared")

print()
print("FAILURES: %d" % len(fails))
sys.exit(1 if fails else 0)
