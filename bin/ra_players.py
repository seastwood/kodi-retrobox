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

import glob
import shutil
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
# Ours, and only ours. See log_line.
PICKER_LOG = os.path.expanduser("~/.local/state/retroarch/ra_players.log")
# Where the config fragments handed to RetroArch are written. Not /tmp: this
# file says which pad is which player, and fourth-player reads it back to tell
# a guest which player they are -- from a service with PrivateTmp=yes, which
# gets a /tmp of its very own and could never see a word of it.
OVERRIDE_DIR = os.path.expanduser("~/.local/state/retroarch/overrides")
OVERRIDE_KEEP = 24 * 3600        # how long a used fragment is worth keeping
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
HOLD_RESCAN_SECONDS = 3.0        # how often to look for a pad that turned up
REPICK_SECONDS = 2.0             # hold Select this long to change players

# RetroArch opens its own menu on a held Select (combo 8), which is the same
# gesture as asking for the player picker and, worse, a way into the whole
# emulator for anybody holding a pad -- including a guest in another house,
# whose entire permitted vocabulary is meant to be "move a gamepad". Turned
# off for every game this launches, so a config that has drifted cannot open
# it again. The menu is still there on a keyboard, where F1 opens it.
NO_PAD_MENU = 'input_menu_toggle_gamepad_combo = "0"\n' 
REPICK = 90                      # run_retroarch: "the players are changing"
RESUME_WAIT = 45                 # how long a relaunched game gets to answer
# Somebody in a browser asking for the same thing. Written by fourth-player,
# which already writes the guest names into this directory, and read here --
# the two programs share files, never code.
REPICK_FLAG = os.path.expanduser("~/.local/state/fourth-player/repick")
STATE_DIR = os.path.expanduser("~/.config/retroarch/states")
# Where a game's own save states are put while one is borrowed to carry the
# game across a restart, and the note saying what to put back if this process
# dies before it can.
STATE_BACKUP = os.path.expanduser("~/.local/state/retroarch/carried")
STATE_MANIFEST = os.path.expanduser("~/.local/state/retroarch/carried.json")
                                 # after the game started -- see watch_hold_to_exit
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


def diagnose(path, code, seconds, asked=False):
    """Why a launch failed, in words, or None if it looks like a normal run.

    A game that ran for a while and exited is somebody quitting, whatever the
    exit code -- only a launch that dies quickly is a failure worth reporting.
    """
    if code < 0 and not asked:
        # Killed by a signal, with nobody having asked it to stop. This used
        # to be filtered out by the "ran for a while, so somebody quit" rule
        # below, which meant a game that fell over after two minutes said
        # nothing at all and looked exactly like a game somebody had finished
        # with. Deaths on the way out of a quit we asked for are still
        # ignored: more than one core here segfaults every time it closes.
        return "The game stopped unexpectedly (signal %d)" % -code
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


def hold_fraction(elapsed, seconds=None):
    """How far along the hold is, or None while it is still too early to say.

    Measured from zero rather than from the grace point, so the bar appears
    already part-filled and keeps moving at a steady rate -- the same speed the
    whole way is what makes it read as a countdown rather than a glitch.
    """
    if elapsed < HOLD_GRACE:
        return None
    return max(0.0, min(1.0, elapsed / (seconds or HOLD_SECONDS)))


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

    def show(self, fraction, caption=""):
        self._write("%.4f %s" % (fraction, caption))

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


# When we last asked a game to close. Some cores fall over on the way out --
# SkyEmu segfaults on every clean exit here -- and a crash during a shutdown
# somebody asked for is not news. A crash nobody asked for is.
QUIT_ASKED = [0.0]


def send_quit():
    """Ask RetroArch to quit, over the command interface it already exposes.

    RetroArch's own hold-Start combo only listens to player 1. With two pads
    attached -- two identical controllers over USB/IP here -- holding Start on
    the second one filled the bar to the end and then nothing happened, because
    the bar watches every pad and the combo does not. Quitting from here makes
    the bar mean what it shows, whichever pad is holding it.
    """
    QUIT_ASKED[0] = time.time()
    return send_command("QUIT")


