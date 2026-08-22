# -*- coding: utf-8 -*-
"""Shared JoyShockMapper config layer.

Used by BOTH front ends -- the Kodi editor (script.joyshock) and the in-game
overlay (jsm-hud) -- so that the two cannot drift apart in how they parse or
write these files. Nothing here may import Kodi modules.

Extracted from the Kodi addon 2026-08-20, unchanged in behaviour; its test
suite covers this code.
"""

import json
import os
import re
import shutil


HOME = os.path.expanduser("~")
JSM_ROOT = os.path.join(HOME, ".config", "JoyShockMapper")
GAMES_DIR = os.path.join(JSM_ROOT, "games")
GYRO_DIR = os.path.join(JSM_ROOT, "GyroConfigs")
PCGAMES = os.path.join(HOME, ".local", "share", "pcgames.json")

TITLE = "JoyShockMapper"
MANAGED = "# --- edited in Kodi ---"

# An assignment line. The left side may be a plain button or setting, a chord
# ("L,W" -- W while L is held), or a simultaneous press ("L+R", "-+UP", and
# even "-++" for the two system buttons together). JSM allows the bare "+" and
# "-" buttons as names, which is why the name alternative is not simply \w+ --
# and why "-++" parses as "-" plus "+". Include lines (a bare path) and
# argument-less commands (RESET_MAPPINGS) do not match, and so are left alone.
_NAME = r"(?:[+-]|[A-Za-z_][A-Za-z0-9_]*)"
ASSIGN = re.compile(
    r"^(\s*)(" + _NAME + r"(?:\s*[,+]\s*" + _NAME + r")?)(\s*=\s*)"
    r"([^#\n]*?)(\s*)(#.*)?$")

COMBO = re.compile(r"^(" + _NAME + r")\s*([,+])\s*(" + _NAME + r")$")


def canon(key):
    """Whitespace-free form of a binding name, so "L , W" and "L,W" match."""
    return re.sub(r"\s+", "", key)


def split_combo(key):
    """(first, op, second) for a chord or simultaneous press, else None."""
    match = COMBO.match(canon(key))
    return match.groups() if match else None

# ---------------------------------------------------------------------------
# What the controller looks like.
#
# JSM sets SDL_HINT_GAMECONTROLLER_USE_BUTTON_LABELS=0, so face buttons are
# POSITIONAL, not Nintendo labels. On a Switch Pro that means
#   S = bottom = B    E = right = A    W = left = Y    N = top = X
# ---------------------------------------------------------------------------
BUTTON_GROUPS = [
    ("FACE BUTTONS", [
        ("N", "X   (top)"),
        ("E", "A   (right)"),
        ("S", "B   (bottom)"),
        ("W", "Y   (left)"),
    ]),
    ("SHOULDERS AND TRIGGERS", [
        ("L", "L   bumper"),
        ("R", "R   bumper"),
        ("ZL", "ZL  trigger"),
        ("ZR", "ZR  trigger"),
    ]),
    ("D-PAD", [
        ("UP", "D-pad Up"),
        ("DOWN", "D-pad Down"),
        ("LEFT", "D-pad Left"),
        ("RIGHT", "D-pad Right"),
    ]),
    ("STICK CLICKS", [
        ("L3", "L3  (press left stick)"),
        ("R3", "R3  (press right stick)"),
    ]),
    ("LEFT STICK DIRECTIONS", [
        ("LUP", "Left stick Up"),
        ("LDOWN", "Left stick Down"),
        ("LLEFT", "Left stick Left"),
        ("LRIGHT", "Left stick Right"),
    ]),
    ("RIGHT STICK DIRECTIONS", [
        ("RUP", "Right stick Up"),
        ("RDOWN", "Right stick Down"),
        ("RLEFT", "Right stick Left"),
        ("RRIGHT", "Right stick Right"),
    ]),
    ("SYSTEM BUTTONS", [
        ("-", "Minus   (-)"),
        ("+", "Plus   (+)"),
        ("HOME", "Home"),
        ("CAPTURE", "Capture"),
    ]),
]

BUTTON_LABELS = {}
for _group, _pairs in BUTTON_GROUPS:
    for _key, _label in _pairs:
        BUTTON_LABELS[_key] = _label

BUTTON_NAMES = [k for _g, ps in BUTTON_GROUPS for k, _l in ps]

