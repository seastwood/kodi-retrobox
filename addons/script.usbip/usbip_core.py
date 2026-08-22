# -*- coding: utf-8 -*-
"""USB/IP command layer, shared by the Kodi screen and the reattach service.

This is the part carried over from usb-audio-ip-client: the same four usbip
calls and the same output parsing, with paramiko swapped for the ssh CLI
(Kodi's Python has no paramiko) and passwords swapped for a key.

Which side runs what:

    server (the Pi, over ssh)   usbip list -l        what is plugged in
                                usbip bind -b BUSID  export it
                                usbip unbind -b ...  stop exporting

    client (this machine)       usbip attach -r H -b BUSID
                                usbip port           what is attached
                                usbip detach -p N

Every client call needs root, which is why /etc/sudoers.d/usbip exists; see
usbip-setup-root.sh.
"""

import json
import os
import re
import subprocess

HOME = os.path.expanduser("~")
SSH_KEY = os.path.join(HOME, ".ssh", "id_ed25519_usbip")
CONFIG_DIR = os.path.join(HOME, ".config", "usbip-kodi")
CONFIG = os.path.join(CONFIG_DIR, "config.json")
USBIP = "/usr/bin/usbip"

SSH_OPTS = [
    "-i", SSH_KEY,
    "-o", "BatchMode=yes",              # never block on a password prompt
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "ConnectTimeout=5",
    "-o", "ServerAliveInterval=3",
    "-o", "ServerAliveCountMax=2",
]

TIMEOUT = 20


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

def load_config():
    """{"hosts": [{"label","ip","user"}], "auto": [{"ip","user","busid"}]}"""
    try:
        with open(CONFIG) as handle:
            data = json.load(handle)
    except (IOError, OSError, ValueError):
        data = {}
    data.setdefault("hosts", [])
    data.setdefault("auto", [])
    return data


def save_config(data):
    if not os.path.isdir(CONFIG_DIR):
        os.makedirs(CONFIG_DIR)
    tmp = CONFIG + ".tmp"
    with open(tmp, "w") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    os.replace(tmp, CONFIG)          # atomic: the service reads this too


def auto_key(host, busid):
    return "%s/%s" % (host, busid)


def resolve_host(name):
    """(ip, all_ips, error) for a hostname or IP.

    Hosts are stored as IP addresses on purpose. "usbip attach -r NAME" records
    whatever NAME resolved to, and "usbip port" then reports that IP back -- so
    a config holding a hostname never matches what is actually attached, and
    the reattach service would try to attach a device it already has. This box
    resolves raspberrypi.local to two different addresses on alternate lookups
    (one Pi, two IPs on one NIC), which makes that failure the normal case
    rather than a corner case.
    """
    import socket
    try:
        socket.inet_aton(name)
        return name, [name], None            # already an IP, nothing to do
    except (socket.error, OSError):
        pass
    try:
        infos = socket.getaddrinfo(name, None, socket.AF_INET)
    except (socket.gaierror, OSError) as exc:
        return None, [], "could not resolve %s: %s" % (name, exc)
    ips = []
    for info in infos:
        ip = info[4][0]
        if ip not in ips:
            ips.append(ip)
    if not ips:
        return None, [], "could not resolve %s" % name
    return ips[0], ips, None


# ---------------------------------------------------------------------------
# running commands
# ---------------------------------------------------------------------------

def run(argv, timeout=TIMEOUT):
    """(rc, stdout, stderr). Never raises -- a dead host is normal here."""
    try:
        proc = subprocess.run(argv, capture_output=True, timeout=timeout)
        return (proc.returncode,
                proc.stdout.decode("utf-8", "replace"),
                proc.stderr.decode("utf-8", "replace"))
    except subprocess.TimeoutExpired:
        return 124, "", "timed out after %ss" % timeout
    except OSError as exc:
        return 127, "", str(exc)


def ssh(host, user, command, timeout=TIMEOUT):
    return run(["ssh"] + SSH_OPTS + ["%s@%s" % (user, host), command], timeout)