def send_command(word):
    """Tell RetroArch one thing, and never ask it anything.

    Deliberately write-only. There was a version of this that could wait for a
    reply, used to find out whether a game was ready yet -- and asking that
    question every quarter of a second from the moment the process started
    segfaulted the emulator within seconds. Readiness is read out of the
    game's own log now (wait_for_log), and there is no way to ask from here.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1)
        sock.sendto(word.encode(), ("127.0.0.1", netcmd_port()))
        sock.close()
        return True
    except OSError:
        return False


# What RetroArch writes once its command interface is listening, and what it
# writes when it has taken a state back. Read rather than asked for: see
# wait_for_log.
UP_MARKER = "bringing_up_command_interface"
LOADED_MARKER = "[State] Loading state"


def wait_for_log(marker, deadline, stop=None):
    """Wait for the game to say something, rather than asking it anything.

    Asking was the obvious way and it was badly wrong. Polling GET_STATUS from
    the instant the process started segfaulted RetroArch within seconds --
    measured on this machine, three clean thirty-second runs of the same game
    with no polling against two crashes out of two with it. The probe meant to
    find out whether the game was ready was killing the game.

    Its own log costs it nothing: this process already has the emulator's
    stdout in a file, so waiting on that touches the game not at all. Nothing
    is now sent to a game that has not first said it is listening.
    """
    while time.time() < deadline:
        if stop is not None and stop.is_set():
            return False              # it is gone; waiting is waiting for nothing
        try:
            with open(LAUNCH_LOG, encoding="utf-8", errors="replace") as fh:
                if marker in fh.read():
                    return True
        except OSError:
            pass
        time.sleep(0.25)
    return False


def state_files(rom):
    """Every numbered save state belonging to a game, whichever core wrote it.

    The auto state is left out on purpose: RetroArch rewrites that one itself
    when a game closes, which is what it is for.
    """
    stem = os.path.splitext(os.path.basename(rom))[0]
    pattern = os.path.join(STATE_DIR, "*", glob.escape(stem) + ".state*")
    out = []
    for path in glob.glob(pattern):
        tail = path.rsplit(".state", 1)[-1]
        # "" is slot 0 and "3" is slot 3. ".auto" is not a slot, and ".png" is
        # the thumbnail RetroArch writes beside every state -- which used to
        # count as a state here, so the scan for "the file that moved" could
        # find a picture and call it slot 0.
        if tail == "" or tail.isdigit():
            out.append(path)
    return sorted(out)


def carry_state(rom):
    """Write the running game to a save state, without endangering anyone's.

    Changing players means restarting the emulator, and the only way to bring
    the game along is to ask RetroArch to save -- which it can only do into a
    numbered slot, and the slot it will choose is whichever one the person
    playing was last using. That is somebody's save, possibly hours of it.

    So every one of them is copied out of the way first, and put back the
    moment the new run has read what it needed. The window in which any file on
    disk differs from what the player left there is the couple of seconds when
    no emulator is running at all, and a note on disk means even being killed
    inside that window is recoverable: the next start puts them back.

    Returns the slot to load from, or None if nothing was written.
    """
    before = {f: os.stat(f).st_mtime for f in state_files(rom)}
    saved = []
    try:
        os.makedirs(STATE_BACKUP, exist_ok=True)
        for i, path in enumerate(before):
            backup = os.path.join(STATE_BACKUP, "%d.state" % i)
            shutil.copy2(path, backup)
            saved.append({"original": path, "backup": backup})
    except OSError as exc:
        log_line("could not put the save states out of harm's way: %s" % exc)
        return None
    # Written before the save is asked for, not after: the point of the note is
    # to survive the thing that happens in between.
    try:
        with open(STATE_MANIFEST, "w") as fh:
            json.dump({"rom": rom, "files": saved}, fh)
    except OSError as exc:
        log_line("could not write the note about carried saves: %s" % exc)
        return None

    if not send_command("SAVE_STATE"):
        restore_carried()
        return None
    # Which slot it chose is not something RetroArch will tell us, so it is
    # found the only way available: by looking for the file that moved.
    deadline = time.time() + 5.0
    while time.time() < deadline:
        for path in state_files(rom):
            if path not in before or os.stat(path).st_mtime > before[path]:
                # Written down, because whether this file is somebody's game
                # or a scrap to throw away is not known until the new run has
                # had its chance to read it.
                try:
                    with open(STATE_MANIFEST, "w") as fh:
                        json.dump({"rom": rom, "files": saved,
                                   "carried": path}, fh)
                except OSError:
                    pass
                return state_slot_of(path)
        time.sleep(0.1)
    log_line("asked for a save state and none appeared")
    restore_carried()
    return None


def state_slot_of(path):
    """The slot number a state file belongs to. Slot 0 has no suffix."""
    tail = path.rsplit(".state", 1)[-1]
    try:
        return int(tail)
    except ValueError:
        return 0


def restore_carried(rescue=False):
    """Put back save states borrowed to carry a game across a restart.

    Also run at startup, because the borrowing happens with the emulator
    between lives: a power cut or a pkill in that gap would otherwise leave one
    slot holding an automatic save nobody asked for.
    """
    try:
        with open(STATE_MANIFEST) as fh:
            note = json.load(fh)
    except (OSError, ValueError):
        return
    # Before anything is put back over it: if the new run never read this,
    # it is not a scrap, it is the only copy of where somebody was. An
    # ordinary launch of this game loads the automatic state, so that is
    # where it goes -- starting the game again finds them where they were.
    carried = note.get("carried")
    if rescue and carried and os.path.exists(carried):
        auto = carried.rsplit(".state", 1)[0] + ".state.auto"
        try:
            shutil.copy2(carried, auto)
            # The picture RetroArch writes beside a state, so the menu shows
            # where they were rather than a blank square.
            if os.path.exists(carried + ".png"):
                shutil.copy2(carried + ".png", auto + ".png")
            log_line("the game never came back; kept it as %s"
                     % os.path.basename(auto))
        except OSError as exc:
            log_line("could not keep the carried game: %s" % exc)

    for item in note.get("files", []):
        try:
            shutil.copy2(item["backup"], item["original"])
            os.unlink(item["backup"])
        except (OSError, KeyError, TypeError):
            pass
    # Anything the save wrote that was not there before is ours, and litter.
    kept = {item.get("original") for item in note.get("files", [])}
    for path in state_files(note.get("rom", "")):
        if path in kept:
            continue
        # The thumbnail goes with the state it belongs to; it is not a state
        # itself, so state_files does not list it and it would otherwise be
        # left behind for ever.
        for junk in (path, path + ".png"):
            try:
                os.unlink(junk)
            except OSError:
                pass
    try:
        os.unlink(STATE_MANIFEST)
    except OSError:
        pass


def log_line(message):
    """A line in this program's own log.

    Not the launch log: RetroArch is streaming its stdout into that one at its
    own file offset, so anything appended to the end of it gets overwritten by
    the emulator's next line and the note about what went wrong disappears --
    which is exactly how a failed state load came to leave no trace at all.
    """
    try:
        os.makedirs(os.path.dirname(PICKER_LOG), exist_ok=True)
        with open(PICKER_LOG, "a") as fh:
            fh.write("%s  %s\n"
                     % (time.strftime("%Y-%m-%d %H:%M:%S"), message))
    except OSError:
        pass


def repick_asked():
    """Has anything outside asked for the player picker to come back?"""
    try:
        os.unlink(REPICK_FLAG)
        return True
    except OSError:
        return False


class Repick(threading.Event):
    """A request to put the player picker back over a game already running.

    Carries the two things the next pass needs and cannot work out for itself:
    which save slot the game was parked in, and the config the last run was
    using -- so backing out of the picker puts everybody back exactly where
    they were rather than dropping them into the menu.
    """

    def __init__(self):
        super().__init__()
        self.slot = None
        self.override = None


def start_repick(repick, rom):
    """Put the game somewhere safe, then close it so the picker can come back.

    The order matters: the state has to be written while the emulator is still
    alive to write it, and the flag has to be set before the quit, or the exit
    reads as an ordinary "they finished playing" and nothing comes back.
    """
    slot = carry_state(rom)
    repick.slot = slot
    repick.set()
    if not send_quit():
        # Nothing is going to close, so nothing is going to reopen. Put the
        # borrowed saves back rather than leaving them borrowed for ever.
        repick.clear()
        restore_carried()


def hold_pads(existing):
    """The pads worth watching for the hold-to-exit, and whether any left.

    Rescanned rather than listed once. A controller that arrives after the game
    started is the ordinary case, not an edge one: Sunshine creates its virtual
    pad when a Moonlight client connects, so somebody joining a game already in
    progress had no way to hold Start and close it -- the one thing they need
    before anything else. Enumerating once meant their pad was never read.

    Handles already being read are kept rather than reopened, because reopening
    one loses whatever it had buffered.
    """
    held = {dev.path: entry for entry in existing for dev, _s, _x in [entry]}
    keep, seen = [], set()
    for kind, _index, path, dev in input_devices():
        seen.add(path)
        if path in held:
            dev.close()                   # keep the handle already in use
            keep.append(held[path])
            continue
        starts, selects = set(), set()
        if kind == "pad":
            btn, _labels = pad_controls(dev)
            starts = {code for code, action in btn.items() if action == "start"}
            selects = {code for code, action in btn.items()
                       if action == "select"}
        if starts or selects:
            keep.append((dev, starts, selects))
        else:
            dev.close()
    gone = False
    for path, entry in held.items():
        if path not in seen:
            gone = True
            try:
                entry[0].close()
            except OSError:
                pass
    return keep, gone


def watch_hold_to_exit(stop, bar=None, repick=None, rom=""):
    """Narrate the hold-to-exit while a game is running.

    RetroArch does not grab the pads exclusively, so this reads them alongside
    it; and which button is Start comes from the same per-pad map the picker
    uses, because on a PowerA Switch pad Start is BTN_TR2 and the code called
    BTN_START is something else entirely.
    """
    pads, _ = hold_pads([])
    if bar is None:
        bar = HoldBar()
    # Two holds, watched the same way: Start closes the game, Select brings the
    # player picker back over it. Both are ordinary in-game buttons, so both
    # wait out HOLD_GRACE before they admit to being a hold at all.
    holds = {"start": {"since": None, "done": False,
                       "seconds": HOLD_SECONDS,
                       "caption": "HOLD TO EXIT"},
             # Longer, because Select is an ordinary in-game button on more
             # games than Start is, and interrupting a game by accident costs
             # everybody playing it.
             "select": {"since": None, "done": False,
                        "seconds": REPICK_SECONDS,
                        "caption": "HOLD TO CHANGE PLAYERS"}}
    showing = False
    next_scan = time.time() + HOLD_RESCAN_SECONDS
    next_flag = time.time()
    try:
        while not stop.is_set():
            if time.time() >= next_scan:
                next_scan = time.time() + HOLD_RESCAN_SECONDS
                pads, gone = hold_pads(pads)
                if gone and any(h["since"] for h in holds.values()):
                    # The pad being held may be the one that left, and its
                    # release will never arrive.
                    if showing:
                        bar.hide()
                        showing = False
                    for h in holds.values():
                        h["since"], h["done"] = None, False
            # Somebody asking from a browser, which is the same request without
            # a controller to make it on.
            if repick is not None and time.time() >= next_flag:
                next_flag = time.time() + 0.4
                if repick_asked() and not repick.is_set():
                    start_repick(repick, rom)
            for dev, starts, selects in pads:
                try:
                    event = dev.read_one()
                except OSError:
                    event = None
                while event is not None:
                    which = None
                    if event.type == evdev.ecodes.EV_KEY:
                        if event.code in starts:
                            which = "start"
                        elif event.code in selects and repick is not None:
                            which = "select"
                    if which is not None:
                        if event.value == 1:
                            holds[which]["since"] = time.time()
                        elif event.value == 0:
                            if showing:
                                bar.hide()
                                showing = False
                            holds[which]["since"] = None
                            holds[which]["done"] = False
                    try:
                        event = dev.read_one()
                    except OSError:
                        event = None
            for name, hold in holds.items():
                if hold["since"] is None:
                    continue
                fraction = hold_fraction(time.time() - hold["since"],
                                         hold["seconds"])
                if fraction is None:
                    continue
                bar.show(fraction, hold["caption"])
                showing = True
                if fraction < 1.0 or hold["done"]:
                    continue
                if name == "start":
                    hold["done"] = send_quit()
                elif not repick.is_set():
                    hold["done"] = True
                    bar.hide()
                    showing = False
                    start_repick(repick, rom)
                break
            stop.wait(0.03)
    finally:
        bar.hide()
        bar.close()
        for dev, _starts, _selects in pads:
            try:
                dev.close()
            except OSError:
                pass


def run_retroarch(args, override=None, shader=None, repick=None,
                  load_slot=None):
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
    # Nothing has asked *this* game to stop. Without clearing it, a game
    # relaunched seconds after the picker closed the last one inherits that
    # quit and any crash of its own is written off as somebody else's tidy
    # shutdown -- which is precisely what happened.
    QUIT_ASKED[0] = 0.0
    stop = threading.Event()
    rom = args[-1] if args and not args[-1].startswith("-") else ""
    watcher = threading.Thread(target=watch_hold_to_exit,
                               args=(stop, None, repick, rom), daemon=True)
    watcher.start()
    try:
        with open(LAUNCH_LOG, "w") as log:
            child = subprocess.Popen(cmd, stdout=log,
                                     stderr=subprocess.STDOUT)
            resume = None
            resume_stop = threading.Event()
            if load_slot is not None:
                label = now_playing(args)[0] or ""
                resume = threading.Thread(
                    target=resume_carried,
                    args=(load_slot, label, resume_stop), daemon=True)
                resume.start()
            code = child.wait()
            if resume is not None:
                # This thread is the one that hands the borrowed saves back.
                # It was a daemon left to run for up to forty-five seconds, so
                # a game that died four seconds in took the whole process down
                # with it and the saves stayed borrowed until the next launch
                # happened to notice.
                resume_stop.set()
                resume.join(timeout=20)
    except OSError as exc:
        notify("Could not start the game", str(exc))
        return 1
    finally:
        stop.set()
        restore_screen(saver)
    if repick is not None and repick.is_set():
        # Closed on purpose, to put the picker back over the same game. Not a
        # failure however RetroArch chose to exit.
        return REPICK
    asked = time.time() - QUIT_ASKED[0] < 30
    if code < 0:
        log_line("the game died on signal %d (%s)"
                 % (-code, "on the way out of a quit we asked for" if asked
                    else "nobody asked it to stop"))
    reason = diagnose(LAUNCH_LOG, code, time.time() - started, asked)
    if reason:
        notify("Could not start the game", reason)
        return 1
    return 0


def resume_carried(slot, name="", stop=None):
    """Hand the game back what it was doing, then give everyone their saves.

    The saves go back whatever happens: they belong to whoever made them, and
    leaving an automatic save sitting in one of their slots is the exact thing
    this is all built to avoid.

    The carried game is only thrown away once the log has confirmed the new
    run actually read it. Anything else -- a game that never came up, a game
    that came up and would not take the state, a game that crashed -- keeps
    it, because it is the only copy of where somebody was.
    """
    loaded = False
    try:
        if not wait_for_log(UP_MARKER, time.time() + RESUME_WAIT, stop):
            log_line("%s never came up in %ds; keeping the carried game"
                     % (name or "the game", RESUME_WAIT))
            notify("Could not put the game back",
                   "%s did not start. Your place was kept -- start it again "
                   "from the menu." % (name or "The game"))
            return
        # Listening is not the same as ready for a state: the core is still
        # bringing itself up in its first frames.
        time.sleep(2.0)
        send_command("LOAD_STATE")
        loaded = wait_for_log(LOADED_MARKER, time.time() + 20, stop)
        if not loaded:
            log_line("%s would not take the carried state back" % (name or "the game"))
            notify("Could not put the game back",
                   "%s started, but would not take your place back. It was "
                   "kept -- start it again from the menu."
                   % (name or "The game"))
    finally:
        restore_carried(rescue=not loaded)


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


def other_slots(pads, exclude):
    """The slots somebody other than this pad has claimed."""
    return {q.slot for q in pads if q.slot is not None and q is not exclude}


def step_cursor(p, pads, slots, step):
    """Move a cursor, stepping straight over slots already claimed.

    A claimed slot is not a place another controller can go, so it is not a
    place another controller's cursor should stop. Landing on one and being
    told "SLOT TAKEN" is a dead end the board could simply not have offered.
    """
    if not step:
        return
    taken = other_slots(pads, p)
    # Where it would have landed before any of this: a whole row down from the
    # bottom row still means the last slot, rather than nothing happening.
    target = max(0, min(slots - 1, p.cursor + step))
    if target == p.cursor:
        return
    direction = 1 if step > 0 else -1
    # The slot itself, then onwards in the direction of travel, then back
    # towards where it came from -- so a claimed slot at the edge of the board
    # is stepped over rather than becoming a wall.
    order = [target]
    order += [target + direction * n for n in range(1, slots)]
    order += [target - direction * n for n in range(1, slots)]
    for candidate in order:
        if 0 <= candidate < slots and candidate not in taken:
            p.cursor = candidate
            return


def clear_hovering(pads, slot, slots):
    """Move anybody still pointing at a slot that has just been claimed.

    Without this they sit on somebody else's slot looking like they are about
    to take it, and the only thing pressing confirm can do is refuse.
    """
    taken = {q.slot for q in pads if q.slot is not None}
    for q in pads:
        if q.slot is not None or q.cursor != slot:
            continue
        # The nearest free slot, preferring the one to the right on a tie, so
        # two controllers bumped off the same slot do not both land together.
        for candidate in sorted(range(slots),
                                key=lambda c: (abs(c - slot), -c)):
            if candidate not in taken:
                q.cursor = candidate
                break


def claim(p, pads, slots=None):
    """Take the slot under the cursor. Returns a message if it cannot."""
    if any(q.slot == p.cursor for q in pads):
        return "SLOT TAKEN"
    if p.kind == "kbd" and any(q.kind == "kbd" and q.slot is not None
                               for q in pads):
        # RetroArch cannot tell two keyboards apart -- they arrive as one
        # input -- so a second keyboard player would just be the first again.
        return "ONLY ONE KEYBOARD CAN PLAY"
    p.slot = p.cursor
    if slots:
        clear_hovering(pads, p.slot, slots)
    return None


def handle_event(p, event, pads, slots):
    """Apply one evdev event from one device.

    Returns (action, message), where action is None, "launch" or "cancel".
    """
    _rows, per_row = slot_rows(slots)
    if p.kind == "kbd":
        if event.type != evdev.ecodes.EV_KEY or event.value != 1:
            return False, None
        p.seen = True
        if event.code in KBD_CLAIM and p.slot is None:
            return None, claim(p, pads, slots)
        if event.code in KBD_RELEASE:
            if p.slot is not None:
                p.cursor, p.slot = p.slot, None
            elif not any(q.slot is not None for q in pads):
                return "cancel", None
        elif event.code in KBD_START:
            if p.slot is None:
                return None, "CLAIM A SLOT BEFORE STARTING"
            return "launch", None
        elif event.code in KBD_MOVE and p.slot is None:
            step_cursor(p, pads, slots, KBD_MOVE[event.code])
        elif event.code in KBD_ROW and p.slot is None:
            step_cursor(p, pads, slots, KBD_ROW[event.code] * per_row)
        return None, None

    if (event.type == evdev.ecodes.EV_KEY and event.value == 0
            and p.btn.get(event.code) == "back"):
        p.back_since = None
        return None, None

    if event.type == evdev.ecodes.EV_KEY and event.value == 1:
        action = p.btn.get(event.code)
        p.seen = True
        p.last_press = (p.labels.get(action) or "?", action, event.code)
        if action == "confirm" and p.slot is None:
            return None, claim(p, pads, slots)
        if action == "back":
            p.back_since = time.time()
            if p.slot is not None:
                p.cursor, p.slot = p.slot, None
            elif not any(q.slot is not None for q in pads):
                # Nothing claimed by anyone, so back leaves the screen -- the
                # same button that backs out of a claim backs out of the
                # picker. Guarded on the board being empty so one player
                # cannot cancel the launch out from under the others.
                return "cancel", None
        elif action == "start":
            # Your own claim, not anybody's. Starting the game while not in it
            # was possible before, so one player could launch the moment
            # somebody else claimed -- including out from under a player who
            # was still choosing.
            if p.slot is None:
                return None, ("PRESS %s TO CLAIM A SLOT FIRST"
                              % p.labels.get("confirm", "A"))
            return "launch", None
        elif action == "select":
            return "test", None
        elif action in ("left", "right", "up", "down") and p.slot is None:
            # A d-pad is a hat on most pads and read from EV_ABS below, but on
            # plenty of generic ones it is four ordinary buttons, and those
            # pads could not move the cursor at all before.
            step = {"left": -1, "right": 1}.get(action, 0)
            step += {"up": -1, "down": 1}.get(action, 0) * per_row
            step_cursor(p, pads, slots, step)
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
            step_cursor(p, pads, slots, step)
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
                by_id.setdefault(ids, []).append(prof)
    _PROFILES = (by_name, by_id)
    return _PROFILES


def name_words(text):
    """A pad's name as comparable words. X-Box, XBox and Xbox are one word."""
    text = (text or "").lower().replace("-", "")
    cleaned = "".join(c if c.isalnum() else " " for c in text)
    return {w for w in cleaned.split() if len(w) > 1}


