"""The player picker: how many slots, who may claim one, and what gets written.

The override is the part that matters -- a wrong line there means someone's
controller silently does nothing, or two people drive the same character.
"""
import importlib.machinery
import importlib.util
import os
import sys
import tempfile

sys.argv = ["x"]
loader = importlib.machinery.SourceFileLoader("rp", os.path.expanduser("~/.local/bin/ra_players.py"))
m = importlib.util.module_from_spec(importlib.util.spec_from_loader("rp", loader))
loader.exec_module(m)

import evdev
from evdev import ecodes as e

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


class FakeDev:
    def __init__(self, name):
        self.name = name

    def close(self):
        pass


class Event:
    def __init__(self, etype, code, value):
        self.type, self.code, self.value = etype, code, value


def pad(index, name="Pad", kind="pad", cursor=0):
    return m.Pad(index, "/dev/input/event%s" % index, FakeDev(name), kind, cursor)


def key(code, value=1):
    return Event(e.EV_KEY, code, value)


def override_text(pads, slots):
    path = m.write_override(pads, slots)
    text = open(path).read()
    os.unlink(path)
    return text


print("-- four slots normally, eight once there are more than four devices --")
for count, want in ((1, 4), (2, 4), (4, 4), (5, 8), (6, 8), (8, 8), (12, 8)):
    got = m.player_slots(range(count))
    check(got == want, "%d devices -> %d slots, got %d" % (count, want, got))

print("-- and the board is one row, or two --")
check(m.slot_rows(4) == (1, 4), "4 -> one row of 4, got %r" % (m.slot_rows(4),))
check(m.slot_rows(8) == (2, 4), "8 -> two rows of 4, got %r" % (m.slot_rows(8),))

print("-- claiming --")
a, b = pad(0), pad(1)
pads = [a, b]
a.cursor = 2
check(m.claim(a, pads) is None, "a free slot is taken")
check(a.slot == 2, "landed on slot 2, got %r" % a.slot)
b.cursor = 2
check(m.claim(b, pads) == "SLOT TAKEN", "a taken slot is refused")
check(b.slot is None, "and the second pad holds nothing")

print("-- only one keyboard, because RetroArch merges them --")
k1, k2 = pad(None, "USB Keyboard", "kbd"), pad(None, "Keyboard passthrough", "kbd")
pads = [k1, k2]
k1.cursor, k2.cursor = 0, 1
check(m.claim(k1, pads) is None, "the first keyboard may play")
check(m.claim(k2, pads) == "ONLY ONE KEYBOARD CAN PLAY",
      "the second is refused with a reason")
check(k2.slot is None, "and holds nothing")

print("-- a pad still may, alongside a keyboard --")
p = pad(0)
pads = [k1, p]
p.cursor = 3
check(m.claim(p, pads) is None, "a pad is unaffected by the keyboard rule")

print("-- pad input --")
p = pad(0)
pads = [p]
launch, _ = m.handle_event(p, key(e.BTN_SOUTH), pads, 8)
check(p.slot == 0 and not launch, "A claims, got slot %r" % p.slot)
m.handle_event(p, key(e.BTN_EAST), pads, 8)
check(p.slot is None and p.cursor == 0, "B releases back onto the slot")
p.slot = 0
launch, _ = m.handle_event(p, key(e.BTN_START), pads, 8)
check(launch, "START launches once someone is ready")

print("-- and moves across a board of eight --")
p = pad(0)
p.slot, p.cursor = None, 0
m.handle_event(p, Event(e.EV_ABS, e.ABS_HAT0X, 1), [p], 8)
check(p.cursor == 1, "right moves one, got %r" % p.cursor)
p.axis_latch = 0
m.handle_event(p, Event(e.EV_ABS, e.ABS_HAT0Y, 1), [p], 8)
check(p.cursor == 5, "down moves a whole row, got %r" % p.cursor)
p.axis_latch = 0
m.handle_event(p, Event(e.EV_ABS, e.ABS_HAT0Y, 1), [p], 8)
check(p.cursor == 7, "down again stops at the end, got %r" % p.cursor)
p.axis_latch = 0
for _ in range(20):
    p.axis_latch = 0
    m.handle_event(p, Event(e.EV_ABS, e.ABS_HAT0X, -1), [p], 8)
check(p.cursor == 0, "left stops at the start, got %r" % p.cursor)