STICK_MODES = ["NO_MOUSE", "AIM", "FLICK", "FLICK_ONLY", "ROTATE_ONLY",
               "MOUSE_RING", "MOUSE_AREA", "OUTER_RING", "INNER_RING",
               "SCROLL_WHEEL"]

# (key, label, kind, choices)
SETTING_GROUPS = [
    ("GYRO", [
        ("GYRO_OFF", "Gyro OFF while this button is held", "button", None),
        ("GYRO_ON", "Gyro ON only while this button is held", "button", None),
        ("GYRO_SENS", "Gyro sensitivity", "num",
         ["1", "2", "3", "4", "6", "8", "10", "12", "16", "24", "32"]),
        ("MIN_GYRO_SENS", "Gyro sensitivity, slow", "num",
         ["1", "2", "4", "6", "8", "12", "16"]),
        ("MAX_GYRO_SENS", "Gyro sensitivity, fast", "num",
         ["4", "8", "12", "16", "24", "32", "48"]),
        ("MOUSE_X_FROM_GYRO_AXIS", "Horizontal comes from gyro axis", "enum",
         ["X", "Y", "Z"]),
        ("MOUSE_Y_FROM_GYRO_AXIS", "Vertical comes from gyro axis", "enum",
         ["X", "Y", "Z"]),
        ("GYRO_SMOOTH_THRESHOLD", "Gyro smoothing threshold", "num",
         ["0", "2", "5", "10", "20"]),
        ("GYRO_CUTOFF_RECOVERY", "Gyro cutoff recovery", "num",
         ["0", "2", "5", "10"]),
    ]),
    ("CALIBRATION", [
        ("REAL_WORLD_CALIBRATION", "Real world calibration", "num",
         ["5.3333", "10", "20", "30", "40", "45", "60", "80", "100"]),
        ("IN_GAME_SENS", "In-game mouse sensitivity", "num",
         ["0.5", "1", "1.5", "2", "3", "4"]),
    ]),
    ("STICKS", [
        ("LEFT_STICK_MODE", "Left stick mode", "enum", STICK_MODES),
        ("RIGHT_STICK_MODE", "Right stick mode", "enum", STICK_MODES),
        ("STICK_SENS", "Stick turn speed (deg/s)", "num",
         ["90", "180", "270", "360", "540", "720"]),
        ("STICK_POWER", "Stick response curve", "num",
         ["0.5", "1", "1.5", "2", "3"]),
        ("STICK_ACCELERATION_RATE", "Stick acceleration rate", "num",
         ["0", "1", "2", "4"]),
        ("STICK_ACCELERATION_CAP", "Stick acceleration cap", "num",
         ["1", "2", "4", "8"]),
        ("LEFT_STICK_DEADZONE_INNER", "Left stick inner deadzone", "num",
         ["0.05", "0.10", "0.15", "0.20", "0.25"]),
        ("LEFT_STICK_DEADZONE_OUTER", "Left stick outer deadzone", "num",
         ["0.05", "0.10", "0.15", "0.20"]),
        ("RIGHT_STICK_DEADZONE_INNER", "Right stick inner deadzone", "num",
         ["0.05", "0.10", "0.15", "0.20", "0.25"]),
        ("RIGHT_STICK_DEADZONE_OUTER", "Right stick outer deadzone", "num",
         ["0.05", "0.10", "0.15", "0.20"]),
        ("SCROLL_SENS", "Scroll wheel sensitivity", "num",
         ["15", "30", "45", "60", "90"]),
    ]),
    # HOLD_PRESS_TIME / SIM_PRESS_WINDOW / DBL_PRESS_WINDOW are deliberately
    # absent: JSM requires HOLD_PRESS_TIME to sit strictly between the other
    # two and silently clamps anything else, so a picker for them would show
    # a value the game never actually uses. Edit those by hand.
    ("TRIGGERS", [
        ("TRIGGER_THRESHOLD", "Trigger pull threshold", "num",
         ["0", "0.25", "0.5", "0.75"]),
    ]),
]

SETTING_LABELS = {}
for _group, _rows in SETTING_GROUPS:
    for _key, _label, _kind, _choices in _rows:
        SETTING_LABELS[_key] = _label

