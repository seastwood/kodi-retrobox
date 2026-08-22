#!/bin/bash
# Build this console on a fresh machine.
#
#   install.sh [--home DIR] [--skip-packages] [--with-optional] [--dry-run] [--yes]
#
# Every phase is idempotent: running it twice changes nothing the second time,
# which matters because the usual reason to run it is that one phase failed.
#
# --home exists so the whole thing can be exercised against a throwaway
# directory without touching a real account. Package installation is the only
# part that needs root, and --skip-packages leaves it out.
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
TARGET_HOME="$HOME"
SKIP_PACKAGES=0
WITH_OPTIONAL=0
DRY=0
ASSUME_YES=0
FAILED=0

while [ $# -gt 0 ]; do
  case "$1" in
    --home) TARGET_HOME="$2"; shift 2 ;;
    --skip-packages) SKIP_PACKAGES=1; shift ;;
    --with-optional) WITH_OPTIONAL=1; shift ;;
    --dry-run) DRY=1; shift ;;
    --yes|-y) ASSUME_YES=1; shift ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok()   { printf '   ok    %s\n' "$*"; }
skip() { printf '   --    %s\n' "$*"; }
warn() { printf '   WARN  %s\n' "$*"; }
bad()  { printf '   FAIL  %s\n' "$*"; FAILED=$((FAILED+1)); }
run()  { if [ "$DRY" = 1 ]; then printf '   would  %s\n' "$*"; else eval "$@"; fi; }
# The no-clobber flag warns that it is non-portable on this coreutils,
# so check for the destination first instead.
copy_new() { [ -e "$2" ] || run "cp '$1' '$2'"; }

CORES_DIR="$TARGET_HOME/.local/lib/retroarch/cores"
SHADER_DIR="$TARGET_HOME/.local/share/retroarch/shaders"
BUILDBOT=https://buildbot.libretro.com

# --------------------------------------------------------------- preflight --
say "Checking the machine"
. /etc/os-release 2>/dev/null || true
echo "   ${PRETTY_NAME:-unknown distribution}"
CODENAME="${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}"
if [ -z "$CODENAME" ]; then
  warn "cannot tell which Ubuntu release this is; the PPAs may not resolve"
elif [ "$CODENAME" != "noble" ]; then
  warn "built and tested on noble (Mint 22 / Ubuntu 24.04); this is $CODENAME"
else
  ok "package base is noble"
fi
for c in git curl; do
  command -v "$c" >/dev/null || bad "$c is required before anything else can run"
done
[ -d "$REPO/bin" ] || bad "run this from inside the repository (no $REPO/bin)"

# Absolute paths are baked into the code. On the machine it grew up on that is
# invisible; anywhere else every path is wrong, so refuse rather than install
# something that cannot work.
BAKED=""
[ -s "$REPO/system/home.txt" ] && BAKED=$(head -1 "$REPO/system/home.txt")
BAKED="${BAKED%/}"
if [ -n "$BAKED" ] && [ "$BAKED" != "${TARGET_HOME%/}" ]; then
  bad "the code points at $BAKED but this is $TARGET_HOME"
  echo "         run:  $HERE/adopt.sh '$TARGET_HOME'   then try again"
fi
[ "$FAILED" -gt 0 ] && { echo; echo "preflight failed"; exit 1; }

# --------------------------------------------------------------- packages ---
say "Packages"
if [ "$SKIP_PACKAGES" = 1 ]; then
  skip "asked to skip package installation"
else
  if [ "$(id -u)" != 0 ] && ! sudo -n true 2>/dev/null; then
    warn "this phase needs sudo; you will be prompted"
  fi
  # The libretro PPA carries RetroArch and the cores.
  while read -r ppa; do
    [ -n "$ppa" ] || continue
    short="${ppa#ppa.launchpadcontent.net/}"; short="${short%/*}"
    if ls /etc/apt/sources.list.d/ 2>/dev/null | grep -qi "${short%%/*}"; then
      skip "PPA already present: $short"
    else
      run "sudo add-apt-repository -y ppa:$short"
    fi
  done < <(sed 's#^ppa.launchpadcontent.net/##; s#/ubuntu$##' "$REPO/system/ppas.txt" 2>/dev/null \
           | sed 's#/$##' | awk 'NF')
  run "sudo apt-get update -qq"
  pkgs=$(grep -vE '^\s*(#|$)' "$REPO/system/packages.required.txt" | tr '\n' ' ')
  run "sudo apt-get install -y $pkgs"
  if [ "$WITH_OPTIONAL" = 1 ]; then
    # WineHQ is a third-party repository, so it is only added on request.
    run "sudo mkdir -pm755 /etc/apt/keyrings"
    run "sudo curl -fsSL -o /etc/apt/keyrings/winehq-archive.key https://dl.winehq.org/wine-builds/winehq.key"
    run "sudo curl -fsSL -o /etc/apt/sources.list.d/winehq-${CODENAME}.sources https://dl.winehq.org/wine-builds/ubuntu/dists/${CODENAME}/winehq-${CODENAME}.sources"
    run "sudo dpkg --add-architecture i386"
    run "sudo apt-get update -qq"
    opt=$(grep -vE '^\s*(#|$)' "$REPO/system/packages.optional.txt" | tr '\n' ' ')
    run "sudo apt-get install -y --install-recommends $opt"
  fi
  ok "packages requested"
