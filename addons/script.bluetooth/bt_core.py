"""Driving BlueZ from Kodi, through bluetoothctl.

bluetoothctl rather than the D-Bus API on purpose: Kodi's bundled Python has
no dbus module, and pairing needs an agent registered to answer BlueZ's
pairing requests -- bluetoothctl brings its own. `/usr/share/dbus-1/system.d/
bluetooth.conf` ends with a default-context rule allowing anyone to
send_destination org.bluez, so none of this needs root or the bluetooth group.
"""

import re
import subprocess

BLUETOOTHCTL = "/usr/bin/bluetoothctl"
# A pad that is not already in pairing mode will not show up in a short scan.
SCAN_SECONDS = 20

DEVICE_LINE = re.compile(r"^Device\s+([0-9A-F:]{17})\s*(.*)$", re.I)


def bctl(args, timeout=30):
    """Run one bluetoothctl command. Returns (ok, text)."""
    try:
        done = subprocess.run([BLUETOOTHCTL] + list(args),
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              timeout=timeout)
    except FileNotFoundError:
        return False, "bluetoothctl is not installed"
    except subprocess.TimeoutExpired:
        return False, "bluetoothctl did not finish in time"
    except OSError as exc:
        return False, str(exc)
    return done.returncode == 0, done.stdout.decode("utf-8", "replace")


def parse_props(text):
    """The `Key: value` block bluetoothctl prints for `show` and `info`."""
    props = {}
    for line in text.splitlines():
        key, sep, value = line.strip().partition(":")
        if sep and not key.startswith("Device "):
            props.setdefault(key.strip(), value.strip())
    return props


def adapter():
    """The Bluetooth adapter, or None when there is no hardware attached.

    "No default controller available" is what bluetoothctl says both when the
    dongle is unplugged and when it has fallen off the USB bus mid-session,
    which is a thing this particular dongle does.
    """
    ok, text = bctl(["show"])
    if not ok or "No default controller" in text:
        return None
    props = parse_props(text)
    match = re.search(r"Controller\s+([0-9A-F:]{17})", text, re.I)
    if match:
        props["Address"] = match.group(1)
    return props if props.get("Address") else None


def powered(props):
    return (props or {}).get("Powered", "no").lower() == "yes"


def power_on():
    return bctl(["power", "on"])[0]


def parse_devices(text):
    """[(mac, name)] from `bluetoothctl devices`."""
    out = []
    for line in text.splitlines():
        match = DEVICE_LINE.match(line.strip())
        if match:
            mac = match.group(1).upper()
            out.append((mac, match.group(2).strip() or mac))
    return out


def device_info(mac):
    ok, text = bctl(["info", mac])
    props = parse_props(text) if ok else {}
    return {
        "mac": mac,
        "name": props.get("Name") or props.get("Alias") or mac,
        "paired": props.get("Paired", "no").lower() == "yes",
        "trusted": props.get("Trusted", "no").lower() == "yes",
        "connected": props.get("Connected", "no").lower() == "yes",
        "icon": props.get("Icon", ""),
    }


def known_devices():
    """Everything the adapter remembers, most useful first."""
    ok, text = bctl(["devices"])
    if not ok:
        return []
    out = [device_info(mac) for mac, _name in parse_devices(text)]
    out.sort(key=lambda d: (not d["connected"], not d["paired"],
                            d["name"].lower()))
    return out


def scan(seconds=SCAN_SECONDS):
    """Discover devices. Returns everything seen that is not paired yet."""
    bctl(["--timeout", str(seconds), "scan", "on"], timeout=seconds + 15)
    return [d for d in known_devices() if not d["paired"]]


# What BlueZ says, and what it actually means to someone holding a controller.
PAIR_ERRORS = [
    ("AlreadyExists", "That device is already paired"),
    ("AuthenticationFailed", "The device refused the pairing"),
    ("AuthenticationCanceled", "Pairing was cancelled"),
    ("AuthenticationTimeout", "The device stopped responding"),
    ("ConnectionAttemptFailed", "Could not connect - is it still in pairing mode?"),
    ("Failed to pair", "Pairing failed"),
    ("not available", "The device is no longer in range"),
]


def explain(text):
    for marker, message in PAIR_ERRORS:
        if marker.lower() in text.lower():
            return message
    return None


def pair(mac):
    """Pair, trust and connect, which is what a person means by "pair".

    Trusting matters as much as pairing: without it BlueZ will not accept the
    controller's own reconnection when it is switched on later, and the pad
    looks broken until someone opens this screen again.
    """
    ok, text = bctl(["pair", mac], timeout=60)
    if not ok and "AlreadyExists" not in text:
        return False, explain(text) or "Pairing failed"
    bctl(["trust", mac])
    ok, text = bctl(["connect", mac], timeout=45)
    if not ok:
        # Paired but not connected is still progress: many pads connect on
        # their own the next time they are switched on.
        return True, explain(text) or "Paired, but it did not connect yet"
    return True, None


def connect(mac):
    ok, text = bctl(["connect", mac], timeout=45)
    return ok, None if ok else (explain(text) or "Could not connect")


def disconnect(mac):
    ok, text = bctl(["disconnect", mac], timeout=30)
    return ok, None if ok else "Could not disconnect"


def forget(mac):
    ok, text = bctl(["remove", mac], timeout=30)
    return ok, None if ok else "Could not remove that device"


def problems():
    """Everything standing between here and pairing something, in order."""
    out = []
    ok, text = bctl(["--version"], timeout=10)
    if not ok:
        out.append("bluetoothctl is missing or will not run")
        return out
    try:
        active = subprocess.run(["systemctl", "is-active", "bluetooth"],
                                stdout=subprocess.PIPE,
                                timeout=10).stdout.decode().strip()
    except (OSError, subprocess.TimeoutExpired):
        active = "unknown"
    if active != "active":
        out.append("The bluetooth service is not running (%s)" % active)
    props = adapter()
    if props is None:
        out.append("No Bluetooth adapter is attached")
    elif not powered(props):
        out.append("The adapter is switched off")
    return out