def best_by_ids(candidates, name):
    """Which of the profiles claiming one id belongs to this pad.

    An id identifies far less than it looks like it does: 1118:654, a Microsoft
    Xbox 360 pad, is claimed by three profiles in the packaged set alone,
    because it is what every third-party pad and every virtual pad pretends to
    be. Keeping whichever the directory listing ended on resolved a real Xbox
    pad to a handheld's profile on a fresh install -- confirm on the north face
    button, back on the west one, both printed wrong in the prompt, and no
    error anywhere to say so.

    So the names break the tie. Nothing in common with any of them means the id
    has told us nothing, and the built-in defaults are a better answer than a
    profile picked by directory order.
    """
    if len(candidates) == 1:
        return candidates[0]
    wanted = name_words(name)
    scored = []
    for prof in candidates:
        words = set()
        for key, value in prof.items():
            if key.startswith("input_device"):
                words |= name_words(value)
        scored.append((len(wanted & words), prof))
    best = max(scored, key=lambda pair: pair[0])
    return best[1] if best[0] else None


def find_profile(dev):
    """This pad's profile: by name the way RetroArch matches it, then by
    vendor/product ids -- Sunshine's virtual pad invents a name of its own but
    carries the ids of the controller it stands in for.

    Only ids that exactly one profile claims are trusted; see profile_index.
    """
    by_name, by_id = profile_index()
    prof = by_name.get(getattr(dev, "name", "").lower())
    if prof is not None:
        return prof
    info = getattr(dev, "info", None)
    if info is None:
        return None
    candidates = by_id.get((info.vendor, info.product))
    if not candidates:
        return None
    return best_by_ids(candidates, getattr(dev, "name", ""))


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


