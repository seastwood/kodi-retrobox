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
R="$HOME/retro-console"
CONF="$R/backup/backup.conf"
LOG="$HOME/.local/state/retro-backup.log"
# Seconds included: two runs in the same minute would otherwise be the same
# snapshot, and the second would quietly overwrite the first.
STAMP=$(date +%Y-%m-%d_%H%M%S)
GENERATIONS=7
SSH_KEY="$HOME/.ssh/id_ed25519_usbip"

mkdir -p "$(dirname "$LOG")"
say() { printf '%s %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$LOG"; }

[ -f "$CONF" ] || { say "no $CONF - nothing configured, doing nothing"; exit 0; }

# shellcheck disable=SC1090
GENERATIONS=$(sed -nE 's/^GENERATIONS=([0-9]+).*/\1/p' "$CONF" | tail -1)
[ -n "$GENERATIONS" ] || GENERATIONS=7
key=$(sed -nE 's/^SSH_KEY=(.*)/\1/p' "$CONF" | tail -1)
[ -n "$key" ] && SSH_KEY="$key"

mapfile -t DESTS < <(grep -E '^(local|ssh|path):' "$CONF" | sed 's/[[:space:]]*$//')
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
done < <(sed -nE 's/^include:(.*)/\1/p' "$CONF")

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
        say "backed up $SIZE to $target/$STAMP"
      else
        say "rsync to $target failed"; fail=1
      fi
      ;;
    ssh)
      host="${target%%:*}"
      remote="${target#*:}"
      ssh -i "$SSH_KEY" -o BatchMode=yes "$host" "mkdir -p '$remote'" 2>>"$LOG" || {
        say "cannot reach $host"; fail=1; continue; }
      link=""
      ssh -i "$SSH_KEY" -o BatchMode=yes "$host" "[ -d '$remote/latest' ]" 2>/dev/null \
        && link="--link-dest=$remote/latest"
      if rsync -a --delete $link -e "ssh -i $SSH_KEY -o BatchMode=yes" \
           "$STAGE/" "$host:$remote/$STAMP/" 2>>"$LOG"; then
        ssh -i "$SSH_KEY" -o BatchMode=yes "$host" \
          "ln -sfn '$remote/$STAMP' '$remote/latest'; ls -1d '$remote'/20* 2>/dev/null | sort | head -n -$GENERATIONS | xargs -r rm -rf" 2>>"$LOG"
        say "backed up $SIZE to $host:$remote/$STAMP"
      else
        say "rsync to $host failed"; fail=1
      fi
      ;;
  esac
done
exit $fail
