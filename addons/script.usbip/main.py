# -*- coding: utf-8 -*-
"""USB/IP front end for Kodi.

Attaches USB devices shared by another machine so they appear here as if they
were plugged in directly -- which is the point for controllers: once attached,
JoyShockMapper and Kodi both just see an ordinary USB pad.

Stripped down from usb-audio-ip-client (github.com/seastwood/usb-audio-ip-client),
keeping the usbip half and dropping the PipeWire audio half and the Qt UI.
Everything here is Kodi dialogs, so it navigates with the controller.

The reattach service (service.py) is what puts devices back after a server
reboot or a dropped link; this screen is for choosing what it should keep.
"""

import os
import sys

import xbmc
import xbmcgui

# Kodi does not guarantee the addon directory is importable for a script, so
# put it on the path before reaching for the shared command layer.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import usbip_core as U

TITLE = "USB over IP"


def dlg():
    return xbmcgui.Dialog()


def choose(heading, rows, preselect=-1):
    items = [xbmcgui.ListItem(label=r[0], label2=r[1]) for r in rows]
    index = dlg().select(heading, items, useDetails=True, preselect=preselect)
    return None if index < 0 else index


def notify(message, error=False):
    dlg().notification(TITLE, message,
                       xbmcgui.NOTIFICATION_ERROR if error
                       else xbmcgui.NOTIFICATION_INFO, 4000)


def busy(message):
    """usbip calls block for a few seconds; say so rather than looking hung."""
    progress = xbmcgui.DialogProgressBG()
    progress.create(TITLE, message)
    return progress


# ---------------------------------------------------------------------------
# hosts
# ---------------------------------------------------------------------------

def hosts_screen():
    index = 0
    while True:
        config = U.load_config()
        rows = [("Add a server...", "", None)]
        for host in config["hosts"]:
            rows.append((host.get("label") or host["ip"],
                         "%s@%s" % (host.get("user", "?"), host["ip"]), None))
        index = choose("Servers", rows, index)
        if index is None:
            return
        if index == 0:
            if add_host():
                notify("Server added")
            continue
        host_menu(config["hosts"][index - 1])


def add_host(existing=None):
    existing = existing or {}
    ip = dlg().input("Step 1 of 3  --  server IP or hostname",
                     existing.get("ip", ""),
                     type=xbmcgui.INPUT_ALPHANUM)
    if not ip:
        return False
    user = dlg().input("Step 2 of 3  --  username to ssh in as",
                       existing.get("user", "pi"),
                       type=xbmcgui.INPUT_ALPHANUM)
    if not user:
        return False
    label = dlg().input("Step 3 of 3  --  a name for this server",
                        existing.get("label", ""),
                        type=xbmcgui.INPUT_ALPHANUM) or ip

    # Store the address, not the name -- see resolve_host() for why a hostname
    # here would quietly break the reattach service.
    resolved, all_ips, error = U.resolve_host(ip.strip())
    if error:
        notify(error, error=True)
        return False
    if len(all_ips) > 1:
        chosen = dlg().select(
            "%s has %d addresses -- which one?" % (ip.strip(), len(all_ips)),
            all_ips)
        if chosen < 0:
            return False
        resolved = all_ips[chosen]

    config = U.load_config()
    entry = {"label": label, "ip": resolved, "user": user.strip()}
    for i, host in enumerate(config["hosts"]):
        if host["ip"] == entry["ip"]:
            config["hosts"][i] = entry
            break
    else:
        config["hosts"].append(entry)
    U.save_config(config)
    return True


PROMPTS = {
    "ip": ("Address", "IP address or hostname of the server"),
    "user": ("Username", "the account to ssh in as"),
    "label": ("Name", "what to call it in this list"),
}


def current_host(ip):
    for host in U.load_config()["hosts"]:
        if host["ip"] == ip:
            return host
    return None


def edit_host_field(host, field):
    """Change one field of a server, leaving the others alone."""
    title, hint = PROMPTS[field]
    value = dlg().input("%s  --  %s" % (title, hint), host.get(field, ""),
                        type=xbmcgui.INPUT_ALPHANUM)
    if not value or value.strip() == host.get(field, ""):
        return False
    value = value.strip()

    config = U.load_config()
    entry = None
    for candidate in config["hosts"]:
        if candidate["ip"] == host["ip"]:
            entry = candidate
    if entry is None:
        return False

    if field == "ip":
        # Stored as an address, never a name: "usbip port" reports back the IP
        # that attach connected to, and a config holding a hostname would never
        # match it. See resolve_host().
        resolved, all_ips, error = U.resolve_host(value)
        if error:
            notify(error, error=True)
            return False
        if len(all_ips) > 1:
            chosen = dlg().select("%s has %d addresses -- which one?"
                                  % (value, len(all_ips)), all_ips)
            if chosen < 0:
                return False
            resolved = all_ips[chosen]
        old_ip = entry["ip"]
        entry["ip"] = resolved
        # Anything set to reattach automatically points at the old address.
        for auto in config["auto"]:
            if auto.get("ip") == old_ip:
                auto["ip"] = resolved
    else:
        entry[field] = value
        if field == "user":
            for auto in config["auto"]:
                if auto.get("ip") == entry["ip"]:
                    auto["user"] = value

    U.save_config(config)
    notify("%s set to %s" % (title, entry.get(field, value)))
    return True


