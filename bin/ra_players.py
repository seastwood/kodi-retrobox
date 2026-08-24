#!/usr/bin/env python3
"""Controller-to-player picker shown before RetroArch launches.

Each physical pad moves its own cursor with left/right, claims a slot with its
confirm button, releases it with the back button, and any claimed pad presses
Start to launch. Which physical button that is comes from RetroArch's own
autoconfig profile for the pad rather than from a fixed evdev code -- see
pad_controls().

RetroArch's udev joypad driver indexes pads by their /dev/input/eventN node
(it logs "Pad #0 (/dev/input/event7)"), so enumerating the same evdev devices
in the same order yields the indices to write into
input_playerN_joypad_index.
"""

import socket
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time

import evdev
import pygame

MAX_PLAYERS = 4                  # slots for an ordinary session
MAX_PLAYERS_BIG = 8              # ... and once there are more devices than that
RETROARCH = "/usr/bin/retroarch"
# Repairs retroarch.cfg if a previous exit wrote something that cannot start.
GUARD = os.path.expanduser("~/.local/bin/ra_guard.py")
KODI_SEND = "/usr/bin/kodi-send"
# Everything RetroArch said on the last launch. The Kodi plugin throws the
# child's output away, so without this a failure leaves no trace anywhere.
LAUNCH_LOG = os.path.expanduser("~/.local/state/retroarch/last-launch.log")
# What the screen blanking was set to before a game turned it off. Written to
# disk because a `finally` does not run when the process is killed outright,
# and the screen would then never blank again.
SAVER_STATE = os.path.expanduser("~/.local/state/retroarch/screensaver.json")
# RetroArch quits when Start is held for two seconds (HOLD_BTN_DELAY_SEC) and
# shows nothing at all while it happens, so a game about to close looks exactly
# like one that has stopped responding.
#
# RetroArch's own SHOW_MSG is no good for this: it pushes onto a message
# *queue*, each entry shown for a fixed three seconds, so a countdown became a
# stack of notifications playing one after another and "cancelled" arrived
# several seconds after letting go. This draws its own bar instead.
HOLDBAR = os.path.expanduser("~/.local/bin/ra_holdbar.py")
HOLD_SECONDS = 2.0               # what RetroArch itself waits for
HOLD_GRACE = 0.45                # Start is an ordinary in-game button: draw
                                 # nothing until the hold is clearly deliberate
RA_CFG = os.path.expanduser("~/.config/retroarch/retroarch.cfg")
PIXEL_FONT = os.path.expanduser("~/.local/share/fonts/PressStart2P.ttf")

# 8-bit palette, matching the Kodi front end
BG = (16, 14, 40)
BG2 = (28, 22, 66)
MAGENTA = (255, 62, 165)
CYAN = (70, 232, 244)
YELLOW = (255, 212, 71)
DIM = (122, 111, 192)
WHITE = (240, 238, 255)
GREEN = (74, 224, 122)

# One per player slot, distinct at a glance across a room and distinct from
# the slot borders (DIM / CYAN / GREEN) so an icon never blends into its box.
PLAYER_COLORS = [
    (255, 62, 165),      # magenta
    (70, 232, 244),      # cyan
    (255, 212, 71),      # yellow
    (74, 224, 122),      # green
    (255, 138, 60),      # orange
    (170, 120, 255),     # violet
    (255, 255, 255),     # white
    (120, 255, 205),     # mint
]

# evdev button codes -> logical action (xpad and BT layouts both covered)
BTN_A = {evdev.ecodes.BTN_SOUTH, evdev.ecodes.BTN_A}
BTN_B = {evdev.ecodes.BTN_EAST, evdev.ecodes.BTN_B}
BTN_START = {evdev.ecodes.BTN_START}
DEADZONE = 12000