def sudo_usbip(*args, **kwargs):
    return run(["sudo", "-n", USBIP] + list(args), kwargs.get("timeout", TIMEOUT))


def have_key():
    return os.path.exists(SSH_KEY)


def check_client():
    """What is missing on this side, as a list of human-readable problems."""
    problems = []
    if not os.path.exists(USBIP):
        problems.append("usbip is not installed")
    if not have_key():
        problems.append("no ssh key at %s" % SSH_KEY)
    rc, _out, _err = run(["sudo", "-n", USBIP, "port"], timeout=10)
    if rc == 127:
        problems.append("usbip could not be run at all")
    elif rc != 0:
        problems.append("sudo usbip needs a password -- run usbip-setup-root.sh")
    try:
        with open("/proc/modules") as handle:
            if "vhci_hcd" not in handle.read():
                problems.append("vhci-hcd module is not loaded")
    except (IOError, OSError):
        pass
    return problems


def check_host(host, user):
    """Same for the server side. Empty list means it is ready."""
    rc, out, err = ssh(host, user, "command -v usbip || true", timeout=10)
    if rc != 0:
        return ["cannot ssh to %s@%s: %s" % (user, host,
                                             (err or "").strip() or "rc %d" % rc)]
    if not out.strip():
        return ["usbip is not installed on %s" % host]
    rc, out, _err = ssh(host, user, "sudo -n usbip list -l >/dev/null 2>&1 "
                                    "&& echo ok || echo no", timeout=10)
    if "ok" not in out:
        return ["%s needs passwordless sudo for usbip" % host]
    return []


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------

BUSID_RE = re.compile(r"^\s*-\s*busid\s+(\S+)\s+\(([0-9a-fA-F]{4}:[0-9a-fA-F]{4})\)")
PORT_RE = re.compile(r"^Port\s+(\d+):")
# The line the original parsed: "6-1 -> usbip://192.0.2.10:3240/1-1.1"
IMPORT_RE = re.compile(r"->\s*usbip://([^:/]+):\d+/(\S+)")


def parse_list(text):
    """usbip list -l output -> [{busid, vidpid, description}].

    Format is a "- busid X (vvvv:pppp)" line followed by an indented
    "Vendor : Product (vvvv:pppp)" line, then further indented detail lines
    which are of no use on a TV.
    """
    devices = []
    for line in text.splitlines():
        match = BUSID_RE.match(line)
        if match:
            devices.append({"busid": match.group(1),
                            "vidpid": match.group(2),
                            "description": ""})
        elif devices and not devices[-1]["description"]:
            stripped = line.strip()
            if stripped and not stripped.startswith(":"):
                # Drop the trailing "(vvvv:pppp)" -- it is already the vidpid.
                devices[-1]["description"] = re.sub(
                    r"\s*\([0-9a-fA-F]{4}:[0-9a-fA-F]{4}\)\s*$", "", stripped)
    return devices


# "usbip list -r" formats each device differently from "-l": there is no
# "busid" keyword, just "1-1.3: Vendor : Product (vvvv:pppp)".
REMOTE_RE = re.compile(
    r"^\s*(\S+):\s*(.*?)\s*\(([0-9a-fA-F]{4}:[0-9a-fA-F]{4})\)\s*$")


def parse_remote(text):
    """usbip list -r output -> [{busid, vidpid, description}].

    This is what the server has actually exported, and it comes straight from
    the daemon on port 3240 -- no ssh and no root on either side. Useful on its
    own as a reachability check.
    """
    devices = []
    for line in text.splitlines():
        if line.strip().startswith(":"):
            continue                      # indented detail lines
        match = REMOTE_RE.match(line)
        if match and "/" not in match.group(1):
            devices.append({"busid": match.group(1),
                            "description": match.group(2),
                            "vidpid": match.group(3)})
    return devices


def list_exported(host):
    """Devices the server is already sharing. (devices, error)."""
    rc, out, err = run([USBIP, "list", "-r", host], timeout=10)
    if rc != 0:
        return [], (err.strip() or "could not reach usbipd on %s" % host)
    return parse_remote(out), None