print("-- keyboard input uses RetroArch's own default keys --")
k = pad(None, "USB Keyboard", "kbd")
pads = [k]
m.handle_event(k, key(e.KEY_RIGHT), pads, 8)
check(k.cursor == 1, "right arrow moves, got %r" % k.cursor)
m.handle_event(k, key(e.KEY_DOWN), pads, 8)
check(k.cursor == 5, "down arrow moves a row, got %r" % k.cursor)
m.handle_event(k, key(e.KEY_X), pads, 8)
check(k.slot == 5, "X claims, got %r" % k.slot)
m.handle_event(k, key(e.KEY_Z), pads, 8)
check(k.slot is None, "Z releases")
k.slot = 5
launch, _ = m.handle_event(k, key(e.KEY_ENTER), pads, 8)
check(launch, "ENTER launches")

print("-- each pad's buttons come from RetroArch's own profile --")
import collections

_Info = collections.namedtuple("Info", "bustype vendor product version")


class CapDev(FakeDev):
    """A device the mapping layer can interrogate: a name, ids and a key list."""

    def __init__(self, name, vendor, product, keys):
        FakeDev.__init__(self, name)
        self.info = _Info(3, vendor, product, 1)
        self._keys = keys

    def capabilities(self, absinfo=False):
        return {e.EV_KEY: list(self._keys)}


# The key list read off a real Switch-layout pad, and xpad's shorter one
# (no BTN_C/BTN_Z, and triggers are axes so no BTN_TL2/BTN_TR2).
SWITCH_KEYS = [0x130, 0x131, 0x133, 0x134, 0x135, 0x136, 0x137, 0x138,
               0x139, 0x13a, 0x13b, 0x13c, 0x13d, 0x13e]
XPAD_KEYS = [0x130, 0x131, 0x133, 0x134, 0x136, 0x137,
             0x13a, 0x13b, 0x13c, 0x13d, 0x13e]


def acts(dev):
    """action -> code, plus the labels.

    Lossy on purpose for the single-valued actions. `confirm` is not one of
    them any more -- spare upper face buttons are accepted as extra ways to
    claim -- so ask `confirms()` which buttons do it rather than reading this.
    """
    btn, labels = m.pad_controls(dev)
    return {a: c for c, a in btn.items()}, labels


def confirms(dev):
    """Every code that claims a slot on this pad."""
    btn, _ = m.pad_controls(dev)
    return {c for c, a in btn.items() if a == "confirm"}


# A Switch pad prints A on the *right* face button and Xbox prints it on the
# bottom one. Both must claim on the button the player can see marked A, or
# the prompt is a lie -- this is the swap the profiles are here to fix.
a, lab = acts(CapDev("Nintendo Switch Pro Controller", 0x57e, 0x2009, SWITCH_KEYS))
check(e.BTN_EAST in confirms(CapDev("Nintendo Switch Pro Controller", 0x57e, 0x2009, SWITCH_KEYS)),
      "Switch claims on the right face button")
check(a["back"] == e.BTN_SOUTH, "Switch backs out on the bottom one")
check(a["start"] == e.BTN_START and lab["start"] == "+", "Switch start is +, got %r" % lab["start"])
check(lab["confirm"] == "A" and lab["back"] == "B", "and prints A / B")

a, lab = acts(CapDev("Afterglow AX.1 Gamepad for Xbox 360", 3695, 1043, XPAD_KEYS))
check(e.BTN_SOUTH in confirms(CapDev("Microsoft X-Box 360 pad", 0x45e, 0x28e, XPAD_KEYS)),
      "an Xbox pad claims on the bottom face button")
check(a["back"] == e.BTN_EAST, "and backs out on the right one")
check(lab["confirm"] == "A" and lab["back"] == "B",
      "printing A / B as well, so one prompt suits both")

print("-- a pad with no profile keeps the positional codes --")
a, lab = acts(CapDev("No Such Controller", 0x9999, 0x9999, XPAD_KEYS))
check(a["confirm"] == e.BTN_SOUTH and a["back"] == e.BTN_EAST,
      "unknown pads fall back rather than losing their buttons")
check(a["start"] == e.BTN_START, "including start")

print("-- and Sunshine's virtual pad is found by its ids, not its name --")
sunshine = CapDev("Sunshine Nintendo (virtual) pad", 0x57e, 0x2009, SWITCH_KEYS)
check(e.BTN_EAST in confirms(sunshine), "the borrowed vendor/product ids identify it")