# A device that reports the whole alphabet is a keyboard. The media and power
# keys of the same keyboard register as their own evdev nodes and would
# otherwise be counted as extra players; they carry no letters, so this is what
# separates one physical keyboard from its three nodes.
ALPHABET = set(getattr(evdev.ecodes, "KEY_" + c)
               for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ")

# Keyboard equivalents of the pad actions, matching RetroArch's own defaults
# (a = x, b = z, start = enter) so the keys are the ones already in muscle
# memory, with the obvious alternatives accepted as well.
KBD_CLAIM = {evdev.ecodes.KEY_X, evdev.ecodes.KEY_SPACE}
KBD_RELEASE = {evdev.ecodes.KEY_Z, evdev.ecodes.KEY_BACKSPACE}
KBD_START = {evdev.ecodes.KEY_ENTER, evdev.ecodes.KEY_KPENTER}
KBD_MOVE = {evdev.ecodes.KEY_LEFT: -1, evdev.ecodes.KEY_RIGHT: 1}
KBD_ROW = {evdev.ecodes.KEY_UP: -1, evdev.ecodes.KEY_DOWN: 1}

# The buttons a keyboard player needs bound, in RetroArch's naming.
KBD_BINDS = ("a", "b", "x", "y", "up", "down", "left", "right",
             "start", "select", "l", "r")
DEFAULT_KBD = {"a": "x", "b": "z", "x": "s", "y": "a",
               "up": "up", "down": "down", "left": "left", "right": "right",
               "start": "enter", "select": "rshift", "l": "q", "r": "w"}


def joystick_devices():
    """Joystick evdev nodes, ordered the way RetroArch's udev driver sees them."""
    found = []
    for path in evdev.list_devices():
        try:
            dev = evdev.InputDevice(path)
        except OSError:
            continue
        caps = dev.capabilities(absinfo=False)
        keys = set(caps.get(evdev.ecodes.EV_KEY, []))
        abss = set(caps.get(evdev.ecodes.EV_ABS, []))
        # A joystick has gamepad buttons and at least a main stick
        if (keys & (BTN_A | BTN_B)) and evdev.ecodes.ABS_X in abss:
            num = int("".join(c for c in os.path.basename(path) if c.isdigit()) or -1)
            found.append((num, path, dev))
        else:
            dev.close()
    found.sort(key=lambda t: t[0])
    return [(i, path, dev) for i, (num, path, dev) in enumerate(found)]


def keyboard_devices():
    """Real keyboards, one per physical device."""
    found = []
    for path in evdev.list_devices():
        try:
            dev = evdev.InputDevice(path)
        except OSError:
            continue
        keys = set(dev.capabilities(absinfo=False).get(evdev.ecodes.EV_KEY, []))
        # JoyShockMapper synthesises a keyboard from a pad that is itself in
        # the list; counting both would make one player look like two.
        if ALPHABET.issubset(keys) and not dev.name.startswith("JoyShockMapper"):
            num = int("".join(c for c in os.path.basename(path) if c.isdigit()) or -1)
            found.append((num, path, dev))
        else:
            dev.close()
    found.sort(key=lambda t: t[0])
    return found


def input_devices():
    """Everything a player could hold: pads first, then keyboards.

    Pads keep the joypad indices RetroArch's udev driver assigns; keyboards
    have no joypad index at all, which is why they carry None.
    """
    out = [("pad", index, path, dev)
           for index, path, dev in joystick_devices()]
    out += [("kbd", None, path, dev)
            for _num, path, dev in keyboard_devices()]
    return out


def player_slots(pads, cap=None):
    """How many slots to show. More devices than the usual four means someone
    is setting up a party, so open all eight -- but never offer more slots
    than the game itself can use."""
    slots = MAX_PLAYERS_BIG if len(pads) > MAX_PLAYERS else MAX_PLAYERS
    if cap:
        slots = max(1, min(slots, cap))
    return slots


def needs_picker(joypads, cap):
    """Whether there is anything worth asking before the game starts.

    No pads at all means a keyboard on its own, which is single player and
    already covered by the normal config. One controller on a one-player game
    means the only possible answer has already been given, and a console would
    simply start the game.
    """
    if joypads == 0:
        return False
    return not (cap == 1 and joypads == 1)


def guard_config():
    """Repair retroarch.cfg before anything tries to start with a broken one."""
    if not os.path.exists(GUARD):
        return
    try:
        subprocess.run([GUARD], timeout=15, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        pass


# What RetroArch says when it cannot start, and what that means to a person on
# a sofa. Checked in order, most specific first.
FAILURES = [
    ("Unable to open CD BIOS", "Missing BIOS file"),
    ("Failed to open libretro core", "The emulator core is missing"),
    ("Failed to load content", "This game would not load"),
    ("Could not find any next driver", "No working video driver"),
    ("Failed to initialize video driver", "No working video driver"),
    ("Failed to initialize system", "The emulator core would not start"),
]


def diagnose(path, code, seconds):
    """Why a launch failed, in words, or None if it looks like a normal run.

    A game that ran for a while and exited is somebody quitting, whatever the
    exit code -- only a launch that dies quickly is a failure worth reporting.
    """
    if seconds > 30 and code in (0, 1):
        return None
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            log = handle.read()[-20000:]
    except OSError:
        log = ""
    for marker, message in FAILURES:
        if marker not in log:
            continue
        # The log prints the exact path it tried, which is the answer.
        for line in log.splitlines():
            if marker in line and '"' in line:
                name = line.rsplit('"', 2)[-2]
                if name and "/" in name:
                    return "%s: %s" % (message, os.path.basename(name))
                break
        return message
    if code != 0 and seconds < 30:
        return "RetroArch stopped straight away (code %d)" % code
    return None


def notify(title, message):
    """Put it on the television. Kodi is what the player is looking at."""
    if not os.path.exists(KODI_SEND):
        return
    # Kodi's builtins split their arguments on commas.
    clean = message.replace(",", " ").replace('"', "")
    try:
        subprocess.run([KODI_SEND, "--host=127.0.0.1",
                        "--action=Notification(%s,%s,12000)" % (title, clean)],
                       timeout=10, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        pass


def xset(args):
    env = dict(os.environ)
    env.setdefault("DISPLAY", ":0")
    try:
        done = subprocess.run(["xset"] + list(args), env=env, timeout=10,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout.decode("utf-8", "replace")


def screensaver_state():
    """(blank timeout, cycle, dpms standby/suspend/off, dpms enabled) or None.

    Read before a game so it can be put back exactly afterwards rather than
    left on some guessed default.
    """
    text = xset(["q"])
    if not text:
        return None
    blank = re.search(r"timeout:\s*(\d+)\s+cycle:\s*(\d+)", text)
    dpms = re.search(r"Standby:\s*(\d+)\s+Suspend:\s*(\d+)\s+Off:\s*(\d+)", text)
    if not (blank and dpms):
        return None
    return (blank.groups(), dpms.groups(), "DPMS is Enabled" in text)


def restore_stale_state():
    """Put back a screensaver setting a killed run never restored.

    A SIGTERM -- `timeout`, a pkill, a shutdown -- ends the process without
    running any `finally`, so the previous game can have left blanking off
    forever. Whatever is on disk here was never put back, so put it back now.
    """
    try:
        with open(SAVER_STATE) as handle:
            state = json.load(handle)
    except (OSError, ValueError):
        return
    try:
        restore_screen((tuple(state[0]), tuple(state[1]), state[2]))
    except (TypeError, IndexError, KeyError):
        pass
    try:
        os.unlink(SAVER_STATE)
    except OSError:
        pass


def hold_screen_awake(state):
    """Stop X blanking the screen for as long as a game is running.

    X blanks on its own idle timer, and **gamepad input never resets it**:
    joysticks are not X input devices, so a pad-only session goes black in the
    middle of a game, and a paused one goes black sooner. Kodi looks after this
    for itself, so only the game needs covering -- and the previous timers go
    back afterwards, so the television still sleeps when nobody is playing.
    """
    if state is None:
        return
    try:
        os.makedirs(os.path.dirname(SAVER_STATE), exist_ok=True)
        with open(SAVER_STATE, "w") as handle:
            json.dump(state, handle)
    except OSError:
        pass
    xset(["s", "off"])
    xset(["-dpms"])


def restore_screen(state):
    if state is None:
        return
    (blank, cycle), (standby, suspend, off), enabled = state
    xset(["s", str(blank), str(cycle)])
    xset(["dpms", str(standby), str(suspend), str(off)])
    if not enabled:
        xset(["-dpms"])
    try:
        os.unlink(SAVER_STATE)
    except OSError:
        pass


def hold_fraction(elapsed):
    """How far along the hold is, or None while it is still too early to say.

    Measured from zero rather than from the grace point, so the bar appears
    already part-filled and keeps moving at a steady rate -- the same speed the
    whole way is what makes it read as a countdown rather than a glitch.
    """
    if elapsed < HOLD_GRACE:
        return None
    return max(0.0, min(1.0, elapsed / HOLD_SECONDS))


class HoldBar:
    """The on-screen bar, in its own process. Never fatal: if it cannot start,
    holding Start still quits exactly as before, just without the feedback."""

    def __init__(self):
        self.proc = None
        try:
            self.proc = subprocess.Popen(
                [HOLDBAR], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL)
        except OSError:
            self.proc = None

    def _write(self, line):
        if self.proc is None or self.proc.stdin is None:
            return
        try:
            self.proc.stdin.write((line + "\n").encode())
            self.proc.stdin.flush()
        except (OSError, ValueError):
            self.proc = None

    def show(self, fraction):
        self._write("%.4f" % fraction)

    def hide(self):
        self._write("hide")

    def close(self):
        if self.proc is None:
            return
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.wait(timeout=3)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            try:
                self.proc.kill()
            except OSError:
                pass
        self.proc = None


def netcmd_port():
    """RetroArch's command port, from its own config."""
    try:
        with open(RA_CFG) as handle:
            for line in handle:
                if line.strip().startswith("network_cmd_port"):
                    return int(line.split("=", 1)[1].strip().strip('"'))
    except (OSError, ValueError):
        pass
    return 55355


def send_quit():
    """Ask RetroArch to quit, over the command interface it already exposes.

    RetroArch's own hold-Start combo only listens to player 1. With two pads
    attached -- two identical controllers over USB/IP here -- holding Start on
    the second one filled the bar to the end and then nothing happened, because
    the bar watches every pad and the combo does not. Quitting from here makes
    the bar mean what it shows, whichever pad is holding it.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1)
        sock.sendto(b"QUIT", ("127.0.0.1", netcmd_port()))
        sock.close()
        return True
    except OSError:
        return False


def watch_hold_to_exit(stop, bar=None):
    """Narrate the hold-to-exit while a game is running.

    RetroArch does not grab the pads exclusively, so this reads them alongside
    it; and which button is Start comes from the same per-pad map the picker
    uses, because on a PowerA Switch pad Start is BTN_TR2 and the code called
    BTN_START is something else entirely.
    """
    pads = []
    for kind, _index, _path, dev in input_devices():
        starts = set()
        if kind == "pad":
            btn, _labels = pad_controls(dev)
            starts = {code for code, action in btn.items() if action == "start"}
        if starts:
            pads.append((dev, starts))
        else:
            dev.close()
    if not pads:
        return
    if bar is None:
        bar = HoldBar()
    held_since = None
    showing = False
    quit_sent = False
    try:
        while not stop.is_set():
            for dev, starts in pads:
                try:
                    event = dev.read_one()
                except OSError:
                    event = None
                while event is not None:
                    if (event.type == evdev.ecodes.EV_KEY
                            and event.code in starts):
                        if event.value == 1:
                            held_since, = (time.time(),)
                        elif event.value == 0:
                            if showing:
                                bar.hide()
                                showing = False
                            held_since = None
                            quit_sent = False
                    try:
                        event = dev.read_one()
                    except OSError:
                        event = None
            if held_since is not None:
                fraction = hold_fraction(time.time() - held_since)
                if fraction is not None:
                    bar.show(fraction)
                    showing = True
                    if fraction >= 1.0 and not quit_sent:
                        quit_sent = send_quit()
            stop.wait(0.03)
    finally:
        bar.hide()
        bar.close()
        for dev, _starts in pads:
            try:
                dev.close()
            except OSError:
                pass


def run_retroarch(args, override=None, shader=None):
    """Start the game and stay alive long enough to see whether it worked.

    This used to be an os.execv. Nothing then watched the launch, and the Kodi
    plugin sends the child's output to /dev/null, so a game that could not
    start showed absolutely nothing on screen -- which is how a missing Sega CD
    BIOS presented for days.
    """
    cmd = [RETROARCH] + (["--appendconfig", override] if override else [])
    # Setting video_shader in a config does nothing: RetroArch does not read it
    # at startup and logs "Stock GLSL shaders will be used". --set-shader is
    # the documented route, and an empty argument is how to say "no filter",
    # which is a real answer for a handheld.
    if shader is not None:
        cmd += ["--set-shader", shader]
    cmd += args
    os.makedirs(os.path.dirname(LAUNCH_LOG), exist_ok=True)
    started = time.time()
    saver = screensaver_state()
    hold_screen_awake(saver)
    # Being killed must still put the screen back, and a `finally` will not
    # run for SIGTERM unless it is turned into an ordinary exception.
    def _bail(_signum, _frame):
        restore_screen(saver)
        os._exit(1)
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        try:
            signal.signal(sig, _bail)
        except (ValueError, OSError):
            pass
    stop = threading.Event()
    watcher = threading.Thread(target=watch_hold_to_exit, args=(stop,),
                               daemon=True)
    watcher.start()
    try:
        with open(LAUNCH_LOG, "w") as log:
            code = subprocess.Popen(cmd, stdout=log,
                                    stderr=subprocess.STDOUT).wait()
    except OSError as exc:
        notify("Could not start the game", str(exc))
        return 1
    finally:
        stop.set()
        restore_screen(saver)
    reason = diagnose(LAUNCH_LOG, code, time.time() - started)
    if reason:
        notify("Could not start the game", reason)
        return 1
    return 0


def assign_colors(pads):
    """Give any pad without a colour the lowest one nobody is using.

    Assigned on arrival and never reshuffled, so unplugging one controller
    does not change the colour of everyone else's mid-session.
    """
    taken = set(p.color_index for p in pads if p.color_index is not None)
    for p in pads:
        if p.color_index is not None:
            continue
        for i in range(len(PLAYER_COLORS)):
            if i not in taken:
                p.color_index = i
                taken.add(i)
                break
        else:
            p.color_index = 0
    return pads


def draw_pad_icon(screen, color, x, y, size):
    """A small gamepad: body, two grips, d-pad and buttons."""
    body = pygame.Rect(x, y + size // 5, size, size * 3 // 5)
    pygame.draw.rect(screen, color, body, border_radius=size // 5)
    pygame.draw.circle(screen, color, (x + size // 6, y + size * 4 // 5), size // 5)
    pygame.draw.circle(screen, color, (x + size * 5 // 6, y + size * 4 // 5), size // 5)
    dark = tuple(c // 4 for c in color)
    cx, cy = x + size // 3, y + size // 2
    pygame.draw.rect(screen, dark, (cx - size // 8, cy - size // 24,
                                    size // 4, size // 12))
    pygame.draw.rect(screen, dark, (cx - size // 24, cy - size // 8,
                                    size // 12, size // 4))
    pygame.draw.circle(screen, dark, (x + size * 2 // 3, cy), size // 12)
    pygame.draw.circle(screen, dark, (x + size * 5 // 6, cy), size // 12)


def draw_kbd_icon(screen, color, x, y, size):
    """A small keyboard: a body with three rows of keys and a space bar."""
    body = pygame.Rect(x, y + size // 4, size, size // 2)
    pygame.draw.rect(screen, color, body, border_radius=size // 10)
    dark = tuple(c // 4 for c in color)
    key = max(2, size // 12)
    for row in range(2):
        for col in range(4):
            pygame.draw.rect(screen, dark,
                             (x + size // 10 + col * (key + key // 2),
                              y + size // 3 + row * (key + key // 3), key, key))
    pygame.draw.rect(screen, dark,
                     (x + size // 4, y + size // 4 + size // 3,
                      size // 2, max(2, key // 2)))


def draw_icon(screen, p, x, y, size):
    color = PLAYER_COLORS[(p.color_index or 0) % len(PLAYER_COLORS)]
    if p.kind == "kbd":
        draw_kbd_icon(screen, color, x, y, size)
    else:
        draw_pad_icon(screen, color, x, y, size)


def slot_rows(slots):
    """(rows, slots per row) for a board of this size."""
    rows = 1 if slots <= MAX_PLAYERS else 2
    return rows, (slots + rows - 1) // rows


def claim(p, pads):
    """Take the slot under the cursor. Returns a message if it cannot."""
    if any(q.slot == p.cursor for q in pads):
        return "SLOT TAKEN"
    if p.kind == "kbd" and any(q.kind == "kbd" and q.slot is not None
                               for q in pads):
        # RetroArch cannot tell two keyboards apart -- they arrive as one
        # input -- so a second keyboard player would just be the first again.
        return "ONLY ONE KEYBOARD CAN PLAY"
    p.slot = p.cursor
    return None


def handle_event(p, event, pads, slots):
    """Apply one evdev event from one device.

    Returns (action, message), where action is None, "launch" or "cancel".
    """
    _rows, per_row = slot_rows(slots)
    if p.kind == "kbd":
        if event.type != evdev.ecodes.EV_KEY or event.value != 1:
            return False, None
        if event.code in KBD_CLAIM and p.slot is None:
            return None, claim(p, pads)
        if event.code in KBD_RELEASE:
            if p.slot is not None:
                p.cursor, p.slot = p.slot, None
            elif not any(q.slot is not None for q in pads):
                return "cancel", None
        elif event.code in KBD_START:
            if any(q.slot is not None for q in pads):
                return "launch", None
        elif event.code in KBD_MOVE and p.slot is None:
            p.cursor = max(0, min(slots - 1, p.cursor + KBD_MOVE[event.code]))
        elif event.code in KBD_ROW and p.slot is None:
            p.cursor = max(0, min(slots - 1,
                                  p.cursor + KBD_ROW[event.code] * per_row))
        return None, None

    if event.type == evdev.ecodes.EV_KEY and event.value == 1:
        action = p.btn.get(event.code)
        if action == "confirm" and p.slot is None:
            return None, claim(p, pads)
        if action == "back":
            if p.slot is not None:
                p.cursor, p.slot = p.slot, None
            elif not any(q.slot is not None for q in pads):
                # Nothing claimed by anyone, so back leaves the screen -- the
                # same button that backs out of a claim backs out of the
                # picker. Guarded on the board being empty so one player
                # cannot cancel the launch out from under the others.
                return "cancel", None
        elif action == "start":
            if any(q.slot is not None for q in pads):
                return "launch", None
        elif action in ("left", "right", "up", "down") and p.slot is None:
            # A d-pad is a hat on most pads and read from EV_ABS below, but on
            # plenty of generic ones it is four ordinary buttons, and those
            # pads could not move the cursor at all before.
            step = {"left": -1, "right": 1}.get(action, 0)
            step += {"up": -1, "down": 1}.get(action, 0) * per_row
            p.cursor = max(0, min(slots - 1, p.cursor + step))
    elif event.type == evdev.ecodes.EV_ABS:
        move = row = 0
        if event.code == evdev.ecodes.ABS_HAT0X:
            move = event.value
        elif event.code == evdev.ecodes.ABS_X:
            if event.value < -DEADZONE:
                move = -1
            elif event.value > DEADZONE:
                move = 1
        elif event.code == evdev.ecodes.ABS_HAT0Y:
            row = event.value
        elif event.code == evdev.ecodes.ABS_Y:
            if event.value < -DEADZONE:
                row = -1
            elif event.value > DEADZONE:
                row = 1
        step = move + row * per_row
        if step and p.axis_latch != (move or row) and p.slot is None:
            p.cursor = max(0, min(slots - 1, p.cursor + step))
        if event.code in (evdev.ecodes.ABS_HAT0X, evdev.ecodes.ABS_X,
                          evdev.ecodes.ABS_HAT0Y, evdev.ecodes.ABS_Y):
            p.axis_latch = move or row
    return None, None


def keyboard_binds():
    """Player 1's keyboard keys as configured, so a keyboard player uses the
    layout already set up rather than one invented here."""
    binds = dict(DEFAULT_KBD)
    try:
        for line in open(RA_CFG):
            if not line.startswith("input_player1_"):
                continue
            key, _, value = line.partition("=")
            name = key.strip()[len("input_player1_"):]
            if name in binds:
                binds[name] = value.strip().strip('"')
    except OSError:
        pass
    return binds


# --- what each pad calls its buttons -----------------------------------------

# Fixed evdev codes cannot identify a button. The kernel's own gamepad names
# disagree between drivers (xpad reports the left face button as BTN_X, which
# the positional naming calls BTN_NORTH), and a generic HID pad gets no naming
# at all -- hid-input just assigns BTN_A + n in report order, so its twelfth
# button becomes the code called BTN_START even when it is the right stick
# click. RetroArch ships ~400 udev profiles that say what each button really
# is; they are the profiles the game itself will use, so reading them keeps
# this screen and the game in agreement as well as making it correct.
AUTOCONFIG_DIRS = (os.path.expanduser("~/.config/retroarch/autoconfig"),
                   "/usr/share/libretro/autoconfig")
UDEV_NUM_BUTTONS = 64            # udev_joypad.c's own cap

# Used when no profile matches. These are what a modern driver reports anyway,
# so this is the current behaviour kept as a floor.
FALLBACK_BTN = {evdev.ecodes.BTN_SOUTH: "confirm",
                evdev.ecodes.BTN_EAST: "back",
                evdev.ecodes.BTN_START: "start",
                evdev.ecodes.BTN_SELECT: "select"}
FALLBACK_LABELS = {"confirm": "A", "back": "B", "start": "START"}

# Printed on the pad rather than written in the profile.
DISPLAY_NAMES = {"plus": "+", "minus": "-"}

_PROFILES = None


def udev_button_index(keys):
    """evdev key code -> the button number RetroArch's udev driver gives it.

    A profile records button *numbers*, so they have to be counted the way
    udev_joypad.c counts them: four passes, arrow keys first and the BTN_
    range only second. It is not a plain ascending scan, and under any other
    order every number in every profile is off.
    """
    keys = set(keys)
    order = []
    for lo, hi in ((evdev.ecodes.KEY_UP, evdev.ecodes.KEY_DOWN + 1),
                   (evdev.ecodes.BTN_MISC, evdev.ecodes.KEY_MAX),
                   (0, evdev.ecodes.KEY_UP),
                   (evdev.ecodes.KEY_DOWN + 1, evdev.ecodes.BTN_MISC)):
        order += sorted(k for k in keys if lo <= k < hi)
    return {code: i for i, code in enumerate(order[:UDEV_NUM_BUTTONS])}


def _parse_profile(path):
    out = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                key, sep, value = line.partition("=")
                if sep:
                    out[key.strip()] = value.strip().strip('"')
    except OSError:
        return None
    return out


def autoconfig_dirs():
    """Every directory a profile might be in, one level deep.

    RetroArch files these by input driver -- `autoconfig/udev/Some Pad.cfg` --
    so listing only `autoconfig` finds nothing a user ever installed. All 440
    profiles on this machine live in the `udev` subdirectory, and none of them
    were being read: the picker fell through to matching by vendor and product
    id, where a stock profile that happens to share an Xbox 360's ids answered
    for a completely different pad. `_parse_profile` already refuses anything
    that is not a udev profile, so scanning the subdirectories is safe.
    """
    found = []
    for base in AUTOCONFIG_DIRS:
        found.append(base)
        try:
            found += [os.path.join(base, name) for name in sorted(os.listdir(base))
                      if os.path.isdir(os.path.join(base, name))]
        except OSError:
            continue
    return found


def profile_index():
    """Every autoconfig profile, indexed by device name and by vendor/product.

    Built once and kept: rescan() runs twice a second, and only a device that
    was not there before is ever looked up.
    """
    global _PROFILES
    if _PROFILES is not None:
        return _PROFILES
    by_name, by_id = {}, {}
    for d in autoconfig_dirs():
        try:
            files = sorted(os.listdir(d))
        except OSError:
            continue
        for fn in files:
            if not fn.endswith(".cfg"):
                continue
            prof = _parse_profile(os.path.join(d, fn))
            # udev profiles only. A dinput or xinput profile numbers a
            # different set of buttons in a different order, so borrowing one
            # here would be worse than having no profile at all.
            if not prof or prof.get("input_driver") != "udev":
                continue
            for key, value in prof.items():
                if key.startswith("input_device") and value:
                    by_name.setdefault(value.lower(), prof)
            try:
                ids = (int(prof["input_vendor_id"]), int(prof["input_product_id"]))
            except (KeyError, ValueError):
                continue
            if ids != (0, 0):
                by_id.setdefault(ids, prof)
    _PROFILES = (by_name, by_id)
    return _PROFILES


def find_profile(dev):
    """This pad's profile: by name the way RetroArch matches it, then by
    vendor/product ids -- Sunshine's virtual pad invents a name of its own but
    carries the ids of the controller it stands in for."""
    by_name, by_id = profile_index()
    prof = by_name.get(getattr(dev, "name", "").lower())
    if prof is not None:
        return prof
    info = getattr(dev, "info", None)
    if info is None:
        return None
    return by_id.get((info.vendor, info.product))


def pad_controls(dev):
    """(evdev code -> action, action -> printed label) for one pad.

    Confirm is chosen by what is *printed* on the button, not by position:
    RetroArch's "a" is the right-hand face button, which Nintendo prints as A
    and Xbox prints as B. Picking the button labelled A therefore lands on the
    bottom button of an Xbox pad and the right button of a Switch pad -- each
    pad's own convention -- and the one "A = CLAIM" prompt is true on both.
    """
    try:
        keys = dev.capabilities(absinfo=False).get(evdev.ecodes.EV_KEY, [])
        prof = find_profile(dev)
    except (AttributeError, OSError, ValueError):
        prof = None
    if not prof:
        return dict(FALLBACK_BTN), dict(FALLBACK_LABELS)

    code_of = {i: c for c, i in udev_button_index(keys).items()}

    def code(setting):
        # Hats and axes ("h0up", "+1") are not buttons; they are read from
        # EV_ABS and are simply not part of this map.
        try:
            return code_of.get(int(prof.get(setting, "")))
        except ValueError:
            return None

    def label(setting):
        value = prof.get(setting + "_label", "").strip()
        return DISPLAY_NAMES.get(value.lower(), value.upper()) or None

    if prof.get("input_a_btn_label", "").strip().lower() == "a":
        confirm, back = "input_a_btn", "input_b_btn"     # Nintendo layout
    else:
        confirm, back = "input_b_btn", "input_a_btn"     # everyone else

    btn, labels = {}, {}
    for action, setting in (("confirm", confirm), ("back", back),
                            ("start", "input_start_btn"),
                            ("select", "input_select_btn"),
                            ("up", "input_up_btn"), ("down", "input_down_btn"),
                            ("left", "input_left_btn"),
                            ("right", "input_right_btn")):
        found = code(setting)
        if found is not None:
            btn[found] = action
        text = label(setting)
        if text:
            labels[action] = text
    for action, text in FALLBACK_LABELS.items():
        labels.setdefault(action, text)
    # A profile that names no confirm button would leave the screen with no way
    # forward, so fill in a missing action positionally. Only a missing one --
    # adding BTN_START back on a pad whose profile put start elsewhere is
    # exactly the bug the profiles are here to fix.
    missing = set(FALLBACK_BTN.values()) - set(btn.values())
    for fallback_code, action in FALLBACK_BTN.items():
        if action in missing and fallback_code not in btn:
            btn[fallback_code] = action
    # Confirm is chosen by what is printed on the button, and a Mega Drive pad
    # prints A on the *west* one -- which is where fourth-player's on-screen
    # controller puts it too. So an upper face button with nothing else to do
    # becomes a second way to claim a slot. Nothing is taken away: back stays
    # on the east button, and a pad whose profile already uses these keeps it.
    for spare in (evdev.ecodes.BTN_X, evdev.ecodes.BTN_Y):
        if spare in keys and spare not in btn:
            btn[spare] = "confirm"
    return btn, labels


def prompt_labels(pads):
    """The button names to print in the footer. Pads disagree -- an Xbox pad
    confirms with A and a PlayStation pad with Cross -- and one line cannot
    name both, so the commonest label among the pads present wins."""
    out = {}
    for action, generic in FALLBACK_LABELS.items():
        seen = [p.labels.get(action) for p in pads
                if p.kind == "pad" and p.labels.get(action)]
        out[action] = max(sorted(set(seen)), key=seen.count) if seen else generic
    return out


class Pad:
    def __init__(self, index, path, dev, kind="pad", cursor=0):
        self.kind = kind             # "pad" or "kbd"
        self.index = index           # RetroArch joypad index, None for a keyboard
        self.path = path
        self.dev = dev
        self.name = dev.name
        self.cursor = cursor
        self.slot = None             # claimed player slot (0-based)
        self.axis_latch = 0          # debounce for stick/dpad movement
        self.color_index = None      # set by assign_colors, then left alone
        # Which physical button does what, for this pad specifically.
        self.btn, self.labels = ({}, {}) if kind == "kbd" else pad_controls(dev)

    def close(self):
        try:
            self.dev.close()
        except OSError:
            pass


def load_fonts():
    """Pixel font to match the Kodi front end, falling back if it is missing."""
    def f(size):
        if os.path.exists(PIXEL_FONT):
            return pygame.font.Font(PIXEL_FONT, size)
        return pygame.font.Font(None, int(size * 2.1))
    return {"big": f(44), "small": f(20), "tiny": f(13)}


def draw(screen, fonts, pads, message, slots):
    w, h = screen.get_size()
    screen.fill(BG)
    for i in range(0, h, 4):
        pygame.draw.rect(screen, BG2, (0, i, w, 2))

    title = fonts["big"].render("SELECT YOUR PLAYER", True, YELLOW)
    screen.blit(title, ((w - title.get_width()) // 2, int(h * 0.07)))

    # Four across stays one row; eight wraps to two rather than shrinking
    # into a strip nobody can read from a sofa.
    rows, per_row = slot_rows(slots)
    slot_w = int(w * (0.19 if per_row <= 4 else 0.15))
    slot_h = int(h * (0.34 if rows == 1 else 0.26))
    gap = int(w * 0.03)
    gap_y = int(h * 0.04)
    total = per_row * slot_w + (per_row - 1) * gap
    x0 = (w - total) // 2
    y0 = int(h * (0.24 if rows == 1 else 0.19))
    name_chars = max(6, slot_w // 13 - 1)

    for s_i in range(slots):
        row, col = divmod(s_i, per_row)
        x = x0 + col * (slot_w + gap)
        y = y0 + row * (slot_h + gap_y)
        owner = next((p for p in pads if p.slot == s_i), None)
        hovered = [p for p in pads if p.slot is None and p.cursor == s_i]
        border = GREEN if owner else (CYAN if hovered else DIM)
        pygame.draw.rect(screen, border, (x, y, slot_w, slot_h), 4)

        label = fonts["big"].render("P%d" % (s_i + 1), True, border)
        screen.blit(label, (x + (slot_w - label.get_width()) // 2, y + 18))

        # Laid out upwards from the bottom edge: name, then status, then the
        # icon above it. Sizing the icon off the slot width and the text off
        # the font meant the two silently overlapped at some sizes.
        icon = max(22, min(slot_w // 5, slot_h // 4))
        icon_y = y + slot_h - 92 - icon
        if owner:
            draw_icon(screen, owner, x + (slot_w - icon) // 2, icon_y, icon)
            txt = fonts["small"].render("READY", True, GREEN)
            screen.blit(txt, (x + (slot_w - txt.get_width()) // 2, y + slot_h - 74))
            nt = fonts["tiny"].render(owner.name[:name_chars], True, WHITE)
            screen.blit(nt, (x + (slot_w - nt.get_width()) // 2, y + slot_h - 40))
        elif hovered:
            # Side by side rather than stacked: two controllers hovering the
            # same number have to read as two, which was the whole problem
            # with an unmarked cursor.
            step = icon + 6
            row_w = len(hovered) * step - 6
            ix = x + (slot_w - row_w) // 2
            for q in hovered:
                draw_icon(screen, q, ix, icon_y, icon)
                ix += step
            # Say the key that actually claims, which differs for a keyboard.
            word = "PRESS X" if all(q.kind == "kbd" for q in hovered) else "PRESS A"
            txt = fonts["small"].render(word, True, CYAN)
            screen.blit(txt, (x + (slot_w - txt.get_width()) // 2, y + slot_h - 74))

    bottom = y0 + rows * slot_h + (rows - 1) * gap_y

    # Whoever has not claimed yet, each behind its own colour so a player can
    # find their icon on the board.
    y = bottom + int(h * 0.05)
    free = [p for p in pads if p.slot is None]
    if free:
        icon = 26
        entries = [(q, fonts["tiny"].render(q.name[:12], True, DIM)) for q in free]
        widths = [icon + 6 + text.get_width() for _q, text in entries]
        ix = (w - (sum(widths) + 24 * (len(entries) - 1))) // 2
        for (q, text), width in zip(entries, widths):
            draw_icon(screen, q, ix, y - 6, icon)
            screen.blit(text, (ix + icon + 6, y + 2))
            ix += width + 24
    else:
        ht = fonts["tiny"].render("ALL PADS ASSIGNED", True, DIM)
        screen.blit(ht, ((w - ht.get_width()) // 2, y))

    foot = fonts["small"].render(message, True, MAGENTA)
    screen.blit(foot, ((w - foot.get_width()) // 2, int(h * 0.88)))
    pygame.display.flip()


def write_override(pads, slots):
    """Write a RetroArch config fragment binding claimed devices to ports."""
    claimed = [p for p in pads if p.slot is not None]
    kbd_slot = next((p.slot for p in claimed if p.kind == "kbd"), None)
    # A game may show fewer slots than there are ports; the ports beyond the
    # board still have to be parked, or a stray pad drives a player nobody
    # picked.
    ports = max(slots, MAX_PLAYERS)
    fd, path = tempfile.mkstemp(prefix="ra_players_", suffix=".cfg")
    with os.fdopen(fd, "w") as fh:
        reserved = {}
        for p in sorted((p for p in claimed if p.kind == "pad"),
                        key=lambda p: p.slot):
            fh.write('input_player%d_joypad_index = "%d"\n' % (p.slot + 1, p.index))
            reserved[p.slot] = p.name
        # Park unclaimed ports on an index that cannot exist so a stray pad
        # (or the keyboard-backed port) does not silently take player 1.
        used = {p.slot for p in claimed if p.kind == "pad"}
        for s in range(ports):
            if s not in used:
                fh.write('input_player%d_joypad_index = "99"\n' % (s + 1))
        # Hold each port for the controller that claimed it, so unplugging a
        # pad mid-game and plugging it back in returns it to the same player
        # instead of the first free port. "Preferred" (1) rather than
        # "Reserved" (2) on purpose: if the name ever fails to match, the port
        # still behaves the way it does today rather than staying empty.
        for s in range(ports):
            name = reserved.get(s)
            fh.write('input_player%d_reserved_device = "%s"\n'
                     % (s + 1, name or ""))
            fh.write('input_player%d_device_reservation_type = "%d"\n'
                     % (s + 1, 1 if name else 0))
        if kbd_slot is not None:
            # RetroArch merges every keyboard into one input, so a keyboard
            # player's binds have to live on exactly one port -- and be cleared
            # from the others, or the keyboard would still be driving player 1
            # at the same time.
            binds = keyboard_binds()
            for s in range(ports):
                for name in KBD_BINDS:
                    fh.write('input_player%d_%s = "%s"\n'
                             % (s + 1, name,
                                binds[name] if s == kbd_slot else "nul"))
    return path


def rescan(pads):
    """Re-enumerate pads so devices added or removed mid-screen are handled.

    Sunshine destroys and recreates its virtual gamepad each time a Moonlight
    stream stops and starts, so the device list is not stable while this screen
    is up. Indices are positional, so they are recomputed every pass.
    """
    current = input_devices()
    live_paths = {path for _kind, _index, path, _dev in current}
    by_path = {p.path: p for p in pads}

    # Drop pads whose device disappeared, freeing any slot they held.
    for p in list(pads):
        if p.path not in live_paths:
            p.close()
            pads.remove(p)

    for kind, index, path, dev in current:
        existing = by_path.get(path)
        if existing is not None and existing in pads:
            existing.index = index      # position may have shifted
            dev.close()                 # keep the handle we are already reading
        else:
            pads.append(Pad(index, path, dev, kind))

    # Pads first in joypad order, then keyboards, which have no index to sort on.
    pads.sort(key=lambda p: (p.kind != "pad", p.index if p.index is not None else 0))
    assign_colors(pads)
    return pads


def main():
    args = sys.argv[1:]
    # --max-players is ours, not RetroArch's, so it never reaches the emulator.
    cap = None
    shader = None
    while len(args) >= 2 and args[0] in ("--max-players", "--shader"):
        if args[0] == "--max-players":
            try:
                cap = max(1, int(args[1]))
            except ValueError:
                cap = None
        else:
            # "none" is a real answer, and a different one from saying nothing.
            shader = "" if args[1] == "none" else args[1]
        args = args[2:]
    if not args:
        print("usage: ra_players.py [--max-players N] <retroarch args...>",
              file=sys.stderr)
        return 2

    guard_config()
    restore_stale_state()

    pads_raw = input_devices()
    joypads = [d for d in pads_raw if d[0] == "pad"]
    if not needs_picker(len(joypads), cap):
        for _kind, _index, _path, dev in pads_raw:
            dev.close()
        return run_retroarch(args, shader=shader)

    slots = player_slots(pads_raw, cap)
    pads = [Pad(index, path, dev, kind, cursor=i % slots)
            for i, (kind, index, path, dev) in enumerate(pads_raw)]
    assign_colors(pads)

    os.environ.setdefault("SDL_VIDEODRIVER", "x11")
    pygame.init()
    pygame.mouse.set_visible(False)
    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    pygame.display.set_caption("Select Player")
    fonts = load_fonts()
    clock = pygame.time.Clock()

    launch = False
    cancelled = False
    rescan_tick = 0
    note = ""
    note_ticks = 0
    while not launch and not cancelled:
        rescan_tick += 1
        if rescan_tick >= 30:           # about twice a second at 60fps
            rescan_tick = 0
            rescan(pads)
            # Plugging a fifth device in opens the board out to eight, and
            # unplugging can close it again -- so nothing may be left pointing
            # at a slot that no longer exists.
            slots = player_slots(pads, cap)
            for p in pads:
                if p.cursor >= slots:
                    p.cursor = slots - 1
                if p.slot is not None and p.slot >= slots:
                    p.slot = None
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                cancelled = True
            elif ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                cancelled = True

        for p in pads:
            try:
                event = p.dev.read_one()
            except OSError:
                event = None
            while event is not None:
                action, said = handle_event(p, event, pads, slots)
                if action == "launch":
                    launch = True
                elif action == "cancel":
                    cancelled = True
                if said:
                    note, note_ticks = said, 120
                try:
                    event = p.dev.read_one()
                except OSError:
                    event = None

        ready = sum(1 for p in pads if p.slot is not None)
        kbd = any(p.kind == "kbd" for p in pads)
        lab = prompt_labels(pads)
        claim_btn = lab["confirm"] + ("/X" if kbd else "")
        back_btn = lab["back"] + ("/Z" if kbd else "")
        start_btn = lab["start"] + ("/ENTER" if kbd else "")
        if note_ticks > 0:
            note_ticks -= 1
            msg = note
        elif ready:
            msg = "PRESS %s TO PLAY    %s = RELEASE" % (start_btn, back_btn)
        else:
            # With nobody claimed the back button leaves the screen, so say so
            # here -- without it the only way out is a keyboard's ESC.
            msg = "%s = CLAIM    %s = BACK" % (claim_btn, back_btn)
        draw(screen, fonts, pads, msg, slots)
        clock.tick(60)

    override = write_override(pads, slots) if launch else None
    for p in pads:
        p.close()
    pygame.quit()

    if cancelled:
        return 1

    return run_retroarch(args, override, shader)


if __name__ == "__main__":
    sys.exit(main())