def host_menu(host):
    while True:
        rows = [("Devices on %s" % (host.get("label") or host["ip"]),
                 "attach or detach", ("devices",)),
                ("What it is already sharing", "no login needed", ("exported",)),
                ("--  CONNECTION  --", "", ("nop",)),
                ("Address", host.get("ip", ""), ("field", "ip")),
                ("Username", host.get("user", ""), ("field", "user")),
                ("Name", host.get("label", ""), ("field", "label")),
                ("--  --", "", ("nop",)),
                ("Check this server", "ssh, usbip, sudo", ("check",)),
                ("Restart usbipd on it", "when it stops responding",
                 ("restart",)),
                ("Remove this server", "", ("remove",))]
        index = choose(host.get("label") or host["ip"], rows)
        if index is None:
            return
        action = rows[index][2][0]
        if action == "devices":
            devices_screen(host)
        elif action == "exported":
            exported_screen(host)
        elif action == "check":
            check_screen(host)
        elif action == "restart":
            progress = busy("Restarting usbipd on %s" % host["ip"])
            error = U.restart_usbipd(host["ip"], host["user"])
            progress.close()
            notify(error or "usbipd restarted", error=bool(error))
        elif action == "nop":
            continue
        elif action == "field":
            if edit_host_field(host, rows[index][2][1]):
                host = current_host(host["ip"]) or host
            continue
        elif action == "remove":
            if dlg().yesno(TITLE, "Remove %s?" % (host.get("label")
                                                  or host["ip"])):
                config = U.load_config()
                config["hosts"] = [h for h in config["hosts"]
                                   if h["ip"] != host["ip"]]
                config["auto"] = [a for a in config["auto"]
                                  if a["ip"] != host["ip"]]
                U.save_config(config)
                notify("Removed")
                return


# ---------------------------------------------------------------------------
# devices
# ---------------------------------------------------------------------------

def devices_screen(host):
    index = 0
    while True:
        progress = busy("Asking %s what is plugged in" % host["ip"])
        devices, error = U.list_remote(host["ip"], host["user"])
        here, _err = U.attached()
        progress.close()
        if error:
            notify(error, error=True)
            return
        if not devices:
            notify("No USB devices on %s" % host["ip"])
            return

        config = U.load_config()
        auto = set(U.auto_key(a["ip"], a["busid"]) for a in config["auto"])
        mine = dict((d["busid"], d) for d in here if d["host"] == host["ip"])

        rows = []
        for device in devices:
            state = []
            if device["busid"] in mine:
                state.append("ATTACHED")
            if U.auto_key(host["ip"], device["busid"]) in auto:
                state.append("auto")
            rows.append((device["description"] or device["busid"],
                         "%s   %s" % (device["busid"], " - ".join(state)),
                         device))
        index = choose("Devices on %s" % (host.get("label") or host["ip"]),
                       rows, index)
        if index is None:
            return
        device_menu(host, rows[index][2], rows[index][2]["busid"] in mine,
                    mine.get(rows[index][2]["busid"]))


def device_menu(host, device, is_attached, port_entry):
    name = device["description"] or device["busid"]
    config = U.load_config()
    key = U.auto_key(host["ip"], device["busid"])
    is_auto = any(U.auto_key(a["ip"], a["busid"]) == key
                  for a in config["auto"])

    rows = []
    if is_attached:
        rows.append(("Detach", "release it back to %s" % host["ip"],
                     ("detach",)))
    else:
        rows.append(("Attach", "use it here", ("attach",)))
    rows.append(("Reattach automatically",
                 "on" if is_auto else "off", ("auto",)))
    # Detaching leaves the device shared for everyone else; this is how to
    # take it off the network on purpose.
    rows.append(("Stop sharing", "give it back to %s" % host["ip"],
                 ("unexport",)))
    rows.append(("Details", "%s   %s" % (device["busid"], device["vidpid"]),
                 ("nop",)))
    index = choose(name, rows)
    if index is None:
        return
    action = rows[index][2][0]

    if action == "attach":
        progress = busy("Attaching %s" % name)
        error = U.attach(host["ip"], host["user"], device["busid"])
        progress.close()
        notify(error or "%s attached" % name, error=bool(error))
    elif action == "detach":
        progress = busy("Detaching %s" % name)
        error = U.detach(port_entry["port"], host["ip"], host["user"],
                         device["busid"])
        progress.close()
        notify(error or "%s detached" % name, error=bool(error))
    elif action == "unexport":
        if dlg().yesno(TITLE, "Stop sharing %s?\n\n"
                              "No machine will be able to attach it until it "
                              "is shared again." % name):
            progress = busy("Releasing %s" % name)
            error = U.unexport(host["ip"], host["user"], device["busid"])
            progress.close()
            notify(error or "%s is no longer shared" % name, error=bool(error))
    elif action == "auto":
        config = U.load_config()
        if is_auto:
            config["auto"] = [a for a in config["auto"]
                              if U.auto_key(a["ip"], a["busid"]) != key]
            notify("Will not reattach automatically")
        else:
            config["auto"].append({"ip": host["ip"], "user": host["user"],
                                   "busid": device["busid"], "name": name})
            notify("Will reattach automatically")
        U.save_config(config)


