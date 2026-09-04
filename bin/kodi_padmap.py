#!/usr/bin/env python3
"""Give Kodi a button map for any controller RetroArch already knows.

Kodi ships button maps for fourteen controllers. Not one of them is a
controller in this house, so every pad here had to be taught to Kodi by hand,
button by button, before it could move a menu -- and a guest who brings their
own arrives at a machine that does not answer their controller at all.

RetroArch has 441 profiles on this machine and `ra_players.py` already reads
them: it is how the player picker knows which button is Start on a pad whose
kernel driver calls it something else. This turns one of those profiles into
the other file, so a pad that works in a game works in the menus.

The numbering is the whole of the work, and neither project's numbers are the
other's. Kodi's udev backend counts buttons in ascending evdev code order and
axes the same way, hats included -- checked against the map it ships for an
Xbox One pad and against the hand-made map for the Sunshine pad on this
machine, which agree. RetroArch counts in four passes over different ranges
and leaves hats out of its axis numbering entirely. So nothing is copied
across: every number is turned back into the evdev code it stands for, and
then into the number the other side would give that code.

Never overwrites a map somebody made by hand. A map that is there is a map
somebody was happy enough with to stop pressing buttons.
"""

import argparse
import glob
import importlib.machinery
import importlib.util
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
KODI_MAPS = os.path.expanduser(
    "~/.kodi/userdata/addon_data/peripheral.joystick/resources/buttonmaps/xml/udev")
KODI_SHIPPED = "/usr/share/kodi/addons/peripheral.joystick/resources/buttonmaps/xml/udev"


def _ra_players():
    """The profile reader, borrowed rather than copied.

    Importing it costs a pygame banner on stdout, which is a small price for
    not having a second implementation of "which RetroArch profile is this
    pad" that can disagree with the first.
    """
    path = os.path.join(HERE, "ra_players.py")
    if not os.path.exists(path):
        path = os.path.expanduser("~/.local/bin/ra_players.py")
    argv, sys.argv = sys.argv, ["kodi_padmap"]
    try:
        loader = importlib.machinery.SourceFileLoader("ra_players", path)
        module = importlib.util.module_from_spec(
            importlib.util.spec_from_loader("ra_players", loader))
        loader.exec_module(module)
    finally:
        sys.argv = argv
    return module


rp = _ra_players()
import evdev                                                    # noqa: E402
from evdev import ecodes as e                                   # noqa: E402


# Which RetroArch setting becomes which Kodi feature.
#
# The face buttons are chosen by what is *printed* on them rather than by
# where they sit, which is the same rule ra_players uses for the picker and
# the rule the hand-made maps on this machine already follow: Kodi's "a" is
# its confirm, and somebody with a Switch pad expects the button marked A to
# confirm even though it is the right-hand one. RetroArch's own names are
# Nintendo's, so a profile that labels input_a_btn "A" is a Nintendo layout
# and the names line up; anything else is an Xbox layout and the pairs cross.
FACES_NINTENDO = {"a": "input_a_btn", "b": "input_b_btn",
                  "x": "input_x_btn", "y": "input_y_btn"}
FACES_OTHERS = {"a": "input_b_btn", "b": "input_a_btn",
                "x": "input_y_btn", "y": "input_x_btn"}

# Everything else is positional and needs no such decision.
PLAIN = {
    "back": "input_select_btn",
    "start": "input_start_btn",
    "guide": "input_menu_toggle_btn",
    "leftbumper": "input_l_btn",
    "rightbumper": "input_r_btn",
    "leftthumb": "input_l3_btn",
    "rightthumb": "input_r3_btn",
}
# A trigger is a button on some pads and an axis on others, and profiles say
# which by which setting they use.
TRIGGERS = {"lefttrigger": ("input_l2_btn", "input_l2_axis"),
            "righttrigger": ("input_r2_btn", "input_r2_axis")}
DPAD = {"up": "input_up_btn", "down": "input_down_btn",
        "left": "input_left_btn", "right": "input_right_btn"}
STICKS = {"leftstick": ("input_l_x", "input_l_y"),
          "rightstick": ("input_r_x", "input_r_y")}


# Kodi cuts a pad's name off here when it names the file. Counted off its
# own output: "Sony Interactive Entertainment Wireless Controller" is fifty
# characters and survives whole, while the fifty-four character mayflash
# adapter loses its last four.
NAME_LIMIT = 50


def map_filename(name, vendor, product, buttons, axes):
    """Kodi's name for a pad's map file, apart from any real device.

    Split out from the Pad so it can be held against the nineteen files Kodi
    has already written on this machine without needing the controllers back.
    """
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", name)[:NAME_LIMIT]
    ids = ""
    if vendor or product:
        ids = "_v%04X_p%04X" % (vendor, product)
    return "%s%s_%db_%da.xml" % (safe, ids, buttons, axes)