print("-- an id several profiles claim is decided by the name --")
# 1118:654 is a Microsoft Xbox 360 pad, and it is what every third-party and
# virtual pad pretends to be: three profiles in the packaged set claim it. When
# whichever the directory listing ended on won, a real Xbox pad on a fresh
# install got a handheld's profile, with confirm on the north face button.
xbox_prof = {"input_driver": "udev", "input_device": "Microsoft X-Box 360 pad",
             "input_b_btn": "0", "input_a_btn": "1"}
handheld = {"input_driver": "udev", "input_device": "Handheld Controller",
            "input_b_btn": "3", "input_a_btn": "2"}
series = {"input_driver": "udev", "input_device": "Microsoft X-Box Series X|S pad BT",
          "input_b_btn": "0", "input_a_btn": "1"}
check(m.best_by_ids([handheld, series], "Microsoft X-Box 360 pad") is series,
      "an Xbox pad takes the Xbox profile, not the handheld one")
check(m.best_by_ids([handheld], "Microsoft X-Box 360 pad") is handheld,
      "one candidate is still used: an id that only one profile claims is a fact")
check(m.best_by_ids([handheld, series], "Some Unrelated Thing") is None,
      "and a name with nothing in common falls back rather than guessing")
check(m.best_by_ids([xbox_prof, series], "Sunshine X-Box One (virtual) pad") is not None,
      "Sunshine's invented name still finds its borrowed profile")
check(m.name_words("Microsoft X-Box 360 pad") == {"microsoft", "xbox", "360", "pad"},
      "X-Box and Xbox are the same word: %s" % m.name_words("Microsoft X-Box 360 pad"))

print("-- profiles are found where RetroArch actually files them --")
import tempfile

_real_dirs = m.AUTOCONFIG_DIRS
_root = tempfile.mkdtemp()
os.makedirs(os.path.join(_root, "udev"))
# RetroArch files profiles under a directory named for the input driver, which
# is where every one of the hundreds on a real machine lives. Listing only the
# parent found none of them, and the picker then fell back to matching by
# vendor and product -- where a stock profile sharing an Xbox 360's ids
# answered for a completely different pad.
with open(os.path.join(_root, "udev", "Made Up Pad.cfg"), "w") as fh:
    fh.write('''input_driver = "udev"
input_device = "Made Up Pad"
input_b_btn = "0"
input_a_btn = "1"
input_a_btn_label = "B"
input_start_btn = "7"
''')
try:
    m.AUTOCONFIG_DIRS = (_root,)
    m._PROFILES = None          # the index is built once and kept
    found = m.find_profile(CapDev("Made Up Pad", 0x1234, 0x5678, XPAD_KEYS))
    check(found is not None, "a profile in the udev subdirectory is found at all")
    check(found and found.get("input_device") == "Made Up Pad",
          "and it is the right one")
    missing = m.find_profile(CapDev("Nobody Pad", 0x1234, 0x5678, XPAD_KEYS))
    check(missing is None, "a name nothing matches still finds nothing")
finally:
    m.AUTOCONFIG_DIRS = _real_dirs
    m._PROFILES = None

print("-- a spare upper face button is a second way to claim --")
xbox = CapDev("Microsoft X-Box 360 pad", 0x45e, 0x28e, XPAD_KEYS)
if m.find_profile(xbox) is None:
    # A fresh install has only the packaged profiles, and the Xbox 360 one in
    # that set declares input_driver "x" rather than "udev" -- rightly ignored,
    # because the button numbers differ per driver and using the wrong set puts
    # confirm somewhere arbitrary. RetroArch downloads the udev profiles itself
    # after first run. Until then this pad falls back to the built-in defaults,
    # which is a different thing from what this section is checking.
    print("  --    no udev profile for an Xbox 360 pad here yet; "
          "skipping the profile-driven checks")
else:
    xbox_confirms = confirms(xbox)
    check(e.BTN_SOUTH in xbox_confirms, "the button printed A still claims")
    check(e.BTN_X in xbox_confirms,
          "and so does the west one, which is where a Mega Drive prints its A")
    xbox_btn, _ = m.pad_controls(xbox)
    check(xbox_btn[e.BTN_EAST] == "back",
          "backing out is untouched -- the east button is not stolen")
    check(xbox_btn[e.BTN_START] == "start", "and neither is start")