def unready(pads):
    """Pads somebody is plainly using that have not claimed a slot.

    "Plainly using" is the whole point. A Fourth Player session creates one
    virtual pad per guest slot whether or not anybody is holding it, so asking
    "is everybody ready?" about every device present would ask every single
    time and mean nothing. A pad counts once it has been pressed.
    """
    return [q for q in pads if q.seen and q.slot is None]


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


# What fourth-player's guests call themselves, keyed by the pad they drive.
# evdev knows a device called "Fourth Player 1" and nothing else, so without
# this the picker shows the socket rather than the person. Absent unless that
# project is installed and a session is open, which is the normal case.
GUEST_NAMES = os.path.expanduser("~/.local/state/fourth-player/pad-names.json")
_guest_names = (None, {})          # (mtime, mapping)


def guest_names():
    """Names for remote pads, re-read only when the file changes."""
    global _guest_names
    try:
        stamp = os.stat(GUEST_NAMES).st_mtime_ns
    except OSError:
        _guest_names = (None, {})
        return {}
    if stamp != _guest_names[0]:
        try:
            with open(GUEST_NAMES) as fh:
                data = json.load(fh)
            names = {str(k): str(v) for k, v in data.items() if k and v}
        except (OSError, ValueError, AttributeError):
            names = {}
        _guest_names = (stamp, names)
    return _guest_names[1]


