"""Turning a RetroArch profile into a Kodi button map.

Kodi ships maps for fourteen controllers and knows nothing about any other, so
every pad in this house had to be taught to it by hand before it could move a
menu. RetroArch has hundreds of profiles here and ra_players already reads
them. kodi_padmap converts one into the other.

The numbering is the whole of the risk. Kodi's udev backend counts buttons in
ascending evdev code order, and axes the same way with hats included;
RetroArch counts buttons in four passes over different ranges and leaves hats
out of its axes entirely. Nothing may be copied across, and a mistake would
not look like a mistake -- it would look like a controller whose buttons are
quietly wrong, which is the thing this exists to prevent.

So it is checked against somebody else's answer rather than my own. Two
things here were written by Kodi and not by us:

  * the maps Kodi ships, for controllers RetroArch also describes. A virtual
    pad declaring exactly what the real one declares drives the conversion,
    and every feature Kodi states is compared with what came out.
  * the nineteen map files already on this machine, each recording inside it
    the device name it was made from -- which is the file-naming rule itself,
    written down by the program we have to agree with.
"""
import importlib.machinery
import importlib.util
import os
import re
import sys
import tempfile
import time

import evdev
from evdev import UInput, ecodes as e

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.dirname(HERE)
KODI_SHIPPED = ("/usr/share/kodi/addons/peripheral.joystick/resources/"
                "buttonmaps/xml/udev")
USER_MAPS = os.path.expanduser("~/.kodi/userdata/addon_data/peripheral.joystick"
                               "/resources/buttonmaps/xml/udev")

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


sys.argv = ["x"]
loader = importlib.machinery.SourceFileLoader(
    "kp", os.path.join(ROOT, "bin", "kodi_padmap.py"))
kp = importlib.util.module_from_spec(
    importlib.util.spec_from_loader("kp", loader))
loader.exec_module(kp)


# --- the naming rule, against every file Kodi has named on this machine ---

def named_files():
    """Every (name, vid, pid, buttons, axes, filename) Kodi has written here.

    The name comes from inside the file; the ids come from the filename. One
    shipped file (HuiJia, hand-written with provider="linux") states no ids
    inside while carrying them in its name, and it is the filename we have to
    reproduce.
    """
    for folder in (KODI_SHIPPED, USER_MAPS):
        if not os.path.isdir(folder):
            continue
        for filename in sorted(os.listdir(folder)):
            if not filename.endswith(".xml"):
                continue
            head = open(os.path.join(folder, filename)).read(600)
            name = re.search(r'<device\s+name="([^"]*)"', head)
            parts = re.search(r'(?:_v([0-9A-F]{4})_p([0-9A-F]{4}))?'
                              r'_(\d+)b_(\d+)a\.xml$', filename)
            if not name or not parts:
                continue
            yield (name.group(1),
                   int(parts.group(1), 16) if parts.group(1) else 0,
                   int(parts.group(2), 16) if parts.group(2) else 0,
                   int(parts.group(3)), int(parts.group(4)), filename)


print("-- the naming rule, against every file Kodi has named here --")
pairs = list(named_files())
# Kodi ships fourteen of these. A machine somebody has already mapped a pad
# on has more, in userdata; a machine installed ten minutes ago has exactly
# the fourteen. Asking for more than Kodi ships was asking for a used console.
check(len(pairs) >= 10, "found %d named files to check against" % len(pairs))
for name, vendor, product, buttons, axes, filename in pairs:
    got = kp.map_filename(name, vendor, product, buttons, axes)
    check(got == filename, "%r -> %s%s" % (
        name, filename, "" if got == filename else "  (this said %s)" % got))


# --- the conversion, against maps Kodi ships ---

# What an xpad-style controller declares. Not invented: xpad reports exactly
# these, and the counts in Kodi's own files -- eleven buttons, eight axes --
# are how we know the set is right.
XPAD_KEYS = [e.BTN_A, e.BTN_B, e.BTN_X, e.BTN_Y, e.BTN_TL, e.BTN_TR,
             e.BTN_SELECT, e.BTN_START, e.BTN_MODE, e.BTN_THUMBL, e.BTN_THUMBR]
STICK = evdev.AbsInfo(0, -32768, 32767, 16, 128, 0)
TRIGGER = evdev.AbsInfo(0, 0, 1023, 0, 0, 0)
HAT = evdev.AbsInfo(0, -1, 1, 0, 0, 0)
XPAD_AXES = [(e.ABS_X, STICK), (e.ABS_Y, STICK), (e.ABS_Z, TRIGGER),
             (e.ABS_RX, STICK), (e.ABS_RY, STICK), (e.ABS_RZ, TRIGGER),
             (e.ABS_HAT0X, HAT), (e.ABS_HAT0Y, HAT)]

# Controllers both projects describe whose capabilities are that plain set.
SUBJECTS = [("Microsoft X-Box One pad", 0x045E, 0x02E6),
            ("Logitech Gamepad F310", 0x046D, 0xC21D)]


