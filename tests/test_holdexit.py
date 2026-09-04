"""Hold-to-exit feedback.

The bar is driven through an injected sink here, so this tests the timing and
the responsiveness without needing a display. It also drives the real watcher
with a synthetic controller, which is what proves the evdev half works.
"""
import os
import importlib.machinery
import importlib.util
import sys
import threading
import time

def repo_script(name):
    """The copy in this checkout, falling back to the installed one.

    These tests used to load ~/.local/bin/<name> outright -- the deployed copy.
    On the machine this was written on those are the same file, because the
    installer symlinks them; on a fresh clone they are not, so the suite
    quietly judged whatever happened to be installed and passed or failed on
    code that was not in front of it. A clone's tests should test the clone.
    """
    here = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))),
                        "bin", name)
    return here if os.path.exists(here) else os.path.expanduser("~/.local/bin/" + name)


sys.argv = ["x"]
ldr = importlib.machinery.SourceFileLoader("rp", repo_script("ra_players.py"))
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
        self.captions = []
    def show(self, fraction, caption=""):
        # The caption is recorded too: there are two holds now, and a bar that
        # promises to exit while it is changing players would be a lie.
        self.calls.append(round(fraction, 2))
        self.captions.append(caption)
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

print("\n-- select and B, which is the other way out --")
# In addition to Start, never instead of it. Reported as wanting a second
# gesture for a pad held differently, or a game that wants Start for itself.
#
# "B" is the button *printed* B, which pad_controls answers per pad: on a
# Nintendo layout that is input_b_btn (the bottom one) and on everything else
# it is input_a_btn (the right one). This synthetic pad has no profile, so it
# takes the fallback, where BTN_EAST is back -- the same button an Xbox pad
# prints B on.
# Axes as well as buttons: a device with no axes is not a gamepad as far as
# input_devices() is concerned, and a pad that is never classified as one is a
# pad this watcher never opens -- which made every check below pass by
# watching nothing at all.
combo_caps = {e.EV_KEY: [e.BTN_SOUTH, e.BTN_EAST, e.BTN_START, e.BTN_SELECT],
              e.EV_ABS: [(e.ABS_X, evdev.AbsInfo(0, -32768, 32767, 0, 0, 0)),
                         (e.ABS_Y, evdev.AbsInfo(0, -32768, 32767, 0, 0, 0))]}
try:
    pad2 = UInput(combo_caps, name="Synthetic Combo Pad",
                  vendor=0x9998, product=0x9998)
except Exception as exc:
    print("  SKIP  cannot create a virtual pad: %s" % exc)
    pad2 = None

if pad2 is not None:
    time.sleep(1.0)
    quits = []
    real_quit = m.send_quit
    m.send_quit = lambda: (quits.append(1), True)[1]
    bar2 = FakeBar()
    stop2 = threading.Event()
    threading.Thread(target=m.watch_hold_to_exit, args=(stop2, bar2),
                     daemon=True).start()
    time.sleep(0.6)

    print("   B on its own, which must do nothing...")
    pad2.write(e.EV_KEY, e.BTN_EAST, 1); pad2.syn()
    time.sleep(1.2)
    b_alone = [c for c in bar2.calls if c != "hide"] == []
    pad2.write(e.EV_KEY, e.BTN_EAST, 0); pad2.syn()
    time.sleep(0.3)

    print("   select and B together, held the whole way...")
    bar2.calls[:] = []
    pad2.write(e.EV_KEY, e.BTN_SELECT, 1); pad2.syn()
    time.sleep(0.1)
    pad2.write(e.EV_KEY, e.BTN_EAST, 1); pad2.syn()
    time.sleep(2.4)
    combo_full = max((c for c in bar2.calls if c != "hide"), default=0)
    combo_caption = bar2.captions[-1] if bar2.captions else ""
    quit_asked = len(quits)
    pad2.write(e.EV_KEY, e.BTN_EAST, 0); pad2.syn()
    pad2.write(e.EV_KEY, e.BTN_SELECT, 0); pad2.syn()
    time.sleep(0.3)

    print("   one of the two let go half way...")
    bar2.calls[:] = []
    pad2.write(e.EV_KEY, e.BTN_SELECT, 1); pad2.syn()
    pad2.write(e.EV_KEY, e.BTN_EAST, 1); pad2.syn()
    time.sleep(1.0)
    pad2.write(e.EV_KEY, e.BTN_EAST, 0); pad2.syn()
    time.sleep(0.25)
    let_go = bar2.calls and bar2.calls[-1] == "hide"
    quits_after = len(quits)
    time.sleep(1.6)                   # long enough to have quit, had it counted
    no_late_quit = len(quits) == quits_after
    pad2.write(e.EV_KEY, e.BTN_SELECT, 0); pad2.syn()

    stop2.set()
    time.sleep(0.4)
    pad2.close()
    m.send_quit = real_quit

    check(b_alone, "B on its own draws nothing and quits nothing")
    check(combo_full >= 0.99,
          "the pair fills the bar the whole way, got %r" % combo_full)
    check(combo_caption == "HOLD TO EXIT",
          "and says it is an exit, got %r" % combo_caption)
    check(quit_asked >= 1, "and asks RetroArch to quit, like holding Start")
    check(let_go, "letting go of either one hides the bar at once")
    check(no_late_quit,
          "and nothing quits afterwards: half a gesture is not the gesture")

print("\n-- the hold has to do the quitting itself --")
# RetroArch's own hold-Start combo only listens to player 1. With two pads
# attached, holding Start on the second one filled the bar to the end and then
# nothing happened, because the bar watches every pad and the combo does not.
sent = []


class _Sock(object):
    def __init__(self, *a, **k):
        pass

    def settimeout(self, *a):
        pass

    def sendto(self, data, addr):
        sent.append((data, addr))

    def close(self):
        pass


real_socket = m.socket.socket
m.socket.socket = _Sock
try:
    check(m.send_quit() is True, "a quit is sent")
    check(bool(sent) and sent[0][0] == b"QUIT",
          "and it is the QUIT command, got %r" % (sent[0][0] if sent else None))
    check(bool(sent) and sent[0][1][0] == "127.0.0.1",
          "to the local command interface only, got %r"
          % (sent[0][1] if sent else None,))
    check(isinstance(m.netcmd_port(), int),
          "the port is read from RetroArch's own config")
finally:
    m.socket.socket = real_socket

print("\nFAILURES: %d" % len(fails))
sys.exit(1 if fails else 0)
