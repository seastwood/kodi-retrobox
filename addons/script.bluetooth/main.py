"""Pair Bluetooth controllers and headphones from the sofa.

Everything here is a full-screen Kodi dialog rather than a plugin listing,
because pairing is a conversation -- scan, choose, wait, be told what happened
-- and a directory of items cannot say "hold the pad's pair button now".
"""

import sys

import xbmc
import xbmcaddon
import xbmcgui

sys.path.insert(0, xbmcaddon.Addon().getAddonInfo("path"))

import bt_core

TITLE = "Bluetooth"
# BlueZ icon names, mapped to something worth reading on a television.
KINDS = {
    "input-gaming": "Controller",
    "input-gamepad": "Controller",
    "input-keyboard": "Keyboard",
    "input-mouse": "Mouse",
    "audio-card": "Speaker",
    "audio-headset": "Headset",
    "audio-headphones": "Headphones",
    "phone": "Phone",
    "computer": "Computer",
}


def kind_of(device):
    return KINDS.get(device.get("icon", ""), "Device")


def describe(device):
    """One line per device: what it is, and what it is doing."""
    state = ("Connected" if device["connected"]
             else "Paired" if device["paired"] else "Not paired")
    return "%s  -  %s, %s" % (device["name"], kind_of(device), state.lower())


def say(message, heading=TITLE):
    xbmcgui.Dialog().ok(heading, message)


def blocked():
    """Refuse to pretend, and say exactly what is wrong."""
    trouble = bt_core.problems()
    if not trouble:
        return False
    if trouble == ["The adapter is switched off"]:
        if xbmcgui.Dialog().yesno(TITLE, "Bluetooth is switched off.\n\n"
                                         "Turn it on now?"):
            if bt_core.power_on():
                return False
            say("Could not switch Bluetooth on.")
        return True
    say("\n".join(trouble) + "\n\nPlug a Bluetooth adapter in and try again."
        if "No Bluetooth adapter is attached" in trouble
        else "\n".join(trouble))
    return True


def scan_and_pair():
    progress = xbmcgui.DialogProgress()
    progress.create(TITLE, "Hold the pairing button on your device.\n"
                           "Looking for it now...")
    found = []
    try:
        # bluetoothctl blocks for the whole scan, so the bar cannot track real
        # progress; it is here so the screen is not simply frozen.
        progress.update(10)
        found = bt_core.scan()
        progress.update(100)
    finally:
        progress.close()

    if not found:
        say("Nothing new was found.\n\n"
            "Most controllers only appear while their pairing button is held "
            "down, and only for a few seconds.")
        return
    choices = ["%s  -  %s" % (d["name"], kind_of(d)) for d in found]
    picked = xbmcgui.Dialog().select("Pair with which device?", choices)
    if picked < 0:
        return
    device = found[picked]

    progress = xbmcgui.DialogProgress()
    progress.create(TITLE, "Pairing with %s..." % device["name"])
    try:
        ok, message = bt_core.pair(device["mac"])
    finally:
        progress.close()
    if not ok:
        say("%s\n\n%s" % (device["name"], message or "Pairing failed"))
        return
    say("%s is paired%s.\n\nIt will reconnect on its own from now on."
        % (device["name"], "" if not message else " (%s)" % message))


def device_menu(device):
    actions = []
    if device["connected"]:
        actions.append(("Disconnect", bt_core.disconnect))
    else:
        actions.append(("Connect", bt_core.connect))
    actions.append(("Forget this device", bt_core.forget))
    picked = xbmcgui.Dialog().select(device["name"], [a[0] for a in actions])
    if picked < 0:
        return
    label, action = actions[picked]
    if action is bt_core.forget and not xbmcgui.Dialog().yesno(
            TITLE, "Forget %s?\n\nIt will have to be paired again."
                   % device["name"]):
        return
    ok, message = action(device["mac"])
    if not ok:
        say(message or "%s failed" % label)


def known_menu():
    devices = bt_core.known_devices()
    if not devices:
        say("Nothing has been paired yet.\n\n"
            "Choose \"Pair a new device\" to add a controller.")
        return
    picked = xbmcgui.Dialog().select("Paired devices",
                                     [describe(d) for d in devices])
    if picked >= 0:
        device_menu(devices[picked])


def setup_menu():
    trouble = bt_core.problems()
    props = bt_core.adapter()
    lines = ["Bluetooth service: %s" %
             ("running" if "not running" not in " ".join(trouble) else "stopped")]
    if props:
        lines.append("Adapter: %s (%s)" % (props.get("Name", "?"),
                                           props.get("Address", "?")))
        lines.append("Powered: %s" % props.get("Powered", "?"))
    else:
        lines.append("Adapter: none attached")
    lines.append("")
    lines.append("Problems: " + ("none" if not trouble else "; ".join(trouble)))
    say("\n".join(lines), "Bluetooth setup")


def main():
    xbmc.log("script.bluetooth: opened", xbmc.LOGINFO)
    while True:
        options = ["Pair a new device", "Paired devices", "Check setup"]
        picked = xbmcgui.Dialog().select(TITLE, options)
        if picked < 0:
            return
        if picked == 2:
            setup_menu()
            continue
        if blocked():
            continue
        if picked == 0:
            scan_and_pair()
        else:
            known_menu()


if __name__ == "__main__":
    main()
