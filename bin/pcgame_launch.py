#!/usr/bin/env python3
"""Launch a native PC game from Kodi, keeping the window stacking sane.

Kodi runs fullscreen and keeps focus, so a game started underneath it stays
in the background. This wrapper raises the game once its window appears,
waits for it to finish, then hands focus back to Kodi. It also refuses to
start a second copy, which previously left several instances stacked up.
"""

import atexit
import argparse
import os
import re
import select
import struct
import subprocess
import sys
import time

WAIT_FOR_WINDOW = 40.0     # seconds to wait for the game to map a window
HEALTH_INTERVAL = 20.0     # how often to check the pad is still sending
HEALTH_COOLDOWN = 60.0     # never revive more often than this
HEALTH_MAX_TRIES = 4       # stop trying if reviving is not helping
POLL = 0.5


def sh(*args):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=15).stdout
    except Exception:
        return ""


def already_running(exe):
    """True if the game itself is running.

    Deliberately matches the process *name* (pgrep -x), not the full command
    line: this wrapper's own argv contains the executable path, so a -f match
    would find itself and refuse to ever launch. Zombies are ignored too.
    """
    name = os.path.basename(exe)[:15]        # comm is truncated to 15 chars
    out = sh("ps", "-eo", "pid,stat,comm")
    me = str(os.getpid())
    for line in out.splitlines()[1:]:
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        pid, stat, comm = parts
        if pid == me or "Z" in stat:
            continue
        if comm.strip() == name:
            return True
    return False


def find_window(match):
    """The largest window whose title matches.

    Not simply the first: Call of Duty 4 maps a small secondary window
    alongside its render window, both titled "Call of Duty 4". Raising the
    small one leaves a black rectangle sitting over the game.
    """
    best, best_area = None, -1
    for line in sh("wmctrl", "-lG").splitlines():
        parts = line.split(None, 7)
        if len(parts) < 8 or match.lower() not in parts[7].lower():
            continue
        try:
            area = int(parts[4]) * int(parts[5])
        except ValueError:
            continue
        if area > best_area:
            best, best_area = parts[0], area
    return best


def sibling_windows(match, keep):
    """Other windows sharing the game's title, besides the one we raised."""
    out = []
    for line in sh("wmctrl", "-lG").splitlines():
        parts = line.split(None, 7)
        if len(parts) < 8 or match.lower() not in parts[7].lower():
            continue
        if parts[0] != keep:
            out.append(parts[0])
    return out


def demote(wid):
    subprocess.run(["wmctrl", "-i", "-r", wid, "-b", "add,below"], check=False)


def raise_window(wid):
    subprocess.run(["wmctrl", "-i", "-a", wid], check=False)
    # Wine's virtual desktop opens as a normal window; make it fill the screen
    # so contained games are presented full-size (harmless for other windows).
    subprocess.run(["wmctrl", "-i", "-b", "add,fullscreen", wid], check=False)
    subprocess.run(["xdotool", "windowactivate", "--sync", str(int(wid, 16))],
                   check=False, stderr=subprocess.DEVNULL)


def screen_geometry():
    """Current X screen size. xdpyinfo is authoritative; xrandr output is easy
    to misread because non-active modes also appear in its list."""
    for line in sh("xdpyinfo").splitlines():
        if "dimensions:" in line:
            return line.split()[1]
    return ""


def set_mode(geom):
    if not geom:
        return
    subprocess.run(["xrandr", "--output", "HDMI-A-0", "--mode", geom + "_60"],
                   check=False, stderr=subprocess.DEVNULL)
    if screen_geometry() != geom:
        subprocess.run(["xrandr", "--output", "HDMI-A-0", "--mode", geom],
                       check=False, stderr=subprocess.DEVNULL)


JSM_BIN = os.path.expanduser("~/.local/lib/joyshockmapper/JoyShockMapper")
HUD_BIN = os.path.expanduser("~/.local/bin/jsm-hud")
# Used when a game names no config of its own. Every PC game gets a controller
# mapping and the on-screen reference, not just the ones somebody has written a
# config for: a new game is playable with a pad the moment it is added, and the
# HUD is there to show what the buttons do and to change them.
JSM_GAMES = os.path.expanduser("~/.config/JoyShockMapper/games")
DEFAULT_JSM = os.path.expanduser("~/.config/JoyShockMapper/games/_default.txt")