class Pad:
    def __init__(self, index, path, dev, kind="pad", cursor=0):
        self.kind = kind             # "pad" or "kbd"
        self.index = index           # RetroArch joypad index, None for a keyboard
        self.path = path
        self.dev = dev
        self.name = dev.name         # the device name; RetroArch matches on it
        # What to put on screen for it, which is not the same thing: a guest
        # who gave a name is a person, not a socket.
        self.display = guest_names().get(dev.name, dev.name)
        self.cursor = cursor
        self.slot = None             # claimed player slot (0-based)
        self.axis_latch = 0          # debounce for stick/dpad movement
        # Whether anybody has actually touched this pad. A Fourth Player
        # session creates a virtual pad per guest slot whether or not anyone is
        # holding one, so "is everybody ready?" has to mean the pads somebody
        # is plainly using, not every device the kernel can see.
        self.seen = False
        self.last_press = None       # (label, action, code) for the test screen
        self.back_since = None       # when the back button went down, if it is
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


def axis_direction(p, event):
    """Which way a stick or hat has just been pushed, or None.

    The same reading the cursor uses, said in words instead of a step: the test
    screen is for finding out what a control is, and "the left stick, left" is
    the answer somebody needs.
    """
    e = evdev.ecodes
    if event.code in (e.ABS_HAT0X, e.ABS_HAT0Y):
        if event.value == 0:
            return None
        if event.code == e.ABS_HAT0X:
            return "d-pad left" if event.value < 0 else "d-pad right"
        return "d-pad up" if event.value < 0 else "d-pad down"
    if event.code in (e.ABS_X, e.ABS_Y):
        if -DEADZONE <= event.value <= DEADZONE:
            return None
        if event.code == e.ABS_X:
            return "stick left" if event.value < 0 else "stick right"
        return "stick up" if event.value < 0 else "stick down"
    return None


def answer_event(p, event, ask):
    """One pad's reply. "yes", "no", or nothing -- and moves the highlight.

    Only the pad that raised the question may answer it. Anyone being able to
    would make the question worse than useless: the whole reason it is asked is
    that somebody may be about to act for the others.

    An answer is *chosen* and then confirmed, rather than one button meaning
    yes and another no. Which face button is "A" is not something this screen
    can know for certain -- a guest's pad arrives through the browser's
    standard mapping, and Xbox and Nintendo layouts print A on different
    buttons -- so a pad whose letters are the other way round would otherwise
    answer the opposite of what its owner meant, every time, with no warning.
    Highlighting NO to begin with means the worst a reversed pad can do is
    dismiss the question.
    """
    if p.path != ask["by"]:
        return None
    if p.kind == "kbd":
        if event.type != evdev.ecodes.EV_KEY or event.value != 1:
            return None
        if event.code in KBD_MOVE:
            ask["choice"] = 1 if KBD_MOVE[event.code] > 0 else 0
            return None
        if event.code in KBD_CLAIM:
            return "yes" if ask.get("choice") else "no"
        if event.code in KBD_RELEASE:
            return "no"
        return None

    if event.type == evdev.ecodes.EV_ABS:
        way = axis_direction(p, event)
        if way and way.endswith("left"):
            ask["choice"] = 0
        elif way and way.endswith("right"):
            ask["choice"] = 1
        return None
    if event.type != evdev.ecodes.EV_KEY or event.value != 1:
        return None
    action = p.btn.get(event.code)
    if action == "left":
        ask["choice"] = 0
    elif action == "right":
        ask["choice"] = 1
    elif action == "confirm":
        return "yes" if ask.get("choice") else "no"
    elif action == "back":
        # Dismissing is always the safe outcome, so it stays available whatever
        # this pad calls its buttons.
        return "no"
    return None