print("-- button numbers follow the device's own key list --")
idx = m.udev_button_index(SWITCH_KEYS)
check(idx[e.BTN_SOUTH] == 0 and idx[e.BTN_EAST] == 1 and idx[e.BTN_START] == 10,
      "udev numbering matches the profile's numbers")
shifted = m.udev_button_index([c for c in SWITCH_KEYS if c != 0x135])
check(shifted[e.BTN_MODE] == 10,
      "dropping one key shifts every later number, as the driver does")
# Arrow keys are scanned before the BTN_ range, so an arcade stick that
# reports them pushes every gamepad button along by four.
arcade = m.udev_button_index([e.KEY_UP, e.KEY_DOWN, e.KEY_LEFT, e.KEY_RIGHT] + SWITCH_KEYS)
check(arcade[e.BTN_SOUTH] == 4, "arrow keys are numbered first, got %r" % arcade[e.BTN_SOUTH])

print("-- a pad whose d-pad is buttons can still move --")
p = pad(0)
p.btn = {0x220: "left", 0x221: "right", 0x222: "up", 0x223: "down"}
p.cursor = 0
m.handle_event(p, key(0x221), [p], 8)
check(p.cursor == 1, "a button d-pad moves right, got %r" % p.cursor)
m.handle_event(p, key(0x223), [p], 8)
check(p.cursor == 5, "and down a whole row, got %r" % p.cursor)

print("-- the footer names a button both pads really have --")
n1, x1 = pad(0), pad(1)
n1.labels = {"confirm": "A", "back": "B", "start": "+"}
x1.labels = {"confirm": "A", "back": "B", "start": "START"}
check(m.prompt_labels([n1, x1])["confirm"] == "A", "agreed labels are used")
ps = pad(2)
ps.labels = {"confirm": "CROSS", "back": "CIRCLE", "start": "START"}
check(m.prompt_labels([ps])["confirm"] == "CROSS", "a PlayStation pad says CROSS")
check(m.prompt_labels([n1, x1, ps])["start"] == "START",
      "and the commonest label wins when they disagree")

print("-- B backs out of the screen, so a pad alone can cancel --")
p = pad(0)
action, _ = m.handle_event(p, key(e.BTN_EAST), [p], 4)
check(action == "cancel", "B on an empty board cancels, got %r" % action)
p.slot = 0
action, _ = m.handle_event(p, key(e.BTN_EAST), [p], 4)
check(action is None and p.slot is None,
      "B releases rather than cancelling when it holds a slot, got %r" % action)

print("-- but one player cannot cancel out from under another --")
p0, p1 = pad(0), pad(1)
p0.slot = 0
action, _ = m.handle_event(p1, key(e.BTN_EAST), [p0, p1], 4)
check(action is None and p0.slot == 0,
      "B does nothing while someone else is ready, got %r" % action)

print("-- and the keyboard's release key backs out the same way --")
k3 = pad(None, "USB Keyboard", "kbd")
action, _ = m.handle_event(k3, key(e.KEY_Z), [k3], 4)
check(action == "cancel", "Z on an empty board cancels, got %r" % action)

print("-- key releases do nothing --")
k2 = pad(None, "USB Keyboard", "kbd")
m.handle_event(k2, key(e.KEY_X, 0), [k2], 8)
check(k2.slot is None, "a key-up does not claim")

print("-- the override: pads get their joypad index --")
p0, p1 = pad(0, "Pro Controller"), pad(3, "Xbox Wireless Controller")
p0.slot, p1.slot = 0, 2
text = override_text([p0, p1], 8)
check('input_player1_joypad_index = "0"' in text, "player 1 -> index 0")
check('input_player3_joypad_index = "3"' in text, "player 3 -> index 3")

print("-- unclaimed ports are parked, all the way to eight --")
for port in (2, 4, 5, 6, 7, 8):
    check('input_player%d_joypad_index = "99"' % port in text,
          "player %d parked" % port)
check(text.count("joypad_index") == 8, "eight ports written, got %d"
      % text.count("joypad_index"))

print("-- with four slots only four ports are written --")
p0.slot, p1.slot = 0, 2
text4 = override_text([p0, p1], 4)
check(text4.count("joypad_index") == 4, "four ports, got %d"
      % text4.count("joypad_index"))

print("-- no keyboard player means no keyboard lines at all --")
check("input_player1_a" not in text, "the config's own binds are left alone")

