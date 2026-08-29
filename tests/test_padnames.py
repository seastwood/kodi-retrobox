"""Showing a guest's name on the picker without breaking what RetroArch reads.

evdev knows a device called "Fourth Player 1" and nothing else, so the picker
showed the socket rather than the person. fourth-player writes down who is on
which pad and this reads it -- but only for the screen: the device name is what
RetroArch matches a reserved controller on, and swapping that for a nickname
would quietly stop pads returning to the same player.
"""
import importlib.machinery
import importlib.util
import json
import os
import sys
import tempfile
import time

sys.argv = ["x"]
REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
loader = importlib.machinery.SourceFileLoader(
    "rp", os.path.join(REPO, "bin", "ra_players.py"))
m = importlib.util.module_from_spec(
    importlib.util.spec_from_loader("rp", loader))
loader.exec_module(m)

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


tmp = tempfile.mkdtemp(prefix="padnames-")
path = os.path.join(tmp, "pad-names.json")
m.GUEST_NAMES = path
m._guest_names = (None, {})

print("with no file at all, nothing is claimed")
check(m.guest_names() == {}, "an absent file is not an error")

print("names are read, and re-read when they change")
json.dump({"Fourth Player 1": "Dave"}, open(path, "w"))
check(m.guest_names() == {"Fourth Player 1": "Dave"}, "read")
time.sleep(0.01)
json.dump({"Fourth Player 1": "Dave", "Fourth Player 2": "Sam"},
          open(path, "w"))
check(m.guest_names().get("Fourth Player 2") == "Sam",
      "a guest joining while the picker is up is picked up")

print("rubbish in the file is ignored rather than thrown")
open(path, "w").write("{ not json")
m._guest_names = (None, {})
check(m.guest_names() == {}, "a half-written file leaves the picker working")
json.dump({"Fourth Player 1": None, "": "x", "Fourth Player 2": "Sam"},
          open(path, "w"))
m._guest_names = (None, {})
check(m.guest_names() == {"Fourth Player 2": "Sam"},
      "and entries with nothing in them are dropped")


class FakeDev:
    def __init__(self, name):
        self.name, self.path = name, "/dev/input/eventX"
    def capabilities(self, absinfo=False):
        import evdev
        return {evdev.ecodes.EV_KEY: [evdev.ecodes.BTN_SOUTH,
                                      evdev.ecodes.BTN_EAST]}
    def close(self):
        pass


print("the screen shows the person, the config keeps the device")
json.dump({"Fourth Player 1": "Dave"}, open(path, "w"))
m._guest_names = (None, {})
pad = m.Pad(0, "/dev/input/event1", FakeDev("Fourth Player 1"))
check(pad.display == "Dave", "the picker draws the name they gave")
check(pad.name == "Fourth Player 1",
      "and keeps the device name, which is what RetroArch matches on")

pad.slot = 0
override = m.write_override([pad], slots=2)
text = open(override).read()
os.unlink(override)
check('input_player1_reserved_device = "Fourth Player 1"' in text,
      "so the reservation names the device, not the nickname")
check("Dave" not in text, "the nickname never reaches RetroArch's config")

print("a pad nobody has claimed keeps its own name")
other = m.Pad(1, "/dev/input/event2", FakeDev("Fourth Player 3"))
check(other.display == "Fourth Player 3", "unclaimed pads read as themselves")

print(("FAILED: %d" % len(fails)) if fails else "test_padnames: all ok")
sys.exit(1 if fails else 0)
