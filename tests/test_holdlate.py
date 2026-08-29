"""A controller that turns up after the game started can still close it.

Holding Start to quit is watched here rather than by RetroArch, so the pad only
has to be in the watcher's list. It was listed once, at launch -- and Sunshine
creates its virtual pad when a Moonlight client connects, which is after that.
So somebody joining a game already in progress could not close it, which is the
first thing they are likely to want.

Real uinput devices, because the question is what the enumeration sees.
"""
import importlib.machinery
import importlib.util
import os
import sys
import time

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


try:
    from evdev import UInput, AbsInfo, ecodes as e
except ImportError:
    print("SKIPPED: evdev is not installed")
    sys.exit(0)

CAPS = {
    e.EV_KEY: [e.BTN_SOUTH, e.BTN_EAST, e.BTN_NORTH, e.BTN_WEST,
               e.BTN_TL, e.BTN_TR, e.BTN_SELECT, e.BTN_START, e.BTN_MODE],
    e.EV_ABS: [(e.ABS_X, AbsInfo(0, -32768, 32767, 16, 128, 0)),
               (e.ABS_Y, AbsInfo(0, -32768, 32767, 16, 128, 0))],
}

first = second = None
try:
    try:
        first = UInput(CAPS, name="Holdtest Pad One", vendor=0x1234, product=0x5678)
    except Exception as exc:
        print("SKIPPED: could not open uinput (%s)" % exc)
        sys.exit(0)
    time.sleep(0.4)

    print("the pads present at the start are watched")
    pads, gone = rp.hold_pads([])
    names = [d.name for d, _ in pads]
    check("Holdtest Pad One" in names, "the one that was there is picked up")
    check(not gone, "and nothing has left yet")
    watched = {d.path for d, _ in pads}
    check(all(s for _, s in pads), "each has a Start to watch for")

    print("a pad that turns up later is picked up on the next look")
    second = UInput(CAPS, name="Holdtest Pad Two", vendor=0x1234, product=0x5679)
    time.sleep(0.4)
    pads2, gone = rp.hold_pads(pads)
    names2 = [d.name for d, _ in pads2]
    check("Holdtest Pad Two" in names2,
          "the late arrival is now watched: %s" % names2)
    check("Holdtest Pad One" in names2, "and the first one is still there")
    check(not gone, "nothing reported as leaving")

    print("and the handle already being read is kept, not reopened")
    before = {d.path: id(d) for d, _ in pads}
    kept = [id(d) for d, _ in pads2 if d.path in before]
    check(any(i in before.values() for i in kept),
          "the original device object survives the rescan")

    print("a pad that goes away is noticed and dropped")
    second.close()
    time.sleep(0.5)
    pads3, gone = rp.hold_pads(pads2)
    check(gone, "the rescan says something left")
    check("Holdtest Pad Two" not in [d.name for d, _ in pads3],
          "and it is no longer watched")
finally:
    for dev in (first, second):
        try:
            dev.close()
        except Exception:
            pass

print(("FAILED: %d" % len(fails)) if fails else "test_holdlate: all ok")
sys.exit(1 if fails else 0)