def draw_ask(screen, fonts, ask, lab):
    """A question over the board, rather than a screen that replaces it.

    The board stays visible behind it on purpose: the question is about who is
    and is not ready, and the answer to that is what is drawn underneath.
    """
    w, h = screen.get_size()
    veil = pygame.Surface((w, h), pygame.SRCALPHA)
    veil.fill((BG[0], BG[1], BG[2], 225))
    screen.blit(veil, (0, 0))

    box_w, box_h = int(w * 0.62), int(h * 0.34)
    x, y = (w - box_w) // 2, (h - box_h) // 2
    pygame.draw.rect(screen, BG2, (x, y, box_w, box_h))
    pygame.draw.rect(screen, MAGENTA, (x, y, box_w, box_h), 4)

    # The big face is for "START ANYWAY?" and too wide for "LEAVE WITHOUT
    # PLAYING?", which ran off both edges of the box. Take whichever fits.
    q = fonts["big"].render(ask["question"], True, YELLOW)
    if q.get_width() > box_w - 40:
        q = fonts["small"].render(ask["question"], True, YELLOW)
    screen.blit(q, (x + (box_w - q.get_width()) // 2, y + int(box_h * 0.16)))
    d = fonts["small"].render(ask["detail"], True, WHITE)
    screen.blit(d, (x + (box_w - d.get_width()) // 2, y + int(box_h * 0.46)))
    # Two options, one of them chosen. Pressing a button does not answer the
    # question; moving to the answer and confirming does.
    opts = [("NO", 0), ("YES", 1)]
    chosen = 1 if ask.get("choice") else 0
    bw, bh = int(box_w * 0.3), int(box_h * 0.2)
    gap = int(box_w * 0.06)
    total = bw * 2 + gap
    bx = x + (box_w - total) // 2
    by = y + int(box_h * 0.62)
    for i, (word, _value) in enumerate(opts):
        rect = (bx + i * (bw + gap), by, bw, bh)
        on = (i == chosen)
        pygame.draw.rect(screen, BG if not on else GREEN, rect)
        pygame.draw.rect(screen, GREEN if on else DIM, rect, 3)
        t = fonts["small"].render(word, True, BG if on else WHITE)
        screen.blit(t, (rect[0] + (bw - t.get_width()) // 2,
                        rect[1] + (bh - t.get_height()) // 2))
    hint = fonts["tiny"].render(
        "LEFT / RIGHT TO CHOOSE     %s TO CONFIRM" % lab["confirm"], True, CYAN)
    screen.blit(hint, (x + (box_w - hint.get_width()) // 2,
                       y + int(box_h * 0.87)))


# Leaving the tester must not depend on the mapping, because the mapping is
# the thing being tested. Holding *any* button works however wrong it is --
# and a hold is not something anybody does by accident while pressing buttons
# to see what they are called.
# Holding back leaves the picker even when other people have claimed slots.
# A tap still only releases your own. The hold is what makes it deliberate:
# leaving is not a thing to do to three other people by brushing a button, and
# it was previously impossible at all once anybody had claimed -- which left
# somebody who had opened the wrong game with no way out but the keyboard.
EXIT_HOLD_SECONDS = 2.0

TEST_HOLD_SECONDS = 2.0
# How often to look for controllers arriving or leaving while the tester is up.
TEST_RESCAN_SECONDS = 1.0


def test_inputs(screen, fonts, clock, pads, lab):
    """Name every button as it is pressed, on every pad at once.

    Controllers disagree about everything: which face button is printed A,
    whether Start is called Start, where Select went. The picker names buttons
    by what is printed on them, which is right and is no help at all to
    somebody holding a pad they have never seen -- the reported experience was
    mashing buttons with no idea which was which.

    So this says it out loud. Press anything and it names it, per pad, in that
    pad's own colour. Nothing here changes anything; it is a mirror.
    """
    holding = {}                  # (device, button) -> when it went down
    left = False
    next_scan = time.time() + TEST_RESCAN_SECONDS
    while not left:
        # The device list is not fixed while this screen is up, and this is the
        # screen somebody opens *because* their controller is behaving oddly --
        # so plugging one in here, or a Sunshine pad appearing when a Moonlight
        # client connects, has to show up. It did not: the list was taken once
        # on the way in, so a controller connected here never appeared and one
        # unplugged sat there for ever as a row that would never say anything.
        if time.time() >= next_scan:
            next_scan = time.time() + TEST_RESCAN_SECONDS
            rescan(pads)
            live = {q.path for q in pads}
            # A pad that leaves takes its held buttons with it. Without this
            # its press is held for ever, and the hold that leaves this screen
            # would fire on a controller that is not there.
            for key in [k for k in holding if k[0] not in live]:
                holding.pop(key, None)
            lab = prompt_labels(pads)

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                left = True
            elif ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                left = True

        now = time.time()
        for q in pads:
            try:
                event = q.dev.read_one()
            except OSError:
                event = None
            while event is not None:
                if event.type == evdev.ecodes.EV_KEY:
                    if q.kind == "kbd":
                        name, act = "KEY %d" % event.code, "keyboard"
                    else:
                        act = q.btn.get(event.code)
                        name = q.labels.get(act) or "?"
                    if event.value == 1:
                        q.seen = True
                        q.last_press = (name, act, event.code)
                        holding[(q.path, event.code)] = now
                    elif event.value == 0:
                        holding.pop((q.path, event.code), None)
                elif event.type == evdev.ecodes.EV_ABS:
                    way = axis_direction(q, event)
                    if way:
                        q.seen = True
                        q.last_press = (way.upper(), None, event.code)
                try:
                    event = q.dev.read_one()
                except OSError:
                    event = None

        held = max((now - t for t in holding.values()), default=0.0)
        if held >= TEST_HOLD_SECONDS:
            left = True
        draw_test(screen, fonts, pads, lab, min(1.0, held / TEST_HOLD_SECONDS))
        clock.tick(60)

    # Leaving on the back button must not also release somebody's slot.
    for q in pads:
        try:
            while q.dev.read_one() is not None:
                pass
        except OSError:
            pass


def draw_test(screen, fonts, pads, lab, held):
    w, h = screen.get_size()
    screen.fill(BG)
    for i in range(0, h, 4):
        pygame.draw.rect(screen, BG2, (0, i, w, 2))

    title = fonts["big"].render("TEST YOUR CONTROLLER", True, YELLOW)
    screen.blit(title, ((w - title.get_width()) // 2, int(h * 0.06)))
    sub = fonts["tiny"].render(
        "PRESS ANY BUTTON AND THIS SAYS WHAT IT IS", True, DIM)
    screen.blit(sub, ((w - sub.get_width()) // 2, int(h * 0.155)))

    y = int(h * 0.26)
    row = max(34, int(h * 0.09))
    for q in pads:
        draw_icon(screen, q, int(w * 0.16), y, 30)
        nm = fonts["small"].render(q.display[:22], True, WHITE)
        screen.blit(nm, (int(w * 0.16) + 42, y + 4))
        if q.last_press:
            name, act, code = q.last_press
            said = name if not act else "%s   (%s)" % (name, act.upper())
            colour = GREEN if act in ("confirm", "back", "start") else CYAN
        else:
            said, colour = "waiting...", DIM
        txt = fonts["small"].render(said, True, colour)
        screen.blit(txt, (int(w * 0.56), y + 4))
        raw = fonts["tiny"].render(
            "code %d" % q.last_press[2] if q.last_press else "", True, DIM)
        screen.blit(raw, (int(w * 0.84), y + 8))
        y += row

    # What the picker itself needs, in this pad's own words.
    key = fonts["tiny"].render(
        "THE PICKER USES:   %s = CLAIM     %s = RELEASE     %s = START"
        % (lab["confirm"], lab["back"], lab["start"]), True, DIM)
    screen.blit(key, ((w - key.get_width()) // 2, int(h * 0.8)))

    foot = fonts["small"].render("HOLD ANY BUTTON TO GO BACK", True, MAGENTA)
    screen.blit(foot, ((w - foot.get_width()) // 2, int(h * 0.88)))
    if held > 0:
        bw = int(w * 0.3)
        bx, by = (w - bw) // 2, int(h * 0.94)
        pygame.draw.rect(screen, BG2, (bx, by, bw, 10))
        pygame.draw.rect(screen, GREEN, (bx, by, int(bw * held), 10))
    pygame.display.flip()


PLAYLIST_DIR = os.path.expanduser("~/.local/share/retroarch/plists")

# The long names RetroArch files systems under, said the way the television
# says them. Repeated from kodi_menu.py rather than imported: this screen has
# to come up even if the menu generator is not installed.
SHORT_SYSTEMS = {
    "Nintendo - Super Nintendo Entertainment System": "SUPER NINTENDO",
    "Nintendo - Nintendo Entertainment System": "NES",
    "Sega - Mega-CD - Sega CD": "SEGA CD",
    "Sega - Mega Drive - Genesis": "GENESIS",
}


def short_system(name):
    if name in SHORT_SYSTEMS:
        return SHORT_SYSTEMS[name]
    for prefix in ("Nintendo - ", "Sega - ", "Sony - ", "Atari - ",
                   "Microsoft - ", "NEC - ", "SNK - "):
        if name.startswith(prefix):
            return name[len(prefix):].upper()
    return name.upper()


def now_playing(args):
    """(game, system) for the top of the picker, or ("", "").

    Read from the playlists rather than from the filename, so the picker names
    the game the same way the menu did a moment ago -- a ROM called
    "Super Godzilla (USA).sfc" is filed with a label and a system, and showing
    the path would be showing the machine's version of the answer. The filename
    is the fallback, because a game can be launched that no playlist knows
    about at all.
    """
    rom = args[-1] if args else ""
    if not rom or rom.startswith("-"):
        return "", ""
    label = os.path.splitext(os.path.basename(rom))[0]
    system = ""
    try:
        for path in sorted(glob.glob(os.path.join(PLAYLIST_DIR, "*.lpl"))):
            try:
                with open(path) as fh:
                    data = json.load(fh)
            except (OSError, ValueError):
                continue
            for item in data.get("items", []):
                if item.get("path") == rom:
                    label = item.get("label") or label
                    system = os.path.basename(path)[:-len(".lpl")]
                    return label, short_system(system)
    except OSError:
        pass
    return label, ""


def draw(screen, fonts, pads, message, slots, playing=None):
    w, h = screen.get_size()
    screen.fill(BG)
    for i in range(0, h, 4):
        pygame.draw.rect(screen, BG2, (0, i, w, 2))

    title = fonts["big"].render("SELECT YOUR PLAYER", True, YELLOW)
    screen.blit(title, ((w - title.get_width()) // 2, int(h * 0.07)))

    # What is about to start. Worth saying: by the time this screen is up the
    # menu is gone, and a guest who asked for a game from their phone has never
    # seen the menu at all.
    if playing and playing[0]:
        game = fonts["small"].render(playing[0][:52], True, WHITE)
        screen.blit(game, ((w - game.get_width()) // 2, int(h * 0.165)))
        if playing[1]:
            sysname = fonts["tiny"].render(playing[1], True, CYAN)
            screen.blit(sysname, ((w - sysname.get_width()) // 2, int(h * 0.215)))

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
            nt = fonts["tiny"].render(owner.display[:name_chars], True, WHITE)
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
        entries = [(q, fonts["tiny"].render(q.display[:12], True, DIM)) for q in free]
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

    # Said here because there is nowhere else to say it: once the game starts
    # this screen is gone, and somebody arriving halfway through a game has no
    # way to guess that it can be brought back at all.
    tip = fonts["tiny"].render(
        "IN A GAME: HOLD SELECT TO COME BACK HERE  ·  HOLD START TO QUIT",
        True, DIM)
    screen.blit(tip, ((w - tip.get_width()) // 2, int(h * 0.93)))


# Starting a game the way the cartridge did: from its own title screen.
#
# "Fresh" means do not *load* what was saved. It used to mean do not *save*
# either, and that was a mistake with real teeth: a game started fresh and
# played for three hours wrote nothing down when it closed. Combined with
# config_save_on_exit, which RetroArch had on, that one launch also disabled
# automatic saving for every game afterwards -- so the loss was not even
# confined to the session that caused it.
#
# So a fresh run saves like any other. What it must not do is quietly destroy
# the resume point somebody deliberately stepped past, which is what saving on
# exit would otherwise do -- hence preserve_auto_state below.
#
# In-game saving is untouched. Battery saves and memory cards are a different
# mechanism from save states, so a game started this way still saves the way
# it always did.
FRESH_LINES = 'savestate_auto_load = "false"\n'


def new_override(prefix):
    """An empty config fragment, somewhere anything on this machine can read.

    Old ones are swept as they are made rather than on a timer: they are tiny,
    they are only interesting while the game they configured is running, and
    nothing else is ever going to come along and tidy them up.
    """
    os.makedirs(OVERRIDE_DIR, exist_ok=True)
    cutoff = time.time() - OVERRIDE_KEEP
    for old in glob.glob(os.path.join(OVERRIDE_DIR, "*.cfg")):
        try:
            if os.stat(old).st_mtime < cutoff:
                os.unlink(old)
        except OSError:
            pass
    return tempfile.mkstemp(prefix=prefix, suffix=".cfg", dir=OVERRIDE_DIR)


def rom_of(args):
    """The content path out of a RetroArch command line, or ""."""
    return args[-1] if args and not args[-1].startswith("-") else ""


def preserve_auto_state(rom):
    """Keep the resume point a fresh start is about to step past.

    A fresh run still saves when it closes, which is the whole point -- but the
    file it saves into is the one holding wherever somebody was before they
    chose to start again. Copying it aside first means choosing "start fresh"
    costs nothing: the old position is still on disk under .previous, and the
    new one is written normally.
    """
    if not rom:
        return
    stem = os.path.splitext(os.path.basename(rom))[0]
    pattern = os.path.join(STATE_DIR, "*", glob.escape(stem) + ".state.auto")
    for path in glob.glob(pattern):
        try:
            shutil.copy2(path, path + ".previous")
            if os.path.exists(path + ".png"):
                shutil.copy2(path + ".png", path + ".previous.png")
            log_line("kept the old resume point as %s"
                     % os.path.basename(path + ".previous"))
        except OSError as exc:
            log_line("could not keep the old resume point: %s" % exc)


def fresh_override():
    """A config that only turns the automatic save state off."""
    fd, path = new_override("ra_fresh_")
    with os.fdopen(fd, "w") as fh:
        fh.write(NO_PAD_MENU)
        fh.write(FRESH_LINES)
    return path


def guard_override():
    """The smallest config worth passing: the one that shuts the menu."""
    fd, path = new_override("ra_guard_")
    with os.fdopen(fd, "w") as fh:
        fh.write(NO_PAD_MENU)
    return path


def write_override(pads, slots, fresh=False, slot=None):
    """Write a RetroArch config fragment binding claimed devices to ports."""
    claimed = [p for p in pads if p.slot is not None]
    kbd_slot = next((p.slot for p in claimed if p.kind == "kbd"), None)
    # A game may show fewer slots than there are ports; the ports beyond the
    # board still have to be parked, or a stray pad drives a player nobody
    # picked.
    ports = max(slots, MAX_PLAYERS)
    fd, path = new_override("ra_players_")
    with os.fdopen(fd, "w") as fh:
        fh.write(NO_PAD_MENU)
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
        # instead of the first free port.
        #
        # "Reserved" (2), not "Preferred" (1). Preferred is a suggestion, and
        # autoconfiguration is free to ignore it -- which it does the moment
        # anything else is plugged in. With a Moonlight client connected,
        # Sunshine's four virtual pads appeared first and took all four ports:
        #
        #   [Autoconf] Remote player 1 configured in port 1.
        #   [ERROR] [Autoconf] No free and unreserved player slots found for
        #           adding new device "Fourth Player 4"!
        #
        # so the pad that had claimed player 1 on the picker screen drove
        # nothing at all, while a device nobody picked drove the game. The
        # earlier reasoning for preferring "preferred" was that a name which
        # failed to match would leave the port empty; an empty port is a much
        # smaller problem than the wrong device in it, and the name written
        # here is read straight off the device a moment earlier.
        for s in range(ports):
            name = reserved.get(s)
            fh.write('input_player%d_reserved_device = "%s"\n'
                     % (s + 1, name or ""))
            fh.write('input_player%d_device_reservation_type = "%d"\n'
                     % (s + 1, 2 if name else 0))
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
        if fresh:
            # Last, so it beats anything above it, though nothing above it
            # touches save states today.
            fh.write(FRESH_LINES)
        if slot is not None:
            # A game being carried across a change of players. The slot has to
            # match the one it was written to a moment ago, or LOAD_STATE will
            # confidently load somebody else's save instead.
            fh.write('state_slot = "%d"\n' % slot)
            fh.write('savestate_auto_load = "false"\n')
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

    for p in pads:
        p.display = guest_names().get(p.name, p.name)

    # Pads first in joypad order, then keyboards, which have no index to sort on.
    pads.sort(key=lambda p: (p.kind != "pad", p.index if p.index is not None else 0))
    assign_colors(pads)
    return pads


def main():
    args = sys.argv[1:]
    # --max-players is ours, not RetroArch's, so it never reaches the emulator.
    cap = None
    shader = None
    fresh = False
    while args:
        if args[0] == "--fresh":
            fresh = True
            args = args[1:]
            continue
        if len(args) >= 2 and args[0] in ("--max-players", "--shader"):
            if args[0] == "--max-players":
                try:
                    cap = max(1, int(args[1]))
                except ValueError:
                    cap = None
            else:
                # "none" is a real answer, and different from saying nothing.
                shader = "" if args[1] == "none" else args[1]
            args = args[2:]
            continue
        break
    if not args:
        print("usage: ra_players.py [--max-players N] [--shader S] [--fresh] "
              "<retroarch args...>", file=sys.stderr)
        return 2

    guard_config()
    restore_stale_state()
    # A note here means a previous run was borrowing somebody's save state and
    # never finished handing it back -- it crashed, or was killed, or the game
    # it relaunched died before it could read the state. Whichever it was, the
    # carried game is the only copy of where somebody was, so it is kept.
    restore_carried(rescue=True)

    repick = Repick()
    asked = False
    while True:
        code = play_once(args, cap, shader, fresh, asked, repick)
        if code != REPICK:
            return code
        # From here on the picker comes up whatever the pads say: being asked
        # for is the whole reason it is coming back. `fresh` is left alone --
        # it means "do not touch the automatic save", which is still true --
        # and the game resumes from the slot it was parked in instead.
        asked = True


def play_once(args, cap, shader, fresh, asked, repick):
    """Pick the players if they need picking, then play until it is over."""
    load_slot = repick.slot if repick.is_set() else None
    previous = repick.override
    repick.clear()
    repick.slot = None

    pads_raw = input_devices()
    joypads = [d for d in pads_raw if d[0] == "pad"]
    if not asked and not needs_picker(len(joypads), cap):
        for _kind, _index, _path, dev in pads_raw:
            dev.close()
        if fresh:
            preserve_auto_state(rom_of(args))
        override = fresh_override() if fresh else guard_override()
        repick.override = override
        return run_retroarch(args, override, shader=shader, repick=repick,
                             load_slot=load_slot)

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
    ask = None                      # a yes/no question waiting on an answer
    playing = now_playing(args)
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
        lab = prompt_labels(pads)
        want_test = False

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                cancelled = True
            elif ev.type == pygame.KEYDOWN:
                if ask is not None:
                    # A question is up; the keyboard answers it rather than
                    # doing what the key would otherwise do.
                    if ev.key in (pygame.K_LEFT, pygame.K_RIGHT):
                        ask["choice"] = 1 if ev.key == pygame.K_RIGHT else 0
                    elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        if not ask.get("choice"):
                            ask = None          # NO was the highlighted answer
                        elif ask["kind"] == "launch":
                            launch = True
                            ask = None
                        else:
                            cancelled = True
                            ask = None
                    elif ev.key == pygame.K_ESCAPE:
                        ask = None
                elif ev.key == pygame.K_ESCAPE:
                    ask = {"kind": "cancel", "by": None,
                           "question": "LEAVE WITHOUT PLAYING?", "choice": 0,
                           "detail": "THE GAME WILL NOT START"}

        for p in pads:
            try:
                event = p.dev.read_one()
            except OSError:
                event = None
            while event is not None:
                if ask is not None:
                    reply = answer_event(p, event, ask)
                    if reply == "yes":
                        if ask["kind"] == "launch":
                            launch = True
                        else:
                            cancelled = True
                        ask = None
                    elif reply == "no":
                        ask = None
                        note, note_ticks = "NOT YET", 90
                else:
                    action, said = handle_event(p, event, pads, slots)
                    if action == "launch":
                        # Everybody who is holding a pad gets asked about,
                        # because the reason to ask is somebody having let go
                        # of their slot by accident a moment ago.
                        waiting = unready(pads)
                        if waiting:
                            ask = {"kind": "launch", "by": p.path,
                                   "question": "START ANYWAY?", "choice": 0,
                                   "detail": "%d CONTROLLER%s NOT READY"
                                   % (len(waiting), "" if len(waiting) == 1 else "S")}
                        else:
                            launch = True
                    elif action == "cancel":
                        ask = {"kind": "cancel", "by": p.path,
                               "question": "LEAVE WITHOUT PLAYING?", "choice": 0,
                               "detail": "THE GAME WILL NOT START"}
                    elif action == "test":
                        want_test = True
                    if said:
                        note, note_ticks = said, 120
                try:
                    event = p.dev.read_one()
                except OSError:
                    event = None

        if ask is None and not (launch or cancelled):
            for p in pads:
                if (p.back_since is not None
                        and time.time() - p.back_since >= EXIT_HOLD_SECONDS):
                    p.back_since = None
                    ask = {"kind": "cancel", "by": p.path, "choice": 0,
                           "question": "LEAVE WITHOUT PLAYING?",
                           "detail": "THE GAME WILL NOT START"}
                    break

        if want_test and not (launch or cancelled):
            # Runs its own loop and reads the pads itself, so it cannot be
            # entered from inside the reading above.
            test_inputs(screen, fonts, clock, pads, lab)

        ready = sum(1 for p in pads if p.slot is not None)
        kbd = any(p.kind == "kbd" for p in pads)
        claim_btn = lab["confirm"] + ("/X" if kbd else "")
        back_btn = lab["back"] + ("/Z" if kbd else "")
        start_btn = lab["start"] + ("/ENTER" if kbd else "")
        test_btn = lab.get("select") or "SELECT"
        if note_ticks > 0:
            note_ticks -= 1
            msg = note
        elif ready:
            msg = "%s TO PLAY   %s = RELEASE, HOLD = LEAVE   %s = TEST" % (
                start_btn, back_btn, test_btn)
        else:
            # With nobody claimed the back button leaves the screen, so say so
            # here -- without it the only way out is a keyboard's ESC.
            msg = "%s = CLAIM   %s = BACK, HOLD = LEAVE   %s = TEST" % (
                claim_btn, back_btn, test_btn)
        draw(screen, fonts, pads, msg, slots, playing)
        if ask is not None:
            draw_ask(screen, fonts, ask, lab)
        pygame.display.flip()
        clock.tick(60)

    if launch and fresh and load_slot is None:
        # Only on the first pass. Coming back from the picker mid-game carries
        # the game across in a slot of its own, and the resume point was put
        # aside when this game first started.
        preserve_auto_state(rom_of(args))
    override = write_override(pads, slots, fresh, slot=load_slot) \
        if launch else None
    for p in pads:
        p.close()
    pygame.quit()

    if cancelled:
        if load_slot is None:
            return 1
        # Backing out of a picker that was asked for mid-game means "leave it
        # as it was", not "stop playing" -- so the game comes back on the same
        # config, with the same people on the same ports.
        repick.override = previous
        return run_retroarch(args, previous, shader, repick=repick,
                             load_slot=load_slot)

    repick.override = override
    return run_retroarch(args, override, shader, repick=repick,
                         load_slot=load_slot)


if __name__ == "__main__":
    sys.exit(main())
