"""A claimed slot belongs to the controller that claimed it.

Before this, every cursor could sit on a slot somebody else had already taken.
Confirm there did nothing but print "SLOT TAKEN" -- a dead end the board could
simply not have offered -- and two people could sit pointing at the same slot
with no idea which of them had it.
"""
import importlib.machinery
import importlib.util
import os
import sys

sys.argv = ["x"]
REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
loader = importlib.machinery.SourceFileLoader(
    "rp", os.path.join(REPO, "bin", "ra_players.py"))
rp = importlib.util.module_from_spec(
    importlib.util.spec_from_loader("rp", loader))
loader.exec_module(rp)

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


class P:
    def __init__(self, cursor=0, slot=None, kind="pad"):
        self.cursor, self.slot, self.kind = cursor, slot, kind

    def __repr__(self):
        return "P(cursor=%r, slot=%r)" % (self.cursor, self.slot)


SLOTS = 4

print("a cursor steps over a slot somebody already has")
a, b = P(cursor=1, slot=1), P(cursor=0)
pads = [a, b]
rp.step_cursor(b, pads, SLOTS, 1)
check(b.cursor == 2, "it skipped past slot 1 to slot 2: %r" % b.cursor)

print("and over several in a row")
a, b, c = P(cursor=1, slot=1), P(cursor=2, slot=2), P(cursor=0)
pads = [a, b, c]
rp.step_cursor(c, pads, SLOTS, 1)
check(c.cursor == 3, "past both to slot 3: %r" % c.cursor)

print("it will not walk off the end to find one")
a, b = P(cursor=3, slot=3), P(cursor=2)
pads = [a, b]
rp.step_cursor(b, pads, SLOTS, 1)
check(b.cursor == 2, "nothing free that way, so it stays: %r" % b.cursor)

print("its own slot is not an obstacle to itself")
a = P(cursor=0, slot=0)
rp.step_cursor(a, [a], SLOTS, 1)
check(a.cursor == 1, "it can still move: %r" % a.cursor)

print("claiming pushes anybody still pointing at that slot off it")
a, b = P(cursor=2), P(cursor=2)
pads = [a, b]
check(rp.claim(a, pads, SLOTS) is None, "the first one takes it")
check(a.slot == 2, "and holds slot 2")
check(b.cursor != 2, "the other is moved off: %r" % b.cursor)
check(b.slot is None, "without being given a slot it did not ask for")

print("and it is moved somewhere free, not onto another taken slot")
a, b, c = P(cursor=1, slot=1), P(cursor=2), P(cursor=2)
pads = [a, b, c]
rp.claim(b, pads, SLOTS)
check(c.cursor not in (1, 2), "not onto slot 1 or 2: %r" % c.cursor)
check(c.cursor in (0, 3), "one of the free ones: %r" % c.cursor)

print("two pushed off the same slot do not land on each other")
a, b, c = P(cursor=1), P(cursor=1), P(cursor=1)
pads = [a, b, c]
rp.claim(a, pads, SLOTS)
check(b.cursor != 1 and c.cursor != 1, "both moved off slot 1")

print("claiming a slot somebody has is still refused")
a, b = P(cursor=0, slot=0), P(cursor=0)
check(rp.claim(b, [a, b], SLOTS) == "SLOT TAKEN",
      "the message is unchanged for anyone who gets there another way")
check(b.slot is None, "and it is not given away")

print("releasing puts the slot back in play")
a, b = P(cursor=1, slot=1), P(cursor=0)
pads = [a, b]
a.cursor, a.slot = a.slot, None            # what the back button does
rp.step_cursor(b, pads, SLOTS, 1)
check(b.cursor == 1, "the freed slot can be moved onto again: %r" % b.cursor)

print()
if fails:
    print("FAILURES: %d" % len(fails))
    sys.exit(1)
print("test_exclusive: all ok")
