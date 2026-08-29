"""Who may start the game, and what gets asked before it starts.

Starting used to need somebody -- anybody -- to have claimed a slot, so a
player who had not claimed could launch the moment another player did, and a
player who let go of their slot by accident could have the game started
without them. Both of those happened.
"""
import importlib.machinery
import importlib.util
import os
import sys

sys.argv = ["x"]
REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
loader = importlib.machinery.SourceFileLoader(
    "rp", os.path.join(REPO, "bin", "ra_players.py"))
m = importlib.util.module_from_spec(
    importlib.util.spec_from_loader("rp", loader))
loader.exec_module(m)

import evdev
from evdev import ecodes as e

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


class Ev:
    def __init__(self, code, value=1, type=e.EV_KEY):
        self.type, self.code, self.value = type, code, value


class FakePad:
    """Just the attributes handle_event and answer_event touch."""

    def __init__(self, path="/dev/input/eventX", kind="pad", slot=None):
        self.path, self.kind, self.slot = path, kind, slot
        self.cursor, self.axis_latch, self.seen = 0, 0, False
        self.last_press = None
        self.name = "Test Pad"
        self.btn = {e.BTN_SOUTH: "confirm", e.BTN_EAST: "back",
                    e.BTN_START: "start", e.BTN_SELECT: "select"}
        self.labels = {"confirm": "A", "back": "B", "start": "START",
                       "select": "SELECT"}


print("starting the game needs your own claim, not somebody else's")
claimed = FakePad(path="/a", slot=0)
loose = FakePad(path="/b")
pads = [claimed, loose]
act, said = m.handle_event(loose, Ev(e.BTN_START), pads, 4)
check(act != "launch", "a pad with no slot cannot start it")
check(said and "CLAIM" in said.upper(),
      "and is told what to do instead: %r" % said)
act, said = m.handle_event(claimed, Ev(e.BTN_START), pads, 4)
check(act == "launch", "a pad holding a slot can")

print("pressing anything marks a pad as one somebody is holding")
fresh = FakePad(path="/c")
check(not fresh.seen, "an untouched pad is not counted")
m.handle_event(fresh, Ev(e.BTN_SELECT), [fresh], 4)
check(fresh.seen, "one that has been pressed is")

print("only pads somebody is using count as not ready")
idle = FakePad(path="/idle")           # a guest slot nobody is holding
using = FakePad(path="/using"); using.seen = True
done = FakePad(path="/done", slot=1); done.seen = True
waiting = m.unready([idle, using, done])
check(waiting == [using],
      "the idle virtual pad is ignored, the held one is not: %s"
      % [q.path for q in waiting])
check(m.unready([idle, done]) == [],
      "with nobody left holding an unclaimed pad, nothing is asked")

print("select opens the button tester")
act, _ = m.handle_event(claimed, Ev(e.BTN_SELECT), pads, 4)
check(act == "test", "select is what opens it")

print("only the pad that asked the question may answer it")
ask = {"kind": "launch", "by": "/a", "question": "?", "detail": ""}
check(m.answer_event(claimed, Ev(e.BTN_SOUTH), ask) == "yes",
      "the asker confirms with the claim button")
check(m.answer_event(claimed, Ev(e.BTN_EAST), ask) == "no",
      "and refuses with the back button")
check(m.answer_event(loose, Ev(e.BTN_SOUTH), ask) is None,
      "somebody else pressing A does not answer for them")
check(m.answer_event(claimed, Ev(e.BTN_SOUTH, value=0), ask) is None,
      "and a release is not an answer")

print("a keyboard is held to the same rule")
kbd = FakePad(path="/kbd", kind="kbd")
act, said = m.handle_event(kbd, Ev(sorted(m.KBD_START)[0]), [kbd], 4)
check(act != "launch" and said, "a keyboard with no slot cannot start it either")
kbd.slot = 0
act, _ = m.handle_event(kbd, Ev(sorted(m.KBD_START)[0]), [kbd], 4)
check(act == "launch", "and can once it has claimed")

print("directions are named rather than treated as buttons")
way = m.axis_direction(claimed, Ev(e.ABS_HAT0X, value=-1, type=e.EV_ABS))
check(way == "d-pad left", "a hat reads as the d-pad: %r" % way)
way = m.axis_direction(claimed, Ev(e.ABS_Y, value=-30000, type=e.EV_ABS))
check(way == "stick up", "a stick reads as the stick: %r" % way)
check(m.axis_direction(claimed, Ev(e.ABS_X, value=0, type=e.EV_ABS)) is None,
      "and a centred stick is not a press")

print(("FAILED: %d" % len(fails)) if fails else "test_ready: all ok")
sys.exit(1 if fails else 0)