def resolve_jsm(name, game_id=None):
    """Find a mapping for this game, trying hardest before giving up.

    A config may be written as a full path, as a bare filename (which is
    what templates/pcgames.json has always documented), or left out
    entirely -- in which case the game id names it, so a game called bf2
    finds games/bf2.txt with nothing declared at all. Failing everything,
    the shared default still gives a pad and an on-screen reference.
    """
    tries = []
    for candidate in (name, game_id):
        if not candidate:
            continue
        tries.append(candidate)
        if not candidate.endswith(".txt"):
            tries.append(candidate + ".txt")
    for t in tries:
        t = os.path.expanduser(t)
        path = t if os.path.isabs(t) else os.path.join(JSM_GAMES, t)
        if os.path.exists(path):
            return path
    return DEFAULT_JSM if os.path.exists(DEFAULT_JSM) else None

# JSM takes commands on stdin and reports on stdout. Both are made reachable
# from outside this process so the HUD can drive JSM and watch what it loads:
#   the fifo is JSM's stdin, so anything written to it is a console command
#   the log is JSM's stdout, where "Loading commands from file X" shows up
_RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
JSM_FIFO = os.path.join(_RUNTIME, "jsm.cmd")
JSM_LOG = os.path.join(_RUNTIME, "jsm.log")
HUD_LOG = os.path.join(_RUNTIME, "jsm-hud.log")


def start_jsm(config):
    """Map the controller to keyboard+mouse for games with no pad support.

    JoyShockMapper takes commands on stdin, so the config path is piped in --
    it ignores a config given as an argument. stdin is left open so its command
    loop keeps running.
    """
    # Never leave two of these alive. Each one synthesises key presses, so a
    # second instance makes every d-pad press arrive twice -- and if one
    # outlives its game it types into whatever has focus next, which is Kodi.
    # That is what "the menu jumps three rows" turned out to be.
    subprocess.run(["pkill", "-x", "JoyShockMapper"], check=False)
    time.sleep(1)
    if not config or not os.path.exists(JSM_BIN) or not os.path.exists(config):
        return None
    env = dict(os.environ)
    env.setdefault("DISPLAY", ":0")
    try:
        if os.path.exists(JSM_FIFO):
            os.unlink(JSM_FIFO)
        os.mkfifo(JSM_FIFO, 0o600)
        # O_RDWR on a fifo neither blocks nor ever sees EOF, which is what we
        # want: JSM reads commands from it for the whole session, and this
        # process keeps the write end so the HUD can open it whenever it likes.
        fifo = os.open(JSM_FIFO, os.O_RDWR)
        log = open(JSM_LOG, "wb", 0)
        proc = subprocess.Popen(
            [JSM_BIN], cwd=os.path.dirname(JSM_BIN), env=env,
            stdin=fifo, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True)
        proc._jsm_fifo = fifo          # kept open deliberately; see above
        proc._jsm_log = log
        send_jsm(proc, config)
        return proc
    except OSError:
        return None


def send_jsm(proc, command):
    """Write one console command (or a config path) to JSM."""
    try:
        os.write(proc._jsm_fifo, (command + "\n").encode())
        return True
    except (OSError, AttributeError):
        return False


def stop_jsm(proc):
    """Ask JoyShockMapper to quit, and only kill it if that fails.

    JSM ignores SIGTERM, so SIGKILL was the original stop -- but that is not
    safe with a Switch Pro Controller. SDL talks to it through hidraw and puts
    it into a proprietary report mode that hid-nintendo cannot parse, restoring
    it only on a clean shutdown. Killed outright, the controller keeps sending
    reports the kernel ignores: its evdev and js nodes go silent and Kodi sees
    a pad that is connected but mute until it is power cycled. Writing QUIT to
    the console is the clean exit, and SIGKILL stays as the fallback.
    """
    if not proc:
        return
    send_jsm(proc, "QUIT")
    try:
        proc.wait(timeout=8)
        return
    except subprocess.TimeoutExpired:
        pass
    proc.kill()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def _imu_node():
    """Event node of the controller's IMU, by name. Numbers change on every
    reconnect and every driver rebind, so this cannot be cached."""
    try:
        with open("/proc/bus/input/devices") as handle:
            blocks = handle.read().split("\n\n")
    except OSError:
        return None
    for block in blocks:
        if 'N: Name="Pro Controller (IMU)"' not in block:
            continue
        match = re.search(r"H: Handlers=(.*)", block)
        if match:
            for handler in match.group(1).split():
                if handler.startswith("event"):
                    return "/dev/input/" + handler
    return None


