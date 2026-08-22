"""Hold-to-exit feedback.

The bar is driven through an injected sink here, so this tests the timing and
the responsiveness without needing a display. It also drives the real watcher
with a synthetic controller, which is what proves the evdev half works.
"""
import importlib.machinery
import importlib.util
import sys
import threading
import time

sys.argv = ["x"]
ldr = importlib.machinery.SourceFileLoader("rp", "/home/retro/.local/bin/ra_players.py")
m = importlib.util.module_from_spec(importlib.util.spec_from_loader("rp", ldr))
ldr.exec_module(m)
import evdev
from evdev import UInput, ecodes as e

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


print("-- how far along the bar should be --")
check(m.hold_fraction(0.0) is None, "nothing at the instant Start goes down")
check(m.hold_fraction(0.3) is None, "nothing during the grace period")
check(m.hold_fraction(0.5) is not None, "the bar appears once the hold is deliberate")
check(abs(m.hold_fraction(1.0) - 0.5) < 0.01,
      "half way at one second, got %r" % m.hold_fraction(1.0))
check(m.hold_fraction(2.0) == 1.0, "full exactly when RetroArch quits")
check(m.hold_fraction(5.0) == 1.0, "and never past full")
# A steady rate is what makes it read as a countdown rather than a glitch.
steps = [m.hold_fraction(t) for t in (0.5, 0.8, 1.1, 1.4, 1.7, 2.0)]
check(all(b > a for a, b in zip(steps, steps[1:])), "it only ever grows")


class FakeBar:
    def __init__(self):
        self.calls = []
    def show(self, fraction):
        self.calls.append(round(fraction, 2))
    def hide(self):
        self.calls.append("hide")
    def close(self):
        self.calls.append("close")


print("-- driven by a synthetic controller --")
caps = {e.EV_KEY: [e.BTN_SOUTH, e.BTN_EAST, e.BTN_START],
        e.EV_ABS: [(e.ABS_X, evdev.AbsInfo(0, -32768, 32767, 0, 0, 0)),
                   (e.ABS_Y, evdev.AbsInfo(0, -32768, 32767, 0, 0, 0))]}
try:
    pad = UInput(caps, name="Synthetic Test Pad", vendor=0x9999, product=0x9999)
except Exception as exc:
    print("  SKIP  cannot create a virtual pad: %s" % exc)
    print("\nFAILURES: %d" % len(fails))
    sys.exit(1 if fails else 0)
time.sleep(1.0)                       # let udev settle so input_devices() sees it

bar = FakeBar()
stop = threading.Event()
threading.Thread(target=m.watch_hold_to_exit, args=(stop, bar), daemon=True).start()
time.sleep(0.6)

print("   a short press, which must draw nothing...")
pad.write(e.EV_KEY, e.BTN_START, 1); pad.syn()
time.sleep(0.25)
pad.write(e.EV_KEY, e.BTN_START, 0); pad.syn()
time.sleep(0.4)
quiet = [c for c in bar.calls if c != "hide"] == []

print("   released half way, which must hide at once...")
bar.calls[:] = []
pad.write(e.EV_KEY, e.BTN_START, 1); pad.syn()
time.sleep(1.0)
drawn = len([c for c in bar.calls if c != "hide"])
pad.write(e.EV_KEY, e.BTN_START, 0); pad.syn()
time.sleep(0.15)                      # far less than SHOW_MSG's three seconds
hid_fast = bar.calls and bar.calls[-1] == "hide"

print("   held the whole way...")
bar.calls[:] = []
pad.write(e.EV_KEY, e.BTN_START, 1); pad.syn()
time.sleep(2.3)
full = max((c for c in bar.calls if c != "hide"), default=0)
pad.write(e.EV_KEY, e.BTN_START, 0); pad.syn()
time.sleep(0.3)

stop.set()
time.sleep(0.4)
pad.close()

check(quiet, "a short press drew nothing at all")
check(drawn > 8, "a one-second hold redrew the bar %d times (smooth, not stepped)" % drawn)
check(hid_fast, "letting go hid it immediately, got %r" % (bar.calls[-1:] or None))
check(full >= 0.99, "a full hold reached the end of the bar, got %r" % full)

print("\nFAILURES: %d" % len(fails))
sys.exit(1 if fails else 0)