class Pad:
    """One controller, and the two numberings that describe it."""

    def __init__(self, device):
        self.device = device
        caps = device.capabilities(absinfo=False)
        self.keys = sorted(caps.get(e.EV_KEY, []))
        self.axes = sorted(caps.get(e.EV_ABS, []))
        # Kodi: ascending, and hats are axes like any other.
        self.kodi_button = {code: i for i, code in enumerate(self.keys)}
        self.kodi_axis = {code: i for i, code in enumerate(self.axes)}
        # RetroArch: its own four-pass order for buttons, and axes that skip
        # the hats -- a hat is written "h0up" there rather than as an axis.
        self.ra_button = rp.udev_button_index(self.keys)
        self.ra_code_of_button = {i: c for c, i in self.ra_button.items()}
        flat = [c for c in self.axes if c not in (e.ABS_HAT0X, e.ABS_HAT0Y)]
        self.ra_code_of_axis = {i: code for i, code in enumerate(flat)}

    @property
    def name(self):
        return self.device.name

    def kodi_filename(self):
        """What Kodi calls the file for this pad.

        Its own scheme, matched rather than invented: the name with every
        awkward character turned into an underscore, the ids if the device has
        them, and the two counts. A file under any other name is a file Kodi
        never looks at.

        Letters, digits, dots, hyphens and underscores survive; everything
        else becomes an underscore. That is read off Kodi's own output rather
        than guessed: it keeps the hyphen in "Microsoft X-Box One pad" and the
        dots in "Nintendo Co., Ltd. Pro Controller" while turning that name's
        comma and spaces into underscores. A pad with no ids, as Bluetooth
        ones often are, is named without them. A long name is cut short, as
        Kodi cuts "mayflash limited MAYFLASH GameCube Controller Adapter"
        down to "..._Adap".
        """
        info = self.device.info
        return map_filename(self.name, info.vendor, info.product,
                            len(self.keys), len(self.axes))


def profile_for(pad):
    return rp.find_profile(pad.device)


def kodi_button(pad, profile, setting):
    """The Kodi button number for a profile's button setting, or None."""
    raw = (profile.get(setting) or "").strip()
    if not raw or raw.startswith("h") or raw.startswith(("+", "-")):
        return None
    try:
        code = pad.ra_code_of_button.get(int(raw))
    except ValueError:
        return None
    return None if code is None else pad.kodi_button.get(code)


def kodi_axis(pad, profile, setting):
    """The Kodi axis for a profile's axis setting, as "+3" or "-3"."""
    raw = (profile.get(setting) or "").strip()
    if not raw or raw[0] not in "+-":
        return None
    try:
        code = pad.ra_code_of_axis.get(int(raw[1:]))
    except ValueError:
        return None
    if code is None or code not in pad.kodi_axis:
        return None
    return "%s%d" % (raw[0], pad.kodi_axis[code])


def kodi_hat(pad, profile, setting):
    """A d-pad direction written as a hat, as Kodi's signed axis."""
    raw = (profile.get(setting) or "").strip().lower()
    match = re.fullmatch(r"h\d+(up|down|left|right)", raw)
    if not match:
        return None
    which = match.group(1)
    code = e.ABS_HAT0X if which in ("left", "right") else e.ABS_HAT0Y
    if code not in pad.kodi_axis:
        return None
    sign = "-" if which in ("up", "left") else "+"
    return "%s%d" % (sign, pad.kodi_axis[code])


def features(pad, profile):
    """Every Kodi feature this profile can describe, in Kodi's own order."""
    faces = (FACES_NINTENDO
             if (profile.get("input_a_btn_label", "").strip().lower() == "a")
             else FACES_OTHERS)
    found = {}

    for feature, setting in list(faces.items()) + list(PLAIN.items()):
        number = kodi_button(pad, profile, setting)
        if number is not None:
            found[feature] = ("button", number)

    for feature, (as_button, as_axis) in TRIGGERS.items():
        number = kodi_button(pad, profile, as_button)
        if number is not None:
            found[feature] = ("button", number)
            continue
        axis = kodi_axis(pad, profile, as_axis)
        if axis is not None:
            found[feature] = ("axis", axis)

    for feature, setting in DPAD.items():
        axis = kodi_hat(pad, profile, setting)
        if axis is not None:
            found[feature] = ("axis", axis)
            continue
        number = kodi_button(pad, profile, setting)
        if number is not None:
            found[feature] = ("button", number)

    for feature, (x_prefix, y_prefix) in STICKS.items():
        parts = {}
        for way, setting in (("right", x_prefix + "_plus_axis"),
                             ("left", x_prefix + "_minus_axis"),
                             ("down", y_prefix + "_plus_axis"),
                             ("up", y_prefix + "_minus_axis")):
            axis = kodi_axis(pad, profile, setting)
            if axis is not None:
                parts[way] = axis
        # All four or none: half a stick is a stick that walks one way.
        if len(parts) == 4:
            found[feature] = ("stick", parts)
    return found