def attached_screen():
    index = 0
    while True:
        progress = busy("Reading attached devices")
        here, error = U.attached()
        progress.close()
        if error:
            notify(error, error=True)
            return
        if not here:
            notify("Nothing is attached right now")
            return
        rows = [(d["description"] or d["busid"],
                 "port %s   from %s   %s" % (d["port"], d["host"], d["busid"]),
                 d) for d in here]
        index = choose("Attached devices", rows, index)
        if index is None:
            return
        entry = rows[index][2]
        if dlg().yesno(TITLE, "Detach %s?"
                       % (entry["description"] or entry["busid"])):
            config = U.load_config()
            user = None
            for host in config["hosts"]:
                if host["ip"] == entry["host"]:
                    user = host["user"]
            progress = busy("Detaching")
            error = U.detach(entry["port"], entry["host"], user,
                             entry["busid"])
            progress.close()
            notify(error or "Detached", error=bool(error))


def exported_screen(host):
    """What the server currently has bound. Straight from usbipd on port 3240,
    so it works even when ssh or sudo are not set up yet."""
    progress = busy("Asking usbipd on %s" % host["ip"])
    devices, error = U.list_exported(host["ip"])
    progress.close()
    if error:
        notify(error, error=True)
        return
    if not devices:
        dlg().ok(TITLE, "%s is reachable but is not sharing anything right "
                        "now.\n\nThat is normal -- a device is only shared "
                        "while it is attached from here." % host["ip"])
        return
    text = "\n".join("%-10s %s" % (d["busid"], d["description"])
                     for d in devices)
    dlg().textviewer("Shared by %s" % host["ip"], text, usemono=True)


# ---------------------------------------------------------------------------
# diagnostics
# ---------------------------------------------------------------------------

def check_screen(host=None):
    progress = busy("Checking")
    lines = ["This machine (the client)", ""]
    problems = U.check_client()
    lines += ["   OK"] if not problems else ["   %s" % p for p in problems]
    if host:
        lines += ["", "%s (the server)" % host["ip"], ""]
        problems = U.check_host(host["ip"], host["user"])
        lines += ["   OK"] if not problems else ["   %s" % p for p in problems]
    progress.close()
    lines += ["", "", "Setup, if something above is missing:", "",
              "  On this machine:",
              "     sudo ~/.local/bin/usbip-setup-root.sh", "",
              "  On the server, once:",
              "     ssh-copy-id -i ~/.ssh/id_ed25519_usbip.pub USER@HOST",
              "     and give it passwordless sudo for usbip"]
    dlg().textviewer(TITLE, "\n".join(lines), usemono=True)


def main():
    index = 0
    while True:
        config = U.load_config()
        auto = len(config["auto"])
        rows = [
            ("Servers", "%d configured" % len(config["hosts"]), None),
            ("Attached devices", "what is plugged in over the network", None),
            ("Automatic reattach", "%d device%s" % (auto,
                                                    "" if auto == 1 else "s"),
             None),
            ("Check setup", "is everything in place", None),
        ]
        index = choose(TITLE, rows, index)
        if index is None:
            return
        if index == 0:
            hosts_screen()
        elif index == 1:
            attached_screen()
        elif index == 2:
            auto_screen()
        else:
            check_screen()


def auto_screen():
    index = 0
    while True:
        config = U.load_config()
        if not config["auto"]:
            dlg().ok(TITLE, "Nothing is set to reattach automatically.\n\n"
                            "Pick a device under Servers and turn on "
                            "\"Reattach automatically\".")
            return
        rows = [(a.get("name") or a["busid"],
                 "%s   %s" % (a["ip"], a["busid"]), a)
                for a in config["auto"]]
        index = choose("Reattached automatically", rows, index)
        if index is None:
            return
        entry = rows[index][2]
        if dlg().yesno(TITLE, "Stop reattaching %s automatically?"
                       % (entry.get("name") or entry["busid"])):
            config["auto"] = [
                a for a in config["auto"]
                if U.auto_key(a["ip"], a["busid"])
                != U.auto_key(entry["ip"], entry["busid"])]
            U.save_config(config)
            notify("Removed")


if __name__ == "__main__":
    main()
