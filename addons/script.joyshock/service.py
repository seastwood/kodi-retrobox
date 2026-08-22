# -*- coding: utf-8 -*-
"""Keeps the controller usable in Kodi.

There is a failure mode that looks like nothing is wrong: the Bluetooth link
reads healthy, Kodi lists the pad in Settings, and yet no input arrives. It
happens after JoyShockMapper has had the controller -- JSM reaches it over
hidraw through SDL, which leaves a Switch Pro in a report mode hid-nintendo
cannot parse, and quitting JSM cleanly does not undo it. Rebinding the driver
makes the controller redo its handshake and reports start flowing again.

pcgame_launch.py already does that after each game. This covers everything
else: a controller that drops and comes back on its own, or one left silent by
a JSM run that did not go through the launcher.

The health signal is the IMU device, which streams continuously while the pad
is awake -- so this can tell "silent" from "idle" without anybody touching it.
"""

import json
import os
import re
import select
import struct
import subprocess
import time

import xbmc

IMU_NAME = "Pro Controller (IMU)"
REBIND = "/usr/local/sbin/nintendo-rebind"

POLL = 20.0            # seconds between checks
LISTEN = 1.5           # how long to watch the IMU before calling it silent
COOLDOWN = 120.0       # never rebind more often than this
MAX_TRIES = 3          # stop trying if rebinding is not helping
TAG = "script.joyshock: "


def log(message, level=xbmc.LOGINFO):
    xbmc.log(TAG + message, level)


def find_imu():
    """Event node of the controller's IMU, by name -- the numbers change on
    every reconnect, so they cannot be cached."""
    try:
        with open("/proc/bus/input/devices") as handle:
            blocks = handle.read().split("\n\n")
    except OSError:
        return None
    for block in blocks:
        if 'N: Name="%s"' % IMU_NAME not in block:
            continue
        match = re.search(r"H: Handlers=(.*)", block)
        if not match:
            continue
        for handler in match.group(1).split():
            if handler.startswith("event"):
                return "/dev/input/" + handler
    return None


def is_streaming(path, seconds=LISTEN):
    """True if the device produced any event. -1 style errors count as True so
    a permissions problem never triggers an endless rebind loop."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
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


BTN_SOUTH = 0x130


def _declares_gamepad_buttons(block):
    """True if the KEY bitmap includes BTN_SOUTH. /proc/bus/input/devices
    prints the bitmap most significant word FIRST."""
    match = re.search(r"B: KEY=(.*)", block)
    if not match:
        return False
    try:
        words = [int(w, 16) for w in match.group(1).split()]
    except ValueError:
        return False
    index, bit = divmod(BTN_SOUTH, 64)
    if index >= len(words):
        return False
    return bool(words[len(words) - 1 - index] >> bit & 1)


def find_pad_node():
    """The real controller's event node -- not the IMU, not a virtual pad."""
    try:
        with open("/proc/bus/input/devices") as handle:
            blocks = handle.read().split("\n\n")
    except OSError:
        return None
    for block in blocks:
        name = re.search(r'N: Name="(.*)"', block)
        name = name.group(1) if name else ""
        sysfs = re.search(r"S: Sysfs=(.*)", block)
        sysfs = sysfs.group(1).strip() if sysfs else ""
        if "(IMU)" in name or sysfs.startswith("/devices/virtual/"):
            continue
        if not _declares_gamepad_buttons(block):
            continue
        handlers = re.search(r"H: Handlers=(.*)", block)
        for handler in (handlers.group(1).split() if handlers else []):
            if handler.startswith("event"):
                return "/dev/input/" + handler
    return None


def holds_live_pad_fd(node):
    """Is one of THIS process's descriptors open on that node?

    This code runs inside Kodi, so /proc/self/fd is Kodi's own table. A
    descriptor left over from a destroyed device reads back as
    "/dev/input/eventN (deleted)", which will not match, so a stale handle
    correctly counts as not held.
    """
    try:
        names = os.listdir("/proc/self/fd")
    except OSError:
        return True                      # cannot tell; assume fine
    for fd in names:
        try:
            if os.readlink("/proc/self/fd/" + fd) == node:
                return True
        except OSError:
            continue
    return False


def game_owns_controller():
    """True while a game has the pad, in which case leave it alone.

    Not because the IMU is silent then -- it is not; a healthy pad keeps
    streaming while JSM holds it over hidraw, measured at ~3500 events per two
    seconds. It is because pcgame_launch.py runs its own health watchdog for
    the duration of a game and can also tell JSM to re-enumerate afterwards,
    which this service cannot. Two of them reviving at once would just fight.
    """
    try:
        return subprocess.run(["pgrep", "-x", "JoyShockMapper"],
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL,
                              timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return True          # unsure: assume busy rather than interfere


def rebind():
    try:
        result = subprocess.run(["sudo", "-n", REBIND], capture_output=True,
                                timeout=25)
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def reopen_joysticks():
    """Make peripheral.joystick re-enumerate after a rebind.

    Without this Kodi holds a file descriptor for an input node that no longer
    exists -- lsof shows it as "(deleted)" -- and the pad is listed in Settings
    while doing nothing whatsoever. Toggling the addon is the lightest way to
    force it; restarting Kodi also works but is far more disruptive.
    """
    for enabled in (False, True):
        xbmc.executeJSONRPC(json.dumps({
            "jsonrpc": "2.0", "id": 1,
            "method": "Addons.SetAddonEnabled",
            "params": {"addonid": "peripheral.joystick", "enabled": enabled},
        }))
        if not enabled:
            time.sleep(2)


class Watchdog(object):
    def __init__(self):
        self.last_rebind = 0.0
        self.tries = 0
        self.reopens = 0

    def check(self, now):
        # Always, game or not: a descriptor left over from a destroyed device
        # reads as "(deleted)" and Kodi silently receives nothing from the pad
        # for the rest of the session. Re-enumerating only touches Kodi.
        pad = find_pad_node()
        if pad and not holds_live_pad_fd(pad):
            if self.reopens < MAX_TRIES:
                self.reopens += 1
                log("kodi has no live handle on %s -- re-enumerating "
                    "joysticks (attempt %d)" % (pad, self.reopens),
                    xbmc.LOGWARNING)
                reopen_joysticks()
            return
        self.reopens = 0

        if game_owns_controller():
            self.tries = 0
            return
        node = find_imu()
        if not node:
            self.tries = 0           # nothing connected; nothing to do
            self.reopens = 0
            return
        if is_streaming(node):
            if self.tries:
                log("controller is streaming again")
            self.tries = 0
            return
        if now - self.last_rebind < COOLDOWN:
            return
        if self.tries >= MAX_TRIES:
            return                   # rebinding is not helping; stay quiet
        self.tries += 1
        self.last_rebind = now
        log("controller is connected but silent -- rebinding (attempt %d)"
            % self.tries, xbmc.LOGWARNING)
        if not rebind():
            log("rebind failed; is /etc/sudoers.d/nintendo-rebind installed?",
                xbmc.LOGERROR)
            return
        # The rebind replaced the input nodes underneath Kodi.
        reopen_joysticks()
        log("re-enumerated joysticks after the rebind")


def main():
    monitor = xbmc.Monitor()
    watchdog = Watchdog()
    log("controller watchdog started")
    while not monitor.abortRequested():
        try:
            watchdog.check(time.monotonic())
        except Exception as exc:
            log("check failed: %s" % exc, xbmc.LOGERROR)
        if monitor.waitForAbort(POLL):
            break
    log("controller watchdog stopped")


if __name__ == "__main__":
    main()
