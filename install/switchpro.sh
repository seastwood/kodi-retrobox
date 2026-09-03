#!/bin/sh
# Make a Nintendo Switch Pro Controller pair with this machine.
#
#   install/switchpro.sh [--file PATH] [--dry-run] [--no-restart]
#
# Two settings, neither of them obvious, and the pad is unusable without the
# first:
#
#   * BlueZ's input service refuses a HID connection from a device that is not
#     bonded (input.conf, ClassicBondedOnly, which defaults to true "for
#     security"). A Pro Controller pairs and then connects unbonded, so the
#     controller appears to pair, disconnects a second later, and the log says
#     nothing a person would connect to the pad. Turning that limit off is the
#     fix every Linux thread arrives at, and it is the whole reason this
#     script exists.
#
#   * The adapter's name. A Pro Controller behaves better against a host
#     called Nintendo, so this console calls itself that. It is only an alias:
#     the machine's hostname is untouched.
#
# --file rewrites some other file and does nothing else at all: no adapter, no
# service, no root. That is how the tests exercise this without a machine.
set -u

FILE=/etc/bluetooth/input.conf
ALIAS=Nintendo
DRY=0
RESTART=1
ONLY_FILE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --file) FILE="$2"; ONLY_FILE=1; RESTART=0; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    --no-restart) RESTART=0; shift ;;
    -h|--help) sed -n '2,4p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

FAILED=0

# ------------------------------------------------------------- input.conf --
if [ ! -f "$FILE" ]; then
  echo "no $FILE -- is bluez installed?" >&2
  exit 1
fi

TMP="${TMPDIR:-/tmp}/switchpro.$$"
trap 'rm -f "$TMP"' EXIT INT TERM

# Rewritten rather than sed'd in place: the setting can be absent, commented
# out, present and true, or present twice, and the answer has to be exactly
# one uncommented line in [General] whichever of those it started as.
STATE=$(python3 - "$FILE" "$TMP" <<'PY'
import re
import sys

src, dst = sys.argv[1], sys.argv[2]
text = open(src).read()
key = re.compile(r"\s*#?\s*ClassicBondedOnly\s*=", re.I)
want = "ClassicBondedOnly=false\n"

out, section, done = [], None, False
for line in text.splitlines(True):
    bare = line.strip()
    if bare.startswith("[") and bare.endswith("]"):
        section = bare[1:-1].strip().lower()
    # Before any header is still [General]'s ground, and a copy of this
    # setting under some other section is not ours to touch.
    elif key.match(line) and section in (None, "general"):
        if not done:                      # the first one becomes the answer
            out.append(want)
            done = True
        continue                          # and any later one would only fight it
    out.append(line)

if not done:
    for i, line in enumerate(out):
        if line.strip().lower() == "[general]":
            out.insert(i + 1, want)
            done = True
            break
if not done:
    if out and not out[-1].endswith("\n"):
        out.append("\n")
    out.append("\n[General]\n" + want)

new = "".join(out)
open(dst, "w").write(new)
print("unchanged" if new == text else "changed")
PY
) || { echo "could not read $FILE" >&2; exit 1; }

if [ "$STATE" = unchanged ]; then
  echo "ClassicBondedOnly=false already in $FILE"
  CHANGED=0
elif [ "$DRY" = 1 ]; then
  echo "would set ClassicBondedOnly=false in $FILE"
  CHANGED=0
else
  if [ -w "$FILE" ] && [ -w "$(dirname "$FILE")" ]; then SUDO=""; else SUDO="sudo"; fi
  [ -n "$SUDO" ] && [ "$(id -u)" != 0 ] && ! sudo -n true 2>/dev/null &&
    echo "this needs sudo; you will be prompted"
  # Kept once, and only the first time, so a re-run cannot overwrite the
  # original with a copy of our own edit.
  if [ ! -e "$FILE.retrobox-orig" ]; then
    $SUDO cp -a "$FILE" "$FILE.retrobox-orig" 2>/dev/null &&
      echo "kept the original as $FILE.retrobox-orig"
  fi
  # Into place as a rename, from the same directory: a half-written
  # input.conf is a bluetoothd that will not start, and this way there is
  # never a moment when the file on disk is neither one thing nor the other.
  if $SUDO cp "$TMP" "$FILE.retrobox-new" &&
     $SUDO chmod --reference="$FILE" "$FILE.retrobox-new" 2>/dev/null &&
     $SUDO mv -f "$FILE.retrobox-new" "$FILE"; then
    echo "ClassicBondedOnly=false in $FILE (a Pro Controller can pair)"
    CHANGED=1
  else
    $SUDO rm -f "$FILE.retrobox-new"
    echo "could not write $FILE" >&2
    FAILED=$((FAILED+1))
    CHANGED=0
  fi
fi

[ "$ONLY_FILE" = 1 ] && exit "$FAILED"

# ---------------------------------------------------------------- service --
# Only when something changed: bluetoothd is read once at startup, and a
# restart drops whatever controller is connected to it right now.
if [ "$CHANGED" = 1 ] && [ "$RESTART" = 1 ]; then
  if systemctl restart bluetooth 2>/dev/null || sudo systemctl restart bluetooth; then
    echo "bluetooth restarted, so the new setting is live"
  else
    echo "could not restart bluetooth; the setting applies at the next boot" >&2
    FAILED=$((FAILED+1))
  fi
fi

# ---------------------------------------------------------------- adapter --
if [ "$DRY" = 1 ]; then
  echo "would name the adapter \"$ALIAS\""
  exit "$FAILED"
fi
if ! command -v bluetoothctl >/dev/null 2>&1; then
  echo "no bluetoothctl, so the adapter was not renamed" >&2
  exit "$FAILED"
fi

alias_now() { bluetoothctl show 2>/dev/null | sed -n 's/^[[:space:]]*Alias:[[:space:]]*//p' | head -1; }

if [ -z "$(alias_now)" ]; then
  echo "no Bluetooth adapter here; nothing to name" >&2
elif [ "$(alias_now)" = "$ALIAS" ]; then
  echo "the adapter is already called \"$ALIAS\""
else
  was=$(alias_now)
  bluetoothctl system-alias "$ALIAS" >/dev/null 2>&1
  # BlueZ applies the name a moment after the command returns, so reading it
  # straight back reads the old one. Poll rather than sleep and hope.
  i=0
  while [ "$(alias_now)" != "$ALIAS" ] && [ "$i" -lt 20 ]; do
    i=$((i+1))
    sleep 0.25
  done
  if [ "$(alias_now)" = "$ALIAS" ]; then
    echo "adapter renamed to \"$ALIAS\" (was \"$was\")"
  else
    # system-alias names the default adapter, and on 5.72 there is no flag
    # for choosing another one.
    echo "could not rename the adapter; it is still \"$(alias_now)\"" >&2
    FAILED=$((FAILED+1))
  fi
fi

exit "$FAILED"