print("-- a keyboard player gets the binds, and only on its own port --")
kb = pad(None, "USB Keyboard", "kbd")
p0.slot, kb.slot = 0, 4
tmp = tempfile.mkdtemp()
cfg = os.path.join(tmp, "retroarch.cfg")
open(cfg, "w").write('input_player1_a = "x"\ninput_player1_start = "enter"\n'
                     'input_player1_left = "left"\n')
m.RA_CFG = cfg
text = override_text([p0, kb], 8)
check('input_player5_a = "x"' in text, "player 5 gets A")
check('input_player5_start = "enter"' in text, "player 5 gets START")
check('input_player1_a = "nul"' in text,
      "player 1's keyboard binds are cleared, or it would drive two players")
check('input_player8_a = "nul"' in text, "and so is every other port")
check(text.count('_a = "nul"') == 7, "seven ports cleared, got %d"
      % text.count('_a = "nul"'))
check('input_player5_joypad_index = "99"' in text,
      "the keyboard's port takes no joypad")

print("-- each device keeps its own colour --")
group = [pad(0, "Pro Controller"), pad(1, "Xbox Wireless Controller"),
         pad(None, "USB Keyboard", "kbd")]
m.assign_colors(group)
colors = [q.color_index for q in group]
check(len(set(colors)) == 3, "all different, got %r" % colors)
check(colors == [0, 1, 2], "and handed out in order, got %r" % colors)

print("-- a colour survives someone else leaving --")
was = group[2].color_index
group.pop(0)                       # the first pad unplugs
m.assign_colors(group)
check(group[-1].color_index == was,
      "the keyboard kept colour %r, got %r" % (was, group[-1].color_index))

print("-- and a new arrival takes the freed colour --")
group.append(pad(4, "8BitDo SN30"))
m.assign_colors(group)
check(group[-1].color_index == 0, "reused the freed 0, got %r"
      % group[-1].color_index)
check(len(set(q.color_index for q in group)) == len(group), "still all distinct")

print("-- the icons draw without a real display --")
import os
os.environ["SDL_VIDEODRIVER"] = "dummy"
import pygame
pygame.init()
surface = pygame.display.set_mode((640, 480))
try:
    for q in group:
        m.draw_icon(surface, q, 10, 10, 30)
    drew = True
except Exception as exc:
    drew = False
    print("     %s" % exc)
check(drew, "pad and keyboard icons both render")

print("-- a claimed port is held for that controller across a replug --")
p0 = pad(0, "Nintendo Co., Ltd. Pro Controller")
p1 = pad(1, "Xbox Wireless Controller")
p0.slot, p1.slot = 0, 3
text = override_text([p0, p1], 8)
check('input_player1_reserved_device = "Nintendo Co., Ltd. Pro Controller"' in text,
      "player 1 reserved for the Pro Controller")
# "Reserved" (2), not "preferred" (1). Preferred is a suggestion that
# autoconfiguration may ignore, and the picker's whole job is deciding who
# plays -- a port that the picker gave to one controller and RetroArch gave
# to another leaves the person who claimed it driving nothing.
check('input_player1_device_reservation_type = "2"' in text,
      "and marked reserved, which is binding")
check('input_player1_device_reservation_type = "1"' not in text,
      "not merely preferred")
check('input_player4_reserved_device = "Xbox Wireless Controller"' in text,
      "player 4 reserved for the Xbox pad")

print("-- ports nobody claimed reserve nothing --")
check('input_player2_reserved_device = ""' in text, "player 2 has no reservation")
check('input_player2_device_reservation_type = "0"' in text, "and type none")
check(text.count("_reserved_device") == 8, "one line per port, got %d"
      % text.count("_reserved_device"))

print("-- a keyboard reserves no joypad port --")
kb2 = pad(None, "USB Keyboard", "kbd")
p0.slot, kb2.slot = 0, 1
text = override_text([p0, kb2], 4)
check('input_player2_reserved_device = ""' in text,
      "the keyboard's port reserves no device")

print("-- binds come from the config, not from a copy kept here --")
open(cfg, "w").write('input_player1_a = "comma"\n')
binds = m.keyboard_binds()
check(binds["a"] == "comma", "read A from the config, got %r" % binds["a"])
check(binds["start"] == "enter", "and fell back for the rest, got %r"
      % binds["start"])

import shutil
shutil.rmtree(tmp)
print()
print("FAILURES: %d" % len(fails))
sys.exit(1 if fails else 0)