fi

# ------------------------------------------------------------- directories --
say "Directories"
for d in \
  "$TARGET_HOME/.local/bin" "$TARGET_HOME/.local/share/fonts" \
  "$CORES_DIR" "$SHADER_DIR" \
  "$TARGET_HOME/.local/share/retroarch/system" \
  "$TARGET_HOME/.local/share/retroarch/plists" \
  "$TARGET_HOME/.local/share/retroarch/thumbnails" \
  "$TARGET_HOME/.local/state/retroarch/plists" \
  "$TARGET_HOME/.config/retroarch" \
  "$TARGET_HOME/.config/systemd/user" \
  "$TARGET_HOME/.config/autostart" \
  "$TARGET_HOME/.kodi/addons" "$TARGET_HOME/.kodi/media/consoles" \
  "$TARGET_HOME/.kodi/userdata/addon_data/script.skinshortcuts" \
  "$TARGET_HOME/Games/emulation" ; do
  run "mkdir -p '$d'"
done
ok "layout created under $TARGET_HOME"

# ------------------------------------------------------------------ deploy --
say "Linking the code into place"
if [ "$DRY" = 1 ]; then
  skip "would run install/deploy.sh"
else
  HOME="$TARGET_HOME" "$HERE/deploy.sh" | sed 's/^/   /' || bad "deploy.sh failed"
fi

# ------------------------------------------------------------------ assets --
say "Fonts and icons"
if [ -f "$REPO/assets/fonts/PressStart2P.ttf" ]; then
  copy_new "$REPO/assets/fonts/PressStart2P.ttf" "$TARGET_HOME/.local/share/fonts/PressStart2P.ttf"
  ok "pixel font in place (the picker and the exit bar both use it)"
else
  warn "no font in the repo; the picker will fall back to a default face"
