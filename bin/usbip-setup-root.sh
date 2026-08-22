#!/bin/bash
# One-off root setup for the USB/IP client side on this machine.
# Run once:   sudo ~/.local/bin/usbip-setup-root.sh
#
# Three things, none of which the Kodi add-on can do for itself:
#   1. load vhci-hcd now, and on every boot
#   2. let the retro user run just the usbip binary without a password
#   3. sanity-check that the tools are actually present
set -euo pipefail

if [ "$EUID" -ne 0 ]; then
    echo "This needs root: sudo $0" >&2
    exit 1
fi

USER_NAME="${SUDO_USER:-retro}"
USBIP_BIN="$(command -v usbip || echo /usr/bin/usbip)"

echo "== usbip binary =="
if [ ! -x "$USBIP_BIN" ]; then
    echo "usbip not found. Install it with:" >&2
    echo "  apt install linux-tools-generic linux-tools-\$(uname -r)" >&2
    exit 1
fi
echo "  $USBIP_BIN  ($("$USBIP_BIN" version 2>&1))"

echo "== vhci-hcd module =="
# vhci-hcd is the client half of USB/IP: it presents the remote device as a
# local virtual USB port. usbip_host is the server half and is not needed here.
if lsmod | grep -q '^vhci_hcd'; then
    echo "  already loaded"
else
    modprobe vhci-hcd
    echo "  loaded"
fi

echo "== load on boot =="
CONF=/etc/modules-load.d/usbip.conf
if [ -f "$CONF" ] && grep -q vhci-hcd "$CONF"; then
    echo "  $CONF already set"
else
    echo "vhci-hcd" > "$CONF"
    echo "  wrote $CONF"
fi

echo "== passwordless sudo for usbip only =="
# Deliberately narrow: attach/detach/port all need root, but nothing else does.
# This grants exactly the one binary, not blanket NOPASSWD.
SUDOERS=/etc/sudoers.d/usbip
NEW="$USER_NAME ALL=(root) NOPASSWD: $USBIP_BIN"
if [ -f "$SUDOERS" ] && [ "$(cat "$SUDOERS")" = "$NEW" ]; then
    echo "  $SUDOERS already set"
else
    # Validate before installing -- a malformed sudoers file locks out sudo.
    TMP="$(mktemp)"
    echo "$NEW" > "$TMP"
    if visudo -c -f "$TMP" >/dev/null; then
        install -m 0440 -o root -g root "$TMP" "$SUDOERS"
        echo "  wrote $SUDOERS"
    else
        echo "  REFUSED: generated sudoers line did not validate" >&2
        rm -f "$TMP"
        exit 1
    fi
    rm -f "$TMP"
fi

echo "== verify =="
if sudo -u "$USER_NAME" sudo -n "$USBIP_BIN" port >/dev/null 2>&1; then
    echo "  $USER_NAME can run 'sudo usbip' without a password"
else
    echo "  WARNING: passwordless sudo test failed" >&2
fi

echo
echo "Client side ready. The remaining step is on the Pi:"
echo "  ssh-copy-id -i /home/$USER_NAME/.ssh/id_ed25519_usbip.pub <piuser>@192.0.2.10"