def xml_for(pad, found):
    """The file Kodi reads, in the shape Kodi writes."""
    info = pad.device.info
    ids = ""
    if info.vendor or info.product:
        ids = ' vid="%04X" pid="%04X"' % (info.vendor, info.product)
    out = ['<?xml version="1.0" ?>', "<buttonmap>",
           '    <device name="%s" provider="udev"%s buttoncount="%d" axiscount="%d">'
           % (pad.name, ids, len(pad.keys), len(pad.axes)),
           '        <controller id="game.controller.default">']
    for feature in sorted(found):
        kind, value = found[feature]
        if kind == "button":
            out.append('            <feature name="%s" button="%d" />'
                       % (feature, value))
        elif kind == "axis":
            out.append('            <feature name="%s" axis="%s" />'
                       % (feature, value))
        else:
            out.append('            <feature name="%s">' % feature)
            for way in ("up", "down", "right", "left"):
                out.append('                <%s axis="%s" />' % (way, value[way]))
            out.append("            </feature>")
    out += ["        </controller>", "    </device>", "</buttonmap>", ""]
    return "\n".join(out)


def pads():
    """Every attached controller, ignoring our own virtual ones.

    Fourth Player's pads are written for by fourth-player itself and belong to
    guests; a map for one of them in Kodi would be a guest driving the menus.
    """
    for path in sorted(evdev.list_devices()):
        try:
            device = evdev.InputDevice(path)
        except OSError:
            continue
        caps = device.capabilities(absinfo=False)
        keys = set(caps.get(e.EV_KEY, []))
        if not (keys & set(range(e.BTN_JOYSTICK, e.BTN_DIGI))) or \
                not caps.get(e.EV_ABS):
            device.close()
            continue
        if device.name.startswith("Fourth Player"):
            device.close()
            continue
        yield Pad(device)


def write_maps(force=False, into=KODI_MAPS):
    written, kept, unknown = [], [], []
    for pad in pads():
        profile = profile_for(pad)
        if not profile:
            unknown.append(pad.name)
            continue
        found = features(pad, profile)
        if "a" not in found:
            # A map with no confirm button is a menu nobody can get out of.
            unknown.append(pad.name)
            continue
        # Kodi ships maps for fourteen controllers, and one of those is
        # already right -- and hand-checked by people who own the pad. Writing
        # our own copy into userdata would override it to no purpose, so a pad
        # Kodi already knows is left to Kodi.
        name = pad.kodi_filename()
        if os.path.exists(os.path.join(KODI_SHIPPED, name)) and not force:
            kept.append(pad.name)
            continue
        path = os.path.join(into, name)
        if os.path.exists(path) and not force:
            kept.append(pad.name)
            continue
        os.makedirs(into, exist_ok=True)
        with open(path, "w") as handle:
            handle.write(xml_for(pad, found))
        written.append((pad.name, len(found), path))
    return written, kept, unknown


def check():
    """Compare what this would write with maps somebody else decided.

    Two answer keys, and neither of them is mine. Kodi ships maps for fourteen
    controllers, which is the ideal comparison and only useful if one of them
    is plugged in. The maps already in this profile are the other: a person sat
    in front of the television and pressed each button in turn, so where those
    disagree with this, one of us has the pad the wrong way round -- and it is
    worth knowing which before this writes anything.
    """
    shipped = {}
    for folder in (KODI_SHIPPED, KODI_MAPS):
        for path in sorted(glob.glob(os.path.join(folder, "*.xml"))):
            text = open(path).read()
            name = re.search(r'name="([^"]+)"', text)
            if name and name.group(1) not in shipped:
                shipped[name.group(1)] = (path, text)
    for path in []:
        pass
    if not shipped:
        print("no maps to check against")
        return 0
    print("%d maps to check against (Kodi's own, and this profile's)."
          % len(shipped))
    checked = 0
    for pad in pads():
        if pad.name not in shipped:
            print("  %-34s nothing to compare with" % pad.name)
            continue
        profile = profile_for(pad)
        if not profile:
            print("  %-34s Kodi knows it, RetroArch does not" % pad.name)
            continue
        checked += 1
        theirs = shipped[pad.name][1]
        mine = xml_for(pad, features(pad, profile))
        for line in theirs.splitlines():
            found = re.search(r'name="(\w+)" (button|axis)="([^"]+)"', line)
            if not found:
                continue
            feature, kind, value = found.groups()
            want = '<feature name="%s" %s="%s" />' % (feature, kind, value)
            print("  %-34s %-14s %s" % (pad.name, feature,
                                        "agrees" if want in mine else
                                        "DIFFERS (Kodi says %s)" % value))
    if not checked:
        print("no attached pad has a map to compare with.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true",
                        help="replace maps that already exist")
    parser.add_argument("--check", action="store_true",
                        help="compare against the maps Kodi ships, and stop")
    parser.add_argument("--into", default=KODI_MAPS,
                        help="where to write (for testing)")
    args = parser.parse_args(argv)

    if args.check:
        return check()

    written, kept, unknown = write_maps(force=args.force, into=args.into)
    for name, count, path in written:
        print("   ok    %s: %d controls -> %s" % (name, count,
                                                  os.path.basename(path)))
    for name in kept:
        print("   --    %s already has a map; left alone" % name)
    for name in unknown:
        print("   --    %s: no RetroArch profile, so nothing to convert" % name)
    if not (written or kept or unknown):
        print("   --    no controllers attached")
    return 0


if __name__ == "__main__":
    sys.exit(main())
