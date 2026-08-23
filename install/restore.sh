#!/bin/bash
# Put a backup back.
#
#   install/restore.sh [--from DIR] [--yes] [--dry-run] [--list]
#
# A backup holds the things that cannot be downloaded again: game saves and
# save states, the playlists, your PC game declarations and hand-kept player
# counts, Kodi's own userdata, and the repository's captured state and
# secrets. It does NOT hold your ROMs or your PC games -- those are yours and
# are far too large -- unless you added include: lines to backup.conf.
#
# So a restore is: install this console normally, then run this. Copy your
# games back yourself.
#
# Paths inside a backup point at the home it was taken from. Restoring onto a
# different user rewrites them, at a path-name boundary, the same way adopt.sh
# does -- otherwise every playlist entry would point at a home that does not
# exist and the games would silently vanish.
set -u

REPO="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
FROM=""
YES=0
DRY=0
LIST=0

while [ $# -gt 0 ]; do
  case "$1" in
    --from) FROM="$2"; shift 2 ;;
    --yes|-y) YES=1; shift ;;
    --dry-run) DRY=1; shift ;;
    --list) LIST=1; shift ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok()   { printf '   ok    %s\n' "$*"; }
skip() { printf '   --    %s\n' "$*"; }
warn() { printf '   WARN  %s\n' "$*"; }
bad()  { printf '   FAIL  %s\n' "$*"; }

# ------------------------------------------------------- find the backup ---
default_root() {
  local conf="$REPO/backup/backup.conf"
  [ -f "$conf" ] || return 0
  sed -nE 's/^local:(.*)/\1/p' "$conf" | head -1 | sed "s|^~/|$HOME/|"
}

if [ -z "$FROM" ]; then
  root="$(default_root)"
  [ -z "$root" ] && root="$HOME/backups"
  if [ -d "$root/latest" ]; then
    FROM="$root/latest"
  else
    FROM=$(find "$root" -maxdepth 1 -mindepth 1 -type d 2>/dev/null | sort | tail -1)
  fi
fi

if [ "$LIST" = 1 ]; then
  root="$(default_root)"; [ -z "$root" ] && root="$HOME/backups"
  say "Generations in $root"
  find "$root" -maxdepth 1 -mindepth 1 -type d 2>/dev/null | sort | while read -r g; do
    printf '   %-28s %s\n' "$(basename "$g")" "$(du -sh "$g" 2>/dev/null | cut -f1)"
  done
  exit 0
fi

say "Backup"
if [ -z "$FROM" ] || [ ! -d "$FROM" ]; then
  bad "no backup found; give one with --from DIR, or --list to see them"
  exit 1
fi
# pwd is logical in bash, so cd-ing into "latest" would keep the symlink
# path and du would report 0. -P gives the generation it actually points at.
FROM="$(cd "$FROM" && pwd -P)"
echo "   $FROM"
echo "   taken $(date -r "$FROM" '+%Y-%m-%d %H:%M' 2>/dev/null), $(du -sh "$FROM" 2>/dev/null | cut -f1)"

# The home the backup was taken from, so paths inside it can be corrected.
OLD_HOME=""
for marker in "$FROM"/*/system/home.txt; do
  [ -f "$marker" ] && OLD_HOME=$(head -1 "$marker")
done
OLD_HOME="${OLD_HOME%/}"
[ -n "$OLD_HOME" ] && echo "   taken on $OLD_HOME"

# ------------------------------------------------------------- safety ------
say "Checks"
busy=""
for p in kodi.bin retroarch; do
  pgrep -x "$p" >/dev/null 2>&1 && busy="$busy $p"
done
if [ -n "$busy" ]; then
  bad "still running:$busy"
  echo "        Kodi and RetroArch rewrite their own files as they exit, so a"
  echo "        restore underneath them would be overwritten moments later."
  echo "        Quit them and run this again."
  exit 1
fi
ok "nothing is running that would overwrite a restore"

# --------------------------------------------------------- what to move ----
# Each entry is a path relative to the backup root, restored to the same place
# under $HOME.
ITEMS=(
  ".config/retroarch/saves"
  ".config/retroarch/states"
  ".config/retroarch/retroarch.cfg"
  ".local/share/retroarch/plists"
  ".local/share/gameplayers.manual.json"
  ".local/share/pcgames.json"
  ".kodi/userdata"
)

say "What will be restored"
found=0
for item in "${ITEMS[@]}"; do
  if [ -e "$FROM/$item" ]; then
    printf '   %-42s %s\n' "$item" "$(du -sh "$FROM/$item" 2>/dev/null | cut -f1)"
    found=$((found + 1))
  else
    skip "$item (not in this backup)"
  fi
done
# The repository's own captured state and secrets, which git never carries.
BSTATE=""
for cand in "$FROM"/*/state; do [ -d "$cand" ] && BSTATE="$cand"; done
[ -n "$BSTATE" ] && printf '   %-42s %s\n' "$(basename "$(dirname "$BSTATE")")/state + secrets" \
  "$(du -sh "$(dirname "$BSTATE")/state" 2>/dev/null | cut -f1)"