# ---------------------------------------------------------------------------
# Every action JSM's Linux nameToKey() accepts, grouped for picking on a TV.
# Anything offered here is valid by construction, so a config built in this
# screen cannot produce "Unrecognized command" when the game loads it.
# ---------------------------------------------------------------------------
ACTION_GROUPS = [
    ("Letters", [chr(c) for c in range(ord("A"), ord("Z") + 1)]),
    ("Numbers", [str(d) for d in range(0, 10)]),
    ("Numpad", ["N%d" % d for d in range(0, 10)]),
    # LWINDOWS/RWINDOWS only exist because they were added to the Linux
    # nameToKey and mapped to KEY_LEFTMETA/KEY_RIGHTMETA; stock builds reject
    # them, so a config using one needs this box's patched JoyShockMapper.
    ("Modifiers", ["LSHIFT", "RSHIFT", "SHIFT", "LCONTROL", "RCONTROL",
                   "CONTROL", "LALT", "RALT", "ALT", "LWINDOWS", "RWINDOWS"]),
    ("Keys", ["SPACE", "ENTER", "TAB", "ESC", "BACKSPACE", "DELETE", "INSERT",
              "HOME", "END", "PAGEUP", "PAGEDOWN",
              "UP", "DOWN", "LEFT", "RIGHT"]),
    ("Punctuation", ["-", "+", ",", ".", ";", "/", "`", "[", "]", "'", "\\"]),
    ("Function keys", ["F%d" % n for n in range(1, 25)]),
    ("Mouse", ["LMOUSE", "RMOUSE", "MMOUSE", "BMOUSE", "FMOUSE",
               "SCROLLUP", "SCROLLDOWN"]),
    ("Gyro actions", ["GYRO_OFF", "GYRO_ON", "GYRO_INVERT", "GYRO_INV_X",
                      "GYRO_INV_Y", "GYRO_TRACK_X", "GYRO_TRACK_Y",
                      "GYRO_TRACKBALL", "CALIBRATE"]),
    ("Nothing", ["NONE"]),
]


# ---------------------------------------------------------------------------
# Config files
# ---------------------------------------------------------------------------

def resolve(spec):
    """Resolve an include the way JSM does: as given, then under JSM_ROOT."""
    spec = spec.strip().strip('"')
    if os.path.isabs(spec) and os.path.exists(spec):
        return spec
    candidate = os.path.join(JSM_ROOT, spec)
    if os.path.exists(candidate):
        return candidate
    return spec if os.path.exists(spec) else None