def compare(name, vendor, product):
    print()
    print("== %s ==" % name)
    filename = kp.map_filename(name, vendor, product,
                               len(XPAD_KEYS), len(XPAD_AXES))
    shipped = os.path.join(KODI_SHIPPED, filename)
    if not os.path.exists(shipped):
        print("  skipped: Kodi ships no map for it here")
        return
    try:
        pad = UInput({e.EV_KEY: XPAD_KEYS, e.EV_ABS: XPAD_AXES}, name=name,
                     vendor=vendor, product=product, version=0x0301)
    except Exception as exc:
        print("  skipped: cannot make a virtual pad: %s" % exc)
        return
    time.sleep(1.0)
    try:
        mine = [p for p in kp.pads() if p.name == name]
        check(len(mine) == 1, "the virtual pad is seen as a controller")
        if not mine:
            return
        subject = mine[0]
        check(subject.kodi_filename() == filename,
              "the filename is the one Kodi looks for, got %s"
              % subject.kodi_filename())

        profile = kp.profile_for(subject)
        check(bool(profile), "RetroArch has a profile for it")
        if not profile:
            return
        found = kp.features(subject, profile)
        theirs = open(shipped).read()
        generated = kp.xml_for(subject, found)

        print("  -- every button and axis Kodi's own map states --")
        stated = re.findall(
            r'<feature name="(\w+)" (button|axis)="([^"]+)" />', theirs)
        check(len(stated) > 8, "there are %d of them to check" % len(stated))
        for feature, kind, value in stated:
            want = '<feature name="%s" %s="%s" />' % (feature, kind, value)
            check(want in generated, "%s: %s=%s%s" % (
                feature, kind, value, "" if want in generated else
                "  (this produced %r)" % dict(found).get(feature)))

        print("  -- and the sticks, which Kodi writes as four directions --")
        for stick in ("leftstick", "rightstick"):
            block = re.search(r'<feature name="%s">(.*?)</feature>' % stick,
                              theirs, re.S)
            if not block:
                continue
            for way, axis in re.findall(r'<(\w+) axis="([^"]+)" />',
                                        block.group(1)):
                kind, parts = found.get(stick, (None, {}))
                check(parts.get(way) == axis, "%s %s is %s%s" % (
                    stick, way, axis, "" if parts.get(way) == axis else
                    "  (this produced %r)" % parts.get(way)))

        print("  -- Kodi's own map for it is left alone --")
        folder = tempfile.mkdtemp()
        written, kept, unknown = kp.write_maps(into=folder)
        check(not os.path.exists(os.path.join(folder, filename)),
              "nothing is written over a controller Kodi already ships")
        check(name in kept, "and it says so rather than silently doing nothing")
    finally:
        pad.close()
        time.sleep(0.3)


def writing():
    """What happens to the file, on a pad Kodi ships no map for.

    The two above are both controllers Kodi already knows, so they stop at
    that check and never reach the writing. RetroArch describes the 360 pad
    and Kodi does not ship it, which is the ordinary case this exists for.
    """
    name, vendor, product = "Microsoft X-Box 360 pad", 0x045E, 0x028E
    print()
    print("== %s (Kodi ships no map for it) ==" % name)
    filename = kp.map_filename(name, vendor, product,
                               len(XPAD_KEYS), len(XPAD_AXES))
    check(not os.path.exists(os.path.join(KODI_SHIPPED, filename)),
          "Kodi really does not ship one")
    try:
        pad = UInput({e.EV_KEY: XPAD_KEYS, e.EV_ABS: XPAD_AXES}, name=name,
                     vendor=vendor, product=product, version=0x0301)
    except Exception as exc:
        print("  skipped: cannot make a virtual pad: %s" % exc)
        return
    time.sleep(1.0)
    try:
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, filename)
        written, kept, unknown = kp.write_maps(into=folder)
        check(os.path.exists(path), "a map is written for it")
        check(any(w[0] == name for w in written), "and it is reported")
        if not os.path.exists(path):
            return
        check('<feature name="a" button="0" />' in open(path).read(),
              "with the buttons in it")

        print("  -- a map somebody made by hand is never overwritten --")
        with open(path, "w") as handle:
            handle.write("theirs, not mine\n")
        written, kept, unknown = kp.write_maps(into=folder)
        check(open(path).read() == "theirs, not mine\n",
              "the existing file is left exactly as it was")
        check(name in kept, "and it says so rather than silently doing nothing")
        kp.write_maps(into=folder, force=True)
        check(open(path).read() != "theirs, not mine\n",
              "--force replaces it, for somebody who asked")
    finally:
        pad.close()
        time.sleep(0.3)


for subject in SUBJECTS:
    compare(*subject)
writing()

print()
if fails:
    print("FAILED: %d" % len(fails))
    for line in fails:
        print("  " + line)
    sys.exit(1)
print("all good")