def controller_is_streaming(seconds=0.8):
    """Is the pad actually sending, or merely connected?

    The IMU streams continuously while the controller is awake -- including
    while JoyShockMapper holds it over hidraw, which was measured rather than
    assumed. So this distinguishes a live pad from one that has gone silent,
    without the player having to touch anything. Unknown counts as healthy, so
    a missing node or a permissions problem never triggers a rebind loop.
    """
    node = _imu_node()
    if not node:
        return True
    try:
        fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        return True
    try:
        end = time.time() + seconds
        while time.time() < end:
            ready, _, _ = select.select([fd], [], [], 0.2)
            if not ready:
                continue
            try:
                data = os.read(fd, 24)
            except OSError:
                continue
            if len(data) == 24 and struct.unpack("llHHi", data)[2]:
                return True
        return False
    finally:
        os.close(fd)


def controller_signature():
    """A fingerprint of the attached input devices.

    Used only to notice *change* -- a controller going away, coming back, or
    being swapped for a different one. Devices with both absolute axes and
    buttons are the ones that matter; JSM's own virtual devices are excluded
    or it would react to itself starting up.
    """
    try:
        with open("/proc/bus/input/devices") as handle:
            blocks = handle.read().split("\n\n")
    except OSError:
        return ""
    names = []
    for block in blocks:
        if "ABS=" not in block or "KEY=" not in block:
            continue
        for line in block.splitlines():
            if line.startswith("N: Name="):
                name = line[8:].strip().strip('"')
                if name and not name.startswith("JoyShockMapper_"):
                    names.append(name)
    return "|".join(sorted(names))


def reconnect_jsm(proc):
    """Tell JSM to re-enumerate. Its own console command for exactly this."""
    return bool(proc) and send_jsm(proc, "RECONNECT_CONTROLLERS")


def start_hud(config):
    """On-screen layer notifications and the in-game settings overlay.

    Entirely optional: if it is missing or fails to start the game is
    unaffected, so this never gets in the way of playing.
    """
    if not os.path.exists(HUD_BIN):
        return None
    env = dict(os.environ)
    env.setdefault("DISPLAY", ":0")
    try:
        # Its output goes to a file rather than /dev/null: the HUD failing to
        # import a module is silent otherwise, and the only symptom is a game
        # with no on-screen controls reference and no explanation anywhere.
        errors = open(HUD_LOG, "w")
        return subprocess.Popen(
            [HUD_BIN, "--config", config, "--fifo", JSM_FIFO,
             "--log", JSM_LOG],
            env=env, stdout=errors, stderr=subprocess.STDOUT,
            start_new_session=True)
    except OSError:
        return None


def stop_hud(proc):
    if not proc:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def revive_controller():
    """Re-initialise a Nintendo pad after JoyShockMapper has had it.

    JSM reaches the controller over hidraw through SDL, which leaves a Switch
    Pro in a report mode hid-nintendo cannot parse -- a clean QUIT does not
    undo it. The symptom is nasty because nothing looks wrong: Bluetooth link
    quality is fine and Kodi still enumerates the pad, but no input arrives, so
    the controller appears dead in Kodi after every game. Rebinding the driver
    makes it redo its handshake. No-op when no Nintendo pad is connected.
    """
    subprocess.run(["sudo", "-n", "/usr/local/sbin/nintendo-rebind"],
                   check=False, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, timeout=20)
    reopen_kodi_joysticks()