class Config(object):
    def __init__(self, path):
        self.path = path
        if os.path.exists(path):
            with open(path, "r") as fh:
                self.lines = fh.read().splitlines()
        else:
            self.lines = []

    # -- includes ----------------------------------------------------------
    def include_index(self):
        for i, line in enumerate(self.lines):
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" in stripped:
                continue
            if stripped.lower().endswith(".txt"):
                return i
        return -1

    def base_spec(self):
        i = self.include_index()
        return self.lines[i].strip() if i >= 0 else None

    def base_path(self):
        spec = self.base_spec()
        return resolve(spec) if spec else None

    def set_base(self, spec):
        i = self.include_index()
        if spec is None:
            if i >= 0:
                del self.lines[i]
            return
        if i >= 0:
            self.lines[i] = spec
        else:
            self.lines.insert(0, spec)

    # -- assignments -------------------------------------------------------
    def own(self, key):
        key = canon(key)
        for line in self.lines:
            match = ASSIGN.match(line)
            if match and canon(match.group(2)) == key:
                return match.group(4).strip()
        return None

    def _combos(self, op):
        for line in self.lines:
            match = ASSIGN.match(line)
            if not match:
                continue
            key = canon(match.group(2))
            parts = split_combo(key)
            if parts and parts[1] == op:
                yield key, parts, match.group(4).strip()

    def all_bindings(self, op):
        """Combo BUTTON bindings of one kind, as (canonical key, value) pairs.
        op is "+" for simultaneous presses or "," for chords.

        Two things are deliberately excluded. A chord whose second half is a
        setting name rather than a button ("L,GYRO_SENS") is a modeshift, not a
        binding -- see chord_settings(). And a chord of a button with itself is
        a double press, not a layer -- see doubles()."""
        out = []
        for key, parts, value in self._combos(op):
            if parts[2] not in BUTTON_LABELS:
                continue
            if op == "," and parts[0] == parts[2]:
                continue
            out.append((key, value))
        return out

    def inherited_bindings(self, op, depth=0):
        """The same, but from the include chain rather than this file."""
        if depth > 8:
            return []
        base = self.base_path()
        if not base or not os.path.exists(base):
            return []
        parent = Config(base)
        out = parent.all_bindings(op)
        mine = set(k for k, _v in out)
        for key, value in parent.inherited_bindings(op, depth + 1):
            if key not in mine:
                out.append((key, value))
        return out

    def effective_bindings(self, op):
        """Combos as they actually resolve: this file's own first, then any
        from the base that this file does not override. Returned as
        (key, value, inherited) so the editor can say where each came from."""
        out = [(k, v, False) for k, v in self.all_bindings(op)]
        mine = set(k for k, _v, _i in out)
        for key, value in self.inherited_bindings(op):
            if key not in mine:
                out.append((key, value, True))
        return out

    def chord_settings(self, held):
        """Settings a hold layer changes while its button is down."""
        out = []
        for key, parts, value in self._combos(","):
            if parts[0] == held and parts[2] in SETTING_LABELS:
                out.append((key, value))
        return out

    def clear_layer(self, held):
        """Drop every binding and setting attached to one hold layer."""
        for key, parts, _value in list(self._combos(",")):
            if parts[0] == held and parts[2] != held:
                self.clear(key)

    def doubles(self):
        return [(key, value) for key, parts, value in self._combos(",")
                if parts[0] == parts[2]]

    def chord_buttons(self):
        """Buttons used as the held half of a chord -- i.e. the hold layers
        this config defines, in the order they first appear. Counts layers
        that only change a setting, which all_bindings deliberately does not."""
        seen = []
        for _key, parts, _value in self._combos(","):
            held = parts[0]
            if held != parts[2] and held not in seen:
                seen.append(held)
        return seen

    def inherited(self, key, depth=0):
        """Value and source file from the include chain, or (None, None)."""
        if depth > 8:
            return None, None
        base = self.base_path()
        if not base or not os.path.exists(base):
            return None, None
        parent = Config(base)
        value = parent.own(key)
        if value is not None:
            return value, base
        return parent.inherited(key, depth + 1)

    def effective(self, key):
        """(value, origin) where origin is None (own), a path, or False."""
        value = self.own(key)
        if value is not None:
            return value, None
        return self.inherited(key)

    def set(self, key, value):
        key = canon(key)
        for i, line in enumerate(self.lines):
            match = ASSIGN.match(line)
            if match and canon(match.group(2)) == key:
                comment = match.group(6) or ""
                gap = match.group(5) if comment else ""
                self.lines[i] = "%s%s%s%s%s%s" % (
                    match.group(1), match.group(2), match.group(3), value,
                    gap, comment)
                return
        if MANAGED not in self.lines:
            if self.lines and self.lines[-1].strip():
                self.lines.append("")
            self.lines.append(MANAGED)
        self.lines.append("%s = %s" % (key, value))

    def clear(self, key):
        key = canon(key)
        kept = []
        for line in self.lines:
            match = ASSIGN.match(line)
            if match and canon(match.group(2)) == key:
                continue
            kept.append(line)
        self.lines = kept

    def save(self):
        directory = os.path.dirname(self.path)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory)
        with open(self.path, "w") as fh:
            fh.write("\n".join(self.lines).rstrip("\n") + "\n")


def list_configs():
    """Every editable config: per-game files first, then the shared bases."""
    out = []
    for directory in (GAMES_DIR, GYRO_DIR):
        if not os.path.isdir(directory):
            continue
        for name in sorted(os.listdir(directory)):
            if name.endswith(".txt"):
                out.append(os.path.join(directory, name))
    return out


def bases():
    out = []
    if os.path.isdir(GYRO_DIR):
        for name in sorted(os.listdir(GYRO_DIR)):
            if name.startswith("_base") and name.endswith(".txt"):
                out.append("GyroConfigs/" + name)
    return out


# ---------------------------------------------------------------------------
# pcgames.json
# ---------------------------------------------------------------------------

def load_games():
    try:
        with open(PCGAMES) as fh:
            return json.load(fh)
    except (IOError, OSError, ValueError):
        return None


def save_games(data):
    shutil.copy2(PCGAMES, PCGAMES + ".kodi-undo")
    with open(PCGAMES, "w") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
