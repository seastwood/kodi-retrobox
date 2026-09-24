#!/bin/bash
# Back up everything that cannot be reinstalled: game saves, save states, the
# captured system definition, and the repository itself.
#
# Destinations are configured in backup/backup.conf, not here, and there can be
# several -- a local copy protects against a bad edit, an off-box copy against
# the disk failing. Nothing happens until one is uncommented, and a run with no
# destinations says so rather than pretending to have worked.
#
# Snapshots are dated and hard-linked against the previous one, so seven
# generations of a 46 MB save directory cost almost nothing but a corrupted
# save can still be rolled back to yesterday.
set -u
# The repository is wherever this file actually lives, not a folder of a
# particular name. It is symlinked into ~/.local/bin, so resolve the link
# first and then walk up out of bin/.
R="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
CONF="$R/backup/backup.conf"
LOG="$HOME/.local/state/retro-backup.log"
# Seconds included: two runs in the same minute would otherwise be the same
# snapshot, and the second would quietly overwrite the first.
STAMP=$(date +%Y-%m-%d_%H%M%S)
GENERATIONS=7
# A ceiling on the whole destination, not on one snapshot. GENERATIONS alone
# cannot promise anything about disk: seven snapshots of a save directory are
# nothing, and seven of a library with include: lines pointed at it can be
# tens of gigabytes. A console that fills its own disk stops being able to
# write saves, which is the thing the backup exists to protect.
#
# Empty means no ceiling, which is what every install before this had.
MAXSIZE=""
SSH_KEY="$HOME/.ssh/id_ed25519_usbip"
# A password for ssh: destinations, for a NAS or a router that will not take a
# key. A key is better and the console offers to set one up first, but "it only
# does keys" is not a reason for somebody to have no off-box backup at all.
#
# The file, never the password itself: a password on a command line is visible
# in `ps` to every account on the machine. It is kept outside the backup set on
# purpose -- ~/.config is not among SOURCES -- so a backup carried to somebody
# else's disk does not carry the credentials for that disk with it.
SSH_PASSFILE=""

mkdir -p "$(dirname "$LOG")"
say() { printf '%s %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$LOG"; }

[ -f "$CONF" ] || { say "no $CONF - nothing configured, doing nothing"; exit 0; }

# shellcheck disable=SC1090
GENERATIONS=$(sed -nE 's/^GENERATIONS=([0-9]+).*/\1/p' "$CONF" | tail -1)
[ -n "$GENERATIONS" ] || GENERATIONS=7
# The config is read, not sourced, so $HOME in it would be a literal. A
# leading ~ is expanded here so destinations can be written portably.
untilde() { case "$1" in "~/"*) printf '%s' "$HOME/${1#\~/}" ;; *) printf '%s' "$1" ;; esac; }
key=$(sed -nE 's/^SSH_KEY=(.*)/\1/p' "$CONF" | tail -1)
[ -n "$key" ] && SSH_KEY="$(untilde "$key")"
MAXSIZE=$(sed -nE 's/^MAXSIZE=([0-9]+[KMGT]?).*/\1/p' "$CONF" | tail -1)
pf=$(sed -nE 's/^SSH_PASSFILE=(.*)/\1/p' "$CONF" | tail -1)
[ -n "$pf" ] && SSH_PASSFILE="$(untilde "$pf")"

# How to reach an ssh destination: a password if one is configured and usable,
# a key otherwise. Printed as a command prefix so both ssh and rsync use the
# same decision rather than each making it again.
SSH_PREFIX=""
if [ -n "$SSH_PASSFILE" ] && [ -f "$SSH_PASSFILE" ]; then
  if command -v sshpass >/dev/null 2>&1; then
    SSH_PREFIX="sshpass -f $SSH_PASSFILE"
  else
    say "a backup password is configured but sshpass is not installed; "\
        "falling back to the key. Fix: sudo apt install sshpass"
  fi
fi
# BatchMode refuses to prompt, which is what makes a failure a log line rather
# than a timer wedged for ever waiting at a password prompt nobody can see.
# It has to come off when a password is genuinely being supplied.
if [ -n "$SSH_PREFIX" ]; then
  SSH_OPTS="-o StrictHostKeyChecking=accept-new"
else
  SSH_OPTS="-i $SSH_KEY -o BatchMode=yes"
fi

# Bytes from "5G", "500M", "2048". Printed rather than returned so the two
# callers below -- one local, one over ssh -- can share one definition.
to_bytes() {
  case "$1" in
    *K|*k) echo $(( ${1%[Kk]} * 1024 )) ;;
    *M|*m) echo $(( ${1%[Mm]} * 1024 * 1024 )) ;;
    *G|*g) echo $(( ${1%[Gg]} * 1024 * 1024 * 1024 )) ;;
    *T|*t) echo $(( ${1%[Tt]} * 1024 * 1024 * 1024 * 1024 )) ;;
    ""|*[!0-9]*) echo 0 ;;
    *) echo "$1" ;;
  esac
}

