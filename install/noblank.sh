#!/bin/sh
# Keep the television awake, and never ask anybody to log in again.
#
#   install/noblank.sh [--home PATH] [--dry-run]
#
# This is a console. It is plugged into a television, it is driven from a
# controller across the room, and the one thing it must never do is put up a
# password box that only a keyboard can answer. Four separate things here
# wanted to do exactly that:
#
#   * light-locker, which comes with LightDM and is started for every session
#     out of /etc/xdg/autostart. It blanks the screen and then demands a
#     password. On a machine with no keyboard in the room that is the end of
#     the evening.
#
#   * xfce4-power-manager, which drives DPMS. Out of the box it stands the
#     monitor by after ten minutes and switches it off after fifteen. A
#     television that has been switched off by DPMS looks exactly like one
#     that has crashed, which is how this was reported: "the screen goes
#     black".
#
#   * The X server's own screen saver, ten minutes, independently of both.
#
#   * xscreensaver, if it is ever installed, for the same reason as the first.
#
# Turning DPMS off at the server with xset is not enough on its own, because
# xfce4-power-manager sets the timeouts back whenever it feels like it. Both
# ends have to agree, so this does both and writes the autostart entry that
# makes it true again at the next login.
#
# Nothing here needs root. All of it is this user's own session, which is the
# right scope anyway: the next person to log in on a shared machine keeps
# their locker.
#
# Logging in at the console is already unnecessary -- LightDM is set to log
# this user straight in -- so a machine that is switched on arrives at Kodi
# with nothing asked of it. That part is the installer's, not this script's;
# this is only about staying there.
#
# --home writes somewhere else and touches no running session at all. That is
# how the tests exercise this without a machine.
set -u

HOME_DIR="${HOME:-/root}"
DRY=0
LIVE=1

while [ $# -gt 0 ]; do
  case "$1" in
    --home) HOME_DIR="$2"; LIVE=0; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) sed -n '2,4p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

AUTOSTART="$HOME_DIR/.config/autostart"
did=0

note() { printf '   %s\n' "$*"; }

# A .desktop that exists only to countermand one in /etc/xdg/autostart. The
# name has to match the system file exactly, or it overrides nothing.
hide() {
  name="$1"
  label="$2"
  target="$AUTOSTART/$name"
  if [ "$DRY" = 1 ]; then
    note "would switch off $label ($name)"
    return
  fi
  mkdir -p "$AUTOSTART" || return
  cat > "$target" <<ENTRY
[Desktop Entry]
Type=Application
Name=$label
Exec=/bin/true
NoDisplay=true
Hidden=true
X-GNOME-Autostart-enabled=false
ENTRY
  note "switched off $label"
  did=$((did + 1))
}

hide light-locker.desktop "Screen Locker"
hide xscreensaver.desktop "Screensaver"

# And one that runs. xset is not persistent -- it is a request to the running
# server, and the next server knows nothing about it -- so it has to be made
# again every time somebody logs in.
if [ "$DRY" = 1 ]; then
  note "would add the autostart entry that turns blanking off at login"
else
  mkdir -p "$AUTOSTART"
  cat > "$AUTOSTART/retrobox-noblank.desktop" <<ENTRY
[Desktop Entry]
Type=Application
Name=Keep the television awake
Comment=Turns off the X screen saver and DPMS, which blank a television that is only being watched
Exec=sh -c "xset s off -dpms s noblank"
NoDisplay=true
X-GNOME-Autostart-enabled=true
ENTRY
  note "blanking will be turned off at every login"
  did=$((did + 1))
fi

# xfce4-power-manager, which is the one that puts the timeouts back.
if [ "$DRY" = 1 ]; then
  note "would tell xfce4-power-manager to leave the monitor alone"
elif command -v xfconf-query >/dev/null 2>&1 && [ "$LIVE" = 1 ]; then
  # Over SSH there is no session bus in the environment, but there is one on
  # the machine and this user owns it. Without this every setting below is
  # written to a bus that does not exist and quietly does nothing.
  if [ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ] && [ -S "/run/user/$(id -u)/bus" ]; then
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u)/bus"
    export DBUS_SESSION_BUS_ADDRESS
  fi
  set -- \
    "/xfce4-power-manager/dpms-enabled bool false" \
    "/xfce4-power-manager/blank-on-ac int 0" \
    "/xfce4-power-manager/dpms-on-ac-sleep int 0" \
    "/xfce4-power-manager/dpms-on-ac-off int 0" \
    "/xfce4-power-manager/blank-on-battery int 0" \
    "/xfce4-power-manager/dpms-on-battery-sleep int 0" \
    "/xfce4-power-manager/dpms-on-battery-off int 0" \
    "/xfce4-power-manager/lock-screen-suspend-hibernate bool false"
  for entry in "$@"; do
    # shellcheck disable=SC2086
    set -f; set -- $entry; set +f
    xfconf-query -c xfce4-power-manager -p "$1" -n -t "$2" -s "$3" \
      >/dev/null 2>&1 || true
  done
  note "xfce4-power-manager will leave the monitor on"
  did=$((did + 1))
fi

# xfce4-screensaver keeps its own channel, and is a locker in its own right on
# the versions that ship it.
if [ "$DRY" != 1 ] && [ "$LIVE" = 1 ] && command -v xfconf-query >/dev/null 2>&1; then
  xfconf-query -c xfce4-screensaver -p /saver/enabled -n -t bool -s false \
    >/dev/null 2>&1 || true
  xfconf-query -c xfce4-screensaver -p /lock/enabled -n -t bool -s false \
    >/dev/null 2>&1 || true
fi

# And the session that is running right now, so this does not wait for a
# reboot to be true.
if [ "$DRY" != 1 ] && [ "$LIVE" = 1 ]; then
  DISPLAY="${DISPLAY:-:0}"
  export DISPLAY
  if command -v xset >/dev/null 2>&1 && xset q >/dev/null 2>&1; then
    xset s off -dpms s noblank 2>/dev/null || true
    note "the screen in front of the television is awake now"
  fi
  # Already running, and it will lock the moment it decides to, override or
  # no override -- the override only governs the next login.
  if pgrep -x light-locker >/dev/null 2>&1; then
    pkill -x light-locker 2>/dev/null || true
    note "stopped the locker that was already running"
  fi
fi

if [ "$DRY" = 1 ]; then
  exit 0
fi
printf '   %s\n' "done: $did change(s) in $HOME_DIR"
