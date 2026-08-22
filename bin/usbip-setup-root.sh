#!/bin/bash
# One-off root setup for the USB/IP client side on this machine.
# Run once:   sudo ~/.local/bin/usbip-setup-root.sh
#
# Four things, none of which the Kodi add-on can do for itself:
#   1. install the usbip tools -- for the *running* kernel, see below
#   2. load vhci-hcd now, and on every boot
#   3. let the user run just the usbip binary without a password
#   4. prove it works by running usbip, rather than by finding the file
#
# The trap this exists to avoid: /usr/bin/usbip is only a wrapper script, from
# linux-tools-common. It execs /usr/lib/linux-tools/$(uname -r)/usbip and, when
# that is missing, prints a warning and exits 2. So the command can be present
# and executable and still not work. linux-tools-generic follows the GA kernel
# line, which is not necessarily the kernel you booted -- an HWE or a freshly
# upgraded kernel leaves the wrapper pointing at nothing.
set -euo pipefail

if [ "$EUID" -ne 0 ]; then
    echo "This needs root: sudo $0" >&2
    exit 1
fi

ASSUME_YES=0
for arg in "$@"; do
    case "$arg" in
        -y|--yes) ASSUME_YES=1 ;;
        -h|--help)
            echo "usage: sudo $0 [-y]"
            echo "  -y, --yes   install packages without asking"
            exit 0 ;;
        *) echo "unknown option: $arg" >&2; exit 1 ;;
    esac
done

USER_NAME="${SUDO_USER:-retro}"
KERNEL="$(uname -r)"
USBIP_BIN=/usr/bin/usbip

# The only honest test: run it.
usbip_works() {
    [ -x "$USBIP_BIN" ] && "$USBIP_BIN" version >/dev/null 2>&1
}

confirm() {
    [ "$ASSUME_YES" = 1 ] && return 0
    [ -t 0 ] || return 0          # non-interactive: they already typed sudo
    local reply
    read -r -p "  install $1? [Y/n] " reply || reply=y
    case "$reply" in [Nn]*) return 1 ;; *) return 0 ;; esac
}

apt_install() {
    DEBIAN_FRONTEND=noninteractive apt-get install -y "$@"
}

echo "== usbip tools =="
if usbip_works; then
    echo "  $USBIP_BIN ($("$USBIP_BIN" version 2>&1)) for kernel $KERNEL"
else
    if [ -x "$USBIP_BIN" ]; then
        echo "  $USBIP_BIN is present but will not run:"
        "$USBIP_BIN" version 2>&1 | sed "s/^/    /" || true
    else
        echo "  usbip is not installed"
    fi

    # linux-tools-common ships the wrapper, linux-tools-$KERNEL the real binary.
    WANT="linux-tools-common linux-tools-$KERNEL"
    if ! apt-cache show "linux-tools-$KERNEL" >/dev/null 2>&1; then
        echo "  apt does not know linux-tools-$KERNEL yet; refreshing lists"
        apt-get update -qq || true
    fi
    if ! apt-cache show "linux-tools-$KERNEL" >/dev/null 2>&1; then
        # A mainline or out-of-archive kernel has no matching tools package.
        echo "  no linux-tools-$KERNEL in the archive; trying linux-tools-generic"
        WANT="linux-tools-common linux-tools-generic"
    fi

    if ! confirm "$WANT"; then
        echo "  declined -- usbip cannot work without it" >&2
        exit 1
    fi
    apt_install $WANT || echo "  apt could not install: $WANT" >&2

    if ! usbip_works; then
        echo >&2
        echo "  usbip still does not run for kernel $KERNEL:" >&2
        "$USBIP_BIN" version 2>&1 | sed "s/^/    /" >&2 || true
        echo "  If the kernel was upgraded recently, reboot and run this again." >&2
        exit 1
    fi
    echo "  now working: $("$USBIP_BIN" version 2>&1)"
fi

echo "== ssh client =="
# The add-on drives the Pi over ssh; a minimal install may not have it.
if command -v ssh >/dev/null 2>&1; then
    echo "  present"
elif confirm "openssh-client" && apt_install openssh-client; then
    echo "  installed"
else
    echo "  WARNING: no ssh client, the Pi side cannot be controlled" >&2
fi

echo "== vhci-hcd module =="
# vhci-hcd is the client half of USB/IP: it presents the remote device as a
# local virtual USB port. usbip_host is the server half and is not needed here.
if grep -q "^vhci_hcd" /proc/modules; then
    echo "  already loaded"
elif modprobe vhci-hcd 2>/dev/null; then
    echo "  loaded"
else
    echo "  could not load vhci-hcd." >&2
    echo "  It ships in linux-modules-$KERNEL -- check that package is installed." >&2
    exit 1
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