# Delete the oldest snapshots until the destination is under the ceiling.
# Never the last one: a backup that deleted itself to fit would be worse than
# no ceiling at all, and a single snapshot larger than the ceiling is a
# configuration to complain about rather than data to throw away.
trim_to_size() {   # trim_to_size <dir> <bytes>
  local dir="$1" cap="$2" used oldest
  [ "$cap" -gt 0 ] 2>/dev/null || return 0
  while :; do
    used=$(du -sb "$dir" 2>/dev/null | cut -f1)
    [ -n "$used" ] || return 0
    [ "$used" -le "$cap" ] && return 0
    # shellcheck disable=SC2012
    [ "$(ls -1d "$dir"/20* 2>/dev/null | wc -l)" -gt 1 ] || return 1
    # shellcheck disable=SC2012
    oldest=$(ls -1d "$dir"/20* 2>/dev/null | sort | head -1)
    [ -n "$oldest" ] || return 0
    rm -rf "$oldest"
  done
}

mapfile -t DESTS < <(grep -E '^(local|ssh|path):' "$CONF" | sed 's/[[:space:]]*$//')
for i in "${!DESTS[@]}"; do
  case "${DESTS[$i]}" in
    *:~/*) DESTS[$i]="${DESTS[$i]%%:*}:$HOME/${DESTS[$i]#*:\~/}" ;;
  esac
done
if [ ${#DESTS[@]} -eq 0 ]; then
  say "no destinations enabled in $CONF - edit it to switch backups on"
  exit 0
fi

# Refresh the captured definition first, so a backup always carries a current one.
"$R/install/capture.sh" >/dev/null 2>&1 || say "capture failed, backing up anyway"

SOURCES=(
  "$HOME/.config/retroarch/saves"
  "$HOME/.config/retroarch/states"
  "$HOME/.config/retroarch/retroarch.cfg"
  "$HOME/.local/share/retroarch/plists"
  "$HOME/.local/share/gameplayers.manual.json"
  "$HOME/.local/share/pcgames.json"
  "$HOME/.kodi/userdata"
  "$R"
)
while read -r extra; do
  [ -n "$extra" ] && SOURCES+=("$extra")
done < <(sed -nE 's/^include:(.*)/\1/p' "$CONF" | sed "s|^~/|$HOME/|")

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
for src in "${SOURCES[@]}"; do
  [ -e "$src" ] || continue
  # Keep the tree shape so a restore is obvious: strip $HOME, keep the rest.
  rel="${src#"$HOME"/}"
  mkdir -p "$STAGE/$(dirname "$rel")"
  cp -a "$src" "$STAGE/$rel"
done
SIZE=$(du -sh "$STAGE" | cut -f1)

fail=0
for dest in "${DESTS[@]}"; do
  kind="${dest%%:*}"
  target="${dest#*:}"
  case "$kind" in
    local|path)
      mkdir -p "$target" || { say "cannot write $target"; fail=1; continue; }
      link=""
      [ -d "$target/latest" ] && link="--link-dest=$target/latest"
      if rsync -a --delete $link "$STAGE/" "$target/$STAMP/" 2>>"$LOG"; then
        ln -sfn "$target/$STAMP" "$target/latest"
        # shellcheck disable=SC2012
        ls -1d "$target"/20* 2>/dev/null | sort | head -n -"$GENERATIONS" \
          | xargs -r rm -rf
        cap=$(to_bytes "$MAXSIZE")
        if [ "$cap" -gt 0 ]; then
          if trim_to_size "$target" "$cap"; then :; else
            say "warning: one snapshot in $target is larger than the ${MAXSIZE} limit; keeping it"
          fi
        fi
        say "backed up $SIZE to $target/$STAMP"
      else
        say "rsync to $target failed"; fail=1
      fi
      ;;
    ssh)
      host="${target%%:*}"
      remote="${target#*:}"
      $SSH_PREFIX ssh $SSH_OPTS "$host" "mkdir -p '$remote'" 2>>"$LOG" || {
        say "cannot reach $host"; fail=1; continue; }
      link=""
      $SSH_PREFIX ssh $SSH_OPTS "$host" "[ -d '$remote/latest' ]" 2>/dev/null \
        && link="--link-dest=$remote/latest"
      if rsync -a --delete $link -e "$SSH_PREFIX ssh $SSH_OPTS" \
           "$STAGE/" "$host:$remote/$STAMP/" 2>>"$LOG"; then
        cap=$(to_bytes "$MAXSIZE")
        # The same two rules, run where the files are. Sent as one command
        # rather than a round trip per snapshot, and it keeps the last one for
        # the same reason the local branch does.
        $SSH_PREFIX ssh $SSH_OPTS "$host" \
          "ln -sfn '$remote/$STAMP' '$remote/latest'
           ls -1d '$remote'/20* 2>/dev/null | sort | head -n -$GENERATIONS | xargs -r rm -rf
           cap=$cap
           if [ \"\$cap\" -gt 0 ]; then
             while [ \"\$(du -sb '$remote' 2>/dev/null | cut -f1)\" -gt \"\$cap\" ]; do
               [ \"\$(ls -1d '$remote'/20* 2>/dev/null | wc -l)\" -gt 1 ] || break
               rm -rf \"\$(ls -1d '$remote'/20* 2>/dev/null | sort | head -1)\"
             done
           fi" 2>>"$LOG"
        say "backed up $SIZE to $host:$remote/$STAMP"
      else
        say "rsync to $host failed"; fail=1
      fi
      ;;
  esac
done
exit $fail