if [ "$found" = 0 ]; then
  bad "this does not look like a backup of this console"
  exit 1
fi
echo
echo "   Your ROMs and PC games are NOT in a backup and are not touched."
echo "   Anything already at these paths will be replaced."

if [ "$DRY" = 1 ]; then
  say "Dry run"; skip "nothing was changed"; exit 0
fi
if [ "$YES" != 1 ]; then
  printf '\n   Restore over the current files? [y/N] '
  read -r reply </dev/tty || reply=n
  case "$reply" in [Yy]*) : ;; *) echo "   stopped"; exit 1 ;; esac
fi

# ------------------------------------------------------------- restore -----
say "Restoring"
STAMP=$(date +%Y-%m-%d_%H%M%S)
ASIDE="$HOME/.local/state/restore-$STAMP"
for item in "${ITEMS[@]}"; do
  [ -e "$FROM/$item" ] || continue
  dest="$HOME/$item"
  if [ -e "$dest" ]; then
    mkdir -p "$ASIDE/$(dirname "$item")"
    mv "$dest" "$ASIDE/$item"
  fi
  mkdir -p "$(dirname "$dest")"
  cp -a "$FROM/$item" "$dest"
  ok "$item"
done
[ -d "$ASIDE" ] && ok "what was there is kept at $ASIDE"

if [ -n "$BSTATE" ]; then
  src="$(dirname "$BSTATE")"
  for part in state secrets; do
    if [ -d "$src/$part" ]; then
      mkdir -p "$REPO/$part"
      cp -a "$src/$part/." "$REPO/$part/"
      ok "$part restored into the clone"
    fi
  done
fi

# ------------------------------------------------------ correct the paths --
if [ -n "$OLD_HOME" ] && [ "$OLD_HOME" != "${HOME%/}" ]; then
  say "Adapting paths"
  echo "   $OLD_HOME -> $HOME"
  esc() { printf '%s' "$1" | sed -e 's/[][\.*^$|&/]/\\&/g'; }
  O=$(esc "$OLD_HOME"); N=$(esc "$HOME")
  TAIL='[^A-Za-z0-9_.-]'
  n=0
  while IFS= read -r -d '' f; do
    sed -i -E "s|${O}(${TAIL})|${N}\1|g; s|${O}\$|${N}|g" "$f"
    n=$((n + 1))
  done < <(grep -rlIZE "${O}(${TAIL}|\$)" \
             "$HOME/.local/share/retroarch/plists" \
             "$HOME/.local/share/pcgames.json" \
             "$HOME/.kodi/userdata" \
             "$REPO/state" 2>/dev/null)
  ok "$n files now point at $HOME"
else
  skip "same home as the backup; no paths to adapt"
fi

say "Done"
cat <<EOF
   Your saves, playlists and settings are back.

   1. Copy your ROMs into ~/Games/emulation/ and your PC games wherever
      pcgames.json says they live. A backup does not carry them.
   2. Run ~/.local/bin/sync_games.py once, or wait for the timer, so the
      menu is rebuilt from what is actually on disk.
   3. Start Kodi.
EOF