fi
if [ -d "$REPO/assets/icons" ]; then
  for i in "$REPO"/assets/icons/*.png; do
    [ -e "$i" ] && copy_new "$i" "$TARGET_HOME/.kodi/media/consoles/$(basename "$i")"
  done
  ok "menu icons in place"
fi

# ----------------------------------------------------------- configuration --
say "Configuration"
RA_CFG="$TARGET_HOME/.config/retroarch/retroarch.cfg"
TEMPLATE="$REPO/templates/retroarch-settings.conf"

# Settings this console deliberately sets, merged one key at a time so
# everything else RetroArch owns is left alone. This is what a stranger gets:
# the behaviour, without anybody's account or game library.
if [ "$DRY" = 1 ]; then
  skip "would merge $(grep -cvE '^\s*(#|$)' "$TEMPLATE" 2>/dev/null) settings into retroarch.cfg"
elif [ -f "$TEMPLATE" ]; then
  touch "$RA_CFG"
  applied=0
  while IFS= read -r line; do
    case "$line" in ''|'#'*) continue ;; esac
    key="${line%% =*}"
    if grep -q "^$key = " "$RA_CFG" 2>/dev/null; then
      # sed with | because the values are paths
      sed -i "s|^$key = .*|$line|" "$RA_CFG"
    else
      printf '%s\n' "$line" >> "$RA_CFG"
    fi
    applied=$((applied+1))
  done < "$TEMPLATE"
  ok "$applied settings applied to retroarch.cfg"
else
  warn "no settings template; RetroArch will use its own defaults"
fi

# This machine's own captured state, if there is any. A fresh clone has none --
# it is deliberately not published -- and a restore from backup provides it.
LOCAL="$REPO/local"
if [ -d "$LOCAL" ]; then
  for f in gameplayers.manual.json pcgames.json; do
    [ -f "$LOCAL/$f" ] && copy_new "$LOCAL/$f" "$TARGET_HOME/.local/share/$f"
  done
  for p in "$LOCAL"/plists/*.lpl; do
    [ -e "$p" ] || continue
    copy_new "$p" "$TARGET_HOME/.local/share/retroarch/plists/$(basename "$p")"
  done
  [ -f "$LOCAL/kodi/kodi.desktop" ] &&
    copy_new "$LOCAL/kodi/kodi.desktop" "$TARGET_HOME/.config/autostart/kodi.desktop"
  ok "restored this machine's captured state from local/"
else
  skip "no captured state (a fresh install: add ROMs and let the sync build the playlists)"
fi

# ------------------------------------------------------------------- cores --
say "Emulator cores"
if [ "$DRY" = 1 ]; then
  skip "would download cores listed in system/retroarch-cores.txt"
elif [ ! -f "$REPO/system/cores.txt" ]; then
  warn "no system/cores.txt"
else
  got=0; missing=0
  while read -r core; do
    [ -n "$core" ] || continue
    case "$core" in *.so) : ;; *) core="$core.so" ;; esac
    [ -f "$CORES_DIR/$core" ] && { got=$((got+1)); continue; }
    url="$BUILDBOT/nightly/linux/x86_64/latest/${core}.zip"
    if curl -fsSL -o /tmp/core.zip "$url" 2>/dev/null &&
       unzip -qo /tmp/core.zip -d "$CORES_DIR" 2>/dev/null; then
      got=$((got+1))
    else
      missing=$((missing+1)); warn "could not fetch $core"
    fi
    rm -f /tmp/core.zip
  done < <(grep -vE '^\s*(#|$)' "$REPO/system/cores.txt")
  ok "$got cores present, $missing could not be fetched"
fi

# ----------------------------------------------------------------- shaders --
say "Shaders"
if [ "$DRY" = 1 ]; then
  skip "would fetch the glsl shader pack"
elif [ -d "$SHADER_DIR/crt" ]; then
  skip "shaders already installed"
else
  # The cg pack cannot run on the GL driver; glsl is the one that matters.
  if curl -fsSL -o /tmp/shaders.zip "$BUILDBOT/assets/frontend/shaders_glsl.zip" &&
     unzip -qo /tmp/shaders.zip -d "$SHADER_DIR"; then
    ok "glsl shaders installed (crt-easymode is the one the launcher uses)"
  else
    warn "shader pack could not be fetched; games will run without a filter"
  fi
  rm -f /tmp/shaders.zip
fi

# ----------------------------------------------------------------- systemd --
say "Timers"
if [ "$DRY" = 1 ] || [ "$TARGET_HOME" != "$HOME" ]; then
  skip "not touching systemd (installing into $TARGET_HOME)"
else
  systemctl --user daemon-reload 2>/dev/null
  for t in sync-games.timer retro-backup.timer; do
    if [ -f "$TARGET_HOME/.config/systemd/user/$t" ]; then
      systemctl --user enable --now "$t" 2>/dev/null && ok "$t enabled" ||
        warn "could not enable $t"
    else
      warn "$t is not installed"
    fi
  done
fi

# ------------------------------------------------------------------ verify --
say "Checking it works"
if [ "$DRY" = 1 ]; then
  skip "would run the test suites"
else
  tests="$TARGET_HOME/.local/share/gametests"
  if [ -d "$tests" ]; then
    total=0; failed=0
    for t in "$tests"/test_*.py; do
      [ -e "$t" ] || continue
      if out=$(cd "$tests" && python3 "$t" 2>&1); then
        n=$(printf '%s' "$out" | grep -c '^  ok'); total=$((total+n))
      else
        failed=$((failed+1)); warn "$(basename "$t") failed"
      fi
    done
    [ "$failed" = 0 ] && ok "$total checks passed" || bad "$failed suites failed"
  else
    warn "no tests found at $tests"
  fi
fi

# ------------------------------------------------------------------- notes --
say "What this cannot do for you"
cat <<'EOF'
   ROMs, BIOS images and box art are not in the repository. Copy your ROMs to
   ~/Games/emulation/<system>/ and your BIOS files to
   ~/.local/share/retroarch/system/ (system/bios-present.txt lists the ones
   this machine expects), then let the sync timer pick them up.

   Achievements need the real token from a backup's secrets/ directory.
EOF

echo
if [ "$FAILED" = 0 ]; then
  printf '\033[1mdone\033[0m - %s\n' "$([ "$DRY" = 1 ] && echo 'dry run, nothing changed' || echo 'installed')"
else
  printf '\033[1mfinished with %d failure(s)\033[0m\n' "$FAILED"
fi
exit $FAILED