def parse_ports(text):
    """usbip port output -> [{port, host, busid, description}]."""
    attached = []
    port = None
    description = ""
    for line in text.splitlines():
        match = PORT_RE.match(line.strip())
        if match:
            port = match.group(1)
            description = ""
            continue
        if port is None:
            continue
        found = IMPORT_RE.search(line)
        if found:
            attached.append({"port": port,
                             "host": found.group(1),
                             "busid": found.group(2),
                             "description": description})
            port = None
            continue
        stripped = line.strip()
        if stripped and not description and not stripped.startswith("->"):
            description = re.sub(
                r"\s*\([0-9a-fA-F]{4}:[0-9a-fA-F]{4}\)\s*$", "", stripped)
    return attached


# ---------------------------------------------------------------------------
# operations
# ---------------------------------------------------------------------------

def list_remote(host, user):
    """(devices, error). Devices are what is physically on the server."""
    rc, out, err = ssh(host, user, "sudo -n usbip list -l")
    if rc != 0:
        return [], (err.strip() or "could not list devices on %s" % host)
    return parse_list(out), None


def attached():
    rc, out, err = sudo_usbip("port")
    if rc != 0:
        return [], (err.strip() or "could not read attached devices")
    return parse_ports(out), None


def attach(host, user, busid):
    """Export on the server, then import here. Returns None on success.

    The unbind before bind is the force-attach from the original app: a device
    left bound by a previous session refuses to bind again, and unbind on an
    unbound device is harmless, so it is always safe to lead with it.
    """
    ssh(host, user, "sudo -n usbip unbind -b %s" % busid)
    rc, _out, err = ssh(host, user, "sudo -n usbip bind -b %s" % busid)
    if rc != 0 and "already bound" not in (err or ""):
        return "bind failed on %s: %s" % (host, err.strip() or "rc %d" % rc)
    rc, _out, err = sudo_usbip("attach", "-r", host, "-b", busid)
    if rc != 0:
        return "attach failed: %s" % (err.strip() or "rc %d" % rc)
    return None


def detach(port, host=None, user=None, busid=None):
    """Release it here, and leave it exported so somebody else can take it.

    This used to unbind on the server, which took the device away from every
    other client as well: unbind hands it back to the server's own driver, so
    the next machine that wants it cannot attach it at all without an ssh
    login to bind it again. Detaching is "I have finished with it", not "stop
    sharing it" -- that second thing is unexport() below, and it is a separate
    choice on the screen.

    Re-exporting rather than simply leaving it bound is deliberate: usbipd can
    leave a device reading as in-use once its client has gone, and unbind then
    bind is the same clean cycle attach() already relies on.
    """
    rc, _out, err = sudo_usbip("detach", "-p", str(port))
    if rc != 0:
        return "detach failed: %s" % (err.strip() or "rc %d" % rc)
    if host and user and busid:
        ssh(host, user, "sudo -n usbip unbind -b %s" % busid)
        rc, _out, err = ssh(host, user, "sudo -n usbip bind -b %s" % busid)
        if rc != 0 and "already bound" not in (err or ""):
            return ("detached here, but %s could not share it again: %s"
                    % (host, err.strip() or "rc %d" % rc))
    return None


def unexport(host, user, busid):
    """Stop sharing a device altogether, giving it back to the server.

    The counterpart to detach(): nobody on the network can attach it after
    this, and the server can use it itself again.
    """
    rc, _out, err = ssh(host, user, "sudo -n usbip unbind -b %s" % busid)
    if rc != 0 and "not bound" not in (err or ""):
        return "could not stop sharing on %s: %s" % (host, err.strip() or "rc %d" % rc)
    return None


def restart_usbipd(host, user):
    """The server daemon does wedge -- the original app had a button for this
    for exactly that reason."""
    rc, _out, err = ssh(host, user, "sudo -n systemctl restart usbipd")
    return None if rc == 0 else (err.strip() or "restart failed")
