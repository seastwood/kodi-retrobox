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
                    e.BTN_START: "start", e.BTN_SELECT: "select",
                    # Plenty of pads report the d-pad as four buttons, and the
                    # question is answered by moving along it.
                    e.BTN_DPAD_LEFT: "left", e.BTN_DPAD_RIGHT: "right",
                    e.BTN_DPAD_UP: "up", e.BTN_DPAD_DOWN: "down"}
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

print("an answer is chosen and then confirmed, not pressed")
# Which face button is "A" is not knowable here: a guest's pad arrives through
# the browser's standard mapping, and Xbox and Nintendo print A on different
# buttons. A pad whose letters are reversed would otherwise answer the opposite
# of what its owner meant, every time, silently.
ask = {"kind": "launch", "by": "/a", "question": "?", "detail": "", "choice": 0}
check(m.answer_event(claimed, Ev(e.BTN_SOUTH), ask) == "no",
      "confirming while NO is highlighted answers no")
ask["choice"] = 0
m.answer_event(claimed, Ev(e.BTN_DPAD_RIGHT), ask)
check(ask["choice"] == 1, "right moves the highlight to YES")
check(m.answer_event(claimed, Ev(e.BTN_SOUTH), ask) == "yes",
      "and confirming there answers yes")
m.answer_event(claimed, Ev(e.BTN_DPAD_LEFT), ask)
check(ask["choice"] == 0, "left moves it back")
ask["choice"] = 0
m.answer_event(claimed, Ev(e.ABS_HAT0X, value=1, type=e.EV_ABS), ask)
check(ask["choice"] == 1, "a d-pad hat moves it too")

print("the safe answer stays available whatever the pad calls its buttons")
ask["choice"] = 1
check(m.answer_event(claimed, Ev(e.BTN_EAST), ask) == "no",
      "back always dismisses, even with YES highlighted")

print("and only the pad that asked may answer")
ask = {"kind": "launch", "by": "/a", "question": "?", "detail": "", "choice": 1}
check(m.answer_event(loose, Ev(e.BTN_SOUTH), ask) is None,
      "somebody else pressing anything does not answer for them")
check(m.answer_event(claimed, Ev(e.BTN_SOUTH, value=0), ask) is None,
      "and a release is not an answer")

print("holding back leaves, even when other people have claimed")
# Previously impossible once anybody had claimed, which left somebody who had
# opened the wrong game with no way out but a keyboard.
holder = FakePad(path="/hold")
others = [FakePad(path="/other", slot=0)]
m.handle_event(holder, Ev(e.BTN_EAST), [holder] + others, 4)
check(holder.back_since is not None, "pressing back starts a hold")
m.handle_event(holder, Ev(e.BTN_EAST, value=0), [holder] + others, 4)
check(holder.back_since is None, "letting go ends it, so a tap is only a tap")

taken = FakePad(path="/taken", slot=2)
m.handle_event(taken, Ev(e.BTN_EAST), [taken], 4)
check(taken.slot is None, "and a tap still releases your own slot first")
check(taken.back_since is not None,
      "while the hold runs on, so one press can do both")

print("the hold is long enough not to happen by accident")
check(m.EXIT_HOLD_SECONDS >= 1.5,
      "%.1fs, which is not a brush against a button" % m.EXIT_HOLD_SECONDS)

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