def kodi_web_credentials():
    """"user:password" for Kodi's JSON-RPC, read from Kodi's own settings.

    Read at run time rather than written down here: this file is in a git
    repository, and a password in source is a password published the first time
    that repository is pushed anywhere.
    """
    settings = os.path.expanduser("~/.kodi/userdata/guisettings.xml")
    user = password = None
    try:
        with open(settings, encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError:
        return None
    for key, target in (("services.webserverusername", "user"),
                        ("services.webserverpassword", "password")):
        found = re.search(r'<setting id="%s"[^>]*>([^<]*)<' % key, text)
        if found:
            if target == "user":
                user = found.group(1)
            else:
                password = found.group(1)
    if not user:
        return None
    return "%s:%s" % (user, password or "")


def reopen_kodi_joysticks():
    """Make a running Kodi reopen the input nodes the rebind just replaced.

    Kodi keeps the old descriptor otherwise -- lsof shows it "(deleted)" -- and
    the pad appears in Settings while sending nothing. Games that stop Kodi do
    not need this (it starts fresh afterwards), but the ones that leave it
    running do. Best effort: if Kodi is not up, or the web server is off, the
    game is unaffected.
    """
    if subprocess.run(["pgrep", "-x", "kodi.bin"], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL, check=False).returncode != 0:
        return
    import base64
    import json as _json
    import urllib.error
    import urllib.request
    credentials = kodi_web_credentials()
    if credentials is None:
        return
    auth = base64.b64encode(credentials.encode()).decode()
    for enabled in (False, True):
        body = _json.dumps({
            "jsonrpc": "2.0", "id": 1,
            "method": "Addons.SetAddonEnabled",
            "params": {"addonid": "peripheral.joystick", "enabled": enabled},
        }).encode()
        request = urllib.request.Request(
            "http://127.0.0.1:8080/jsonrpc", data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": "Basic " + auth})
        try:
            urllib.request.urlopen(request, timeout=5).read()
        except (urllib.error.URLError, OSError):
            return
        if not enabled:
            time.sleep(2)


# While this exists, kodi-autostart.sh must not put Kodi back. Killing Kodi
# makes it exit non-zero, which is indistinguishable from a crash, so without
# this the supervisor restarted Kodi three seconds later -- on top of the game
# that had just asked for the screen.
KODI_HOLD = os.path.join(os.path.expanduser("~/.local/state"), "kodi-hold")


def hold_kodi(on):
    try:
        if on:
            os.makedirs(os.path.dirname(KODI_HOLD), exist_ok=True)
            with open(KODI_HOLD, "w") as handle:
                handle.write("%d\n" % os.getpid())
        elif os.path.exists(KODI_HOLD):
            os.remove(KODI_HOLD)
    except OSError:
        pass


def stop_kodi():
    """Shut Kodi down. Note pkill -x: a -f pattern would match this process."""
    hold_kodi(True)
    # Belt as well as braces: the supervisor also notices a dead holder, but
    # an ordinary exit should not depend on it doing so.
    atexit.register(lambda: hold_kodi(False))
    subprocess.run(["pkill", "-x", "kodi.bin"], check=False)
    time.sleep(6)
    subprocess.run(["pkill", "-9", "-x", "kodi.bin"], check=False)
    time.sleep(2)


def start_kodi():
    """Bring Kodi back after a game. Refuses to start a second one.

    Two instances fight over the display and leave an unresponsive black
    screen. That is easy to cause without noticing: if Kodi was started by
    hand while a stop_kodi game was running, the unconditional restart at the
    end of the game would add another.
    """
    hold_kodi(False)
    if subprocess.run(["pgrep", "-x", "kodi.bin"], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL, check=False).returncode == 0:
        return False
    # If the supervisor is alive it is waiting on the hold and will start Kodi
    # itself, with the crash handling intact. Starting one here as well would
    # give two Kodis fighting over the display -- and would also leave the
    # session without a supervisor, so a later crash would not be caught.
    if subprocess.run(["pgrep", "-x", "kodi-autostart."],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                      check=False).returncode == 0:
        return False
    env = dict(os.environ)
    env.setdefault("DISPLAY", ":0")
    subprocess.Popen(["setsid", "kodi", "-fs"], env=env,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    return True


def restart_kodi():
    """Kodi keeps rendering at the old size after a mode change and only a
    restart re-establishes its viewport (togglefullscreen does not work)."""
    stop_kodi()
    start_kodi()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cwd")
    ap.add_argument("--match", required=True,
                    help="substring of the game's window title")
    ap.add_argument("--stop-kodi", action="store_true",
                    help="stop Kodi for the duration of the game")
    ap.add_argument("--env", action="append", default=[], metavar="K=V",
                    help="extra environment for the game, repeatable")
    ap.add_argument("--id", metavar="ID", default=None,
                    help="the game's id, used to find its mapping by name")
    ap.add_argument("--jsm", metavar="CONFIG",
                    help="JoyShockMapper config to run alongside the game")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    args = ap.parse_args()

    cmd = [c for c in args.cmd if c != "--"]
    if not cmd:
        return 2

    if already_running(cmd[0]):
        # A second instance fights the first for the display and input.
        subprocess.run(["kodi-send", "--host=127.0.0.1",
                        "--action=Notification(PC Game,Already running,3000)"],
                       check=False, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
        return 0

    before_geom = screen_geometry()

    # Warcraft III (and any other game that takes exclusive fullscreen) is
    # minimised by the driver the instant it does not have the foreground, and
    # Kodi reclaims the foreground even from an iconified state -- so raising
    # the game is not enough, Kodi has to be gone while it runs.
    if args.stop_kodi:
        stop_kodi()

    env = dict(os.environ)
    env.setdefault("DISPLAY", ":0")
    # Per-game environment, e.g. Battlefield 2 needs its own d3dx9 rather than
    # Wine's, whose HLSL compiler cannot build the game's .fx shaders.
    for pair in args.env:
        key, sep, value = pair.partition("=")
        if sep:
            env[key] = value
    proc = subprocess.Popen(cmd, cwd=args.cwd or None, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Bring the game to the front once it actually has a window. It can take a
    # while to map, and it may need re-raising if Kodi grabs focus back.
    deadline = time.time() + WAIT_FOR_WINDOW
    wid = None
    while time.time() < deadline and proc.poll() is None:
        wid = find_window(args.match)
        if wid:
            for _ in range(6):
                raise_window(wid)
                time.sleep(0.7)
            break
        time.sleep(POLL)

    # Only now start the controller mapping. Started any earlier it is Kodi --
    # still on screen for the games that do not set stop_kodi -- that receives
    # the synthesised mouse and keys, and a stray click on the PC GAMES list
    # silently launches another game.
    config = resolve_jsm(args.jsm, args.id)
    jsm = start_jsm(config)
    hud = start_hud(config) if jsm else None

    # Call of Duty 4 maps a small secondary window *after* its render window,
    # and it lands on top as a black rectangle over the game. Keep pushing any
    # such late sibling behind for as long as the game runs -- it can appear a
    # minute or more in, e.g. after the safe-mode prompt. A no-op for
    # single-window games, which is every other title here.
    raised = wid
    # Watchdog state: keep the mapping alive for as long as the game runs, even
    # if the controller drops off, comes back, or is swapped for another one.
    signature = controller_signature()
    pending = None
    # The pad can go silent mid-game -- connected, enumerated by JSM, sending
    # nothing. Checking the device set is not enough to catch that, because
    # nothing appears or disappears; only the data stops.
    next_health = time.time() + HEALTH_INTERVAL
    last_revive = 0.0
    revives = 0
    while proc.poll() is None:
        if config:
            now = time.time()
            if now >= next_health:
                next_health = now + HEALTH_INTERVAL
                if (not controller_is_streaming()
                        and now - last_revive > HEALTH_COOLDOWN
                        and revives < HEALTH_MAX_TRIES):
                    last_revive = now
                    revives += 1
                    revive_controller()
                    # The rebind tears the input devices down and builds them
                    # again, so JSM has to be told to look for the pad afresh.
                    time.sleep(2)
                    reconnect_jsm(jsm)
                    signature = controller_signature()
                    pending = None
                elif controller_is_streaming():
                    revives = 0
            if jsm is not None and jsm.poll() is not None:
                # JSM itself died -- start it again with the same config.
                jsm = start_jsm(config)
                signature = controller_signature()
                pending = None
            else:
                current = controller_signature()
                if current != signature:
                    # Wait for one more pass before acting: a pad that has just
                    # appeared is often still registering its second device
                    # (the Pro Controller adds a separate IMU node), and
                    # reconnecting mid-way finds only half of it.
                    if pending == current:
                        signature = current
                        pending = None
                        reconnect_jsm(jsm)
                    else:
                        pending = current
                else:
                    pending = None

        # Re-resolve every pass: the render window can appear after the
        # WAIT_FOR_WINDOW deadline (Call of Duty 4's safe-mode prompt alone can
        # burn all 40s), in which case the initial search found nothing.
        main = find_window(args.match)
        if main:
            if main != raised:
                raise_window(main)
                raised = main
            for other in sibling_windows(args.match, main):
                demote(other)
        time.sleep(2)

    proc.wait()
    stop_hud(hud)
    stop_jsm(jsm)
    if jsm:
        revive_controller()

    # Game finished. If it changed the display mode, put it back; Kodi cannot
    # recover its render size on its own and has to come up afterwards.
    after_geom = screen_geometry()
    mode_changed = bool(before_geom) and after_geom != before_geom
    if mode_changed:
        set_mode(before_geom)
        time.sleep(2)

    if args.stop_kodi:
        start_kodi()
        return 0

    if mode_changed:
        restart_kodi()
        return 0

    kodi = find_window("Kodi")
    if kodi:
        raise_window(kodi)
    subprocess.run(["kodi-send", "--host=127.0.0.1", "--action=ActivateWindow(Home)"],
                   check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return 0


if __name__ == "__main__":
    sys.exit(main())
