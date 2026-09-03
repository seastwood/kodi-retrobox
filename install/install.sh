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
  warn "this needs a noble base (Mint 22.x / Xubuntu 24.04); this is $CODENAME"
  warn "the libretro PPA and WineHQ are keyed to the codename and will not resolve"
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
  # Every update pulls in files still carrying the repository's own home, so
  # adapting is a normal part of installing rather than a one-off ceremony.
  # Boundary-aware for the same reason adopt.sh is: without it, /home/retro
  # is found inside an already-adopted /home/retro2 and every run re-adopts.
  if grep -rqsE "${BAKED}([^A-Za-z0-9_.-]|\$)" \
       "$REPO/bin" "$REPO/addons" "$REPO/lib" 2>/dev/null; then
    if [ "$DRY" = 1 ]; then
      skip "would adapt paths from $BAKED to $TARGET_HOME"
    else
      "$HERE/adopt.sh" "$TARGET_HOME" | sed 's/^/         /'
      ok "adapted the paths to this machine"
    fi
  else
    ok "paths already adapted to $TARGET_HOME"
  fi
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
  # The libretro PPA carries RetroArch and the cores. The captured line looks
  # like "ppa.launchpadcontent.net/libretro/stable" and what add-apt-repository
  # wants is "ppa:libretro/stable" -- owner AND name, so only the host comes off.
  while read -r line; do
    [ -n "$line" ] || continue
    case "$line" in \#*) continue ;; esac
    name="${line#ppa.launchpadcontent.net/}"
    name="${name%/ubuntu}"; name="${name%/}"
    case "$name" in */*) : ;; *) warn "cannot parse PPA: $line"; continue ;; esac
    if grep -rqs "launchpadcontent.net/${name}" /etc/apt/sources.list.d/ 2>/dev/null; then
      skip "PPA already present: $name"
    else
      run "sudo add-apt-repository -y ppa:$name" || warn "could not add ppa:$name"
    fi
  done < "$REPO/system/ppas.txt"
  run "sudo apt-get update -qq"
  pkgs=$(grep -vE '^\s*(#|$)' "$REPO/system/packages.required.txt" | tr '\n' ' ')
  # One unavailable package makes apt refuse the whole list, so a single bad
  # name used to leave the machine with nothing installed while this said "ok".
  # Try the lot, and if that fails install them one at a time so the report
  # names exactly which ones could not be had.
  if [ "$DRY" = 1 ]; then
    skip "would install: $pkgs"
  elif sudo apt-get install -y $pkgs; then
    ok "all $(printf '%s\n' $pkgs | wc -l) packages installed"
  else
    warn "installing together failed; trying them one at a time"
    missing=""
    for p in $pkgs; do
      sudo apt-get install -y "$p" >/dev/null 2>&1 || missing="$missing $p"
    done
    if [ -n "$missing" ]; then
      bad "could not install:$missing"
    else
      ok "all packages installed (individually)"
    fi
  fi
  # linux-tools-generic follows the GA kernel line, so on an HWE or a freshly
  # upgraded kernel /usr/bin/usbip is a wrapper pointing at nothing: it exists,
  # it is executable, and it exits 2. The package that matters is the one named
  # for the running kernel, which a static package list cannot express.
  ktools="linux-tools-$(uname -r)"
  if [ "$DRY" = 1 ]; then
    skip "would install: $ktools"
  elif usbip version >/dev/null 2>&1; then
    ok "usbip works for kernel $(uname -r)"
  elif sudo apt-get install -y "$ktools" >/dev/null 2>&1 && usbip version >/dev/null 2>&1; then
    ok "installed $ktools so usbip runs"
  else
    warn "usbip does not run for kernel $(uname -r) -- run bin/usbip-setup-root.sh"
  fi

  if [ "$WITH_OPTIONAL" = 1 ]; then
    # WineHQ is a third-party repository, so it is only added on request.
    run "sudo mkdir -pm755 /etc/apt/keyrings"
    run "sudo curl -fsSL -o /etc/apt/keyrings/winehq-archive.key https://dl.winehq.org/wine-builds/winehq.key"
    run "sudo curl -fsSL -o /etc/apt/sources.list.d/winehq-${CODENAME}.sources https://dl.winehq.org/wine-builds/ubuntu/dists/${CODENAME}/winehq-${CODENAME}.sources"
    run "sudo dpkg --add-architecture i386"
    run "sudo apt-get update -qq"
    opt=$(grep -vE '^\s*(#|$)' "$REPO/system/packages.pcgames.txt" | tr '\n' ' ')
    run "sudo apt-get install -y --install-recommends $opt" ||
      warn "the optional Wine packages could not be installed"
  fi
fi

# ------------------------------------------------------------- directories --
say "Directories"
for d in \
  "$TARGET_HOME/.local/bin" "$TARGET_HOME/.local/share/fonts" \
  "$CORES_DIR" "$SHADER_DIR" \
  "$TARGET_HOME/.local/share/retroarch/system" \
  "$TARGET_HOME/.local/share/retroarch/plists" \
  "$TARGET_HOME/.local/share/retroarch/plists/builtin" \
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
# RetroArch identifies games against the libretro databases, which the
# retroarch-data package installs system-wide. content_database_path points
# here, so this is what makes scanning work at all.
RDB_LINK="$TARGET_HOME/.local/share/retroarch/rdb"
if [ -e "$RDB_LINK" ]; then
  skip "game database already linked"
elif [ -d /usr/share/libretro/database/rdb ]; then
  run "ln -s /usr/share/libretro/database/rdb '$RDB_LINK'"
  ok "game database linked ($(ls /usr/share/libretro/database/rdb/*.rdb 2>/dev/null | wc -l) systems)"
else
  warn "no libretro database found; scanning will not identify anything"
fi
ok "layout created under $TARGET_HOME"

# ------------------------------------------------------------------ deploy --
say "Linking the code into place"
if [ "$DRY" = 1 ]; then
  skip "would run install/deploy.sh"
else
  HOME="$TARGET_HOME" "$HERE/deploy.sh" | sed 's/^/   /' || bad "deploy.sh failed"
fi

# --------------------------------------------------------- outside add-ons --
# Add-ons that are their own projects. They are cloned rather than carried
# here, so there is one copy of each and it is the one its own tests run
# against -- two copies of the same add-on in two repositories drift the
# moment either is touched, and the drift is silent.
say "Add-ons kept in their own repositories"
OUTSIDE_ADDONS="script.usbip https://github.com/seastwood/kodi-usbip.git
script.bluetooth https://github.com/seastwood/kodi-bluetooth.git
script.steam https://github.com/seastwood/kodi-steam.git
script.moonlight https://github.com/seastwood/kodi-moonlight.git"
echo "$OUTSIDE_ADDONS" | while read -r id url; do
  [ -n "$id" ] || continue
  dst="$TARGET_HOME/.kodi/addons/$id"
  if [ "$DRY" = 1 ]; then
    skip "would clone $url into $dst"
    continue
  fi
  if ! command -v git >/dev/null 2>&1; then
    warn "git is not installed, so $id was not fetched"
    continue
  fi
  # An earlier install symlinked this out of the repository. Move it aside the
  # same way deploy.sh does rather than deleting something somebody may have
  # edited in place.
  if [ -L "$dst" ]; then
    rm -f "$dst"
    ok "replaced the old link to $id"
  elif [ -d "$dst" ] && [ ! -d "$dst/.git" ]; then
    mv "$dst" "$dst.replaced.$(date +%s)"
    ok "kept the old $id as $id.replaced.*"
  fi
  if [ -d "$dst/.git" ]; then
    if git -C "$dst" pull --ff-only --quiet 2>/dev/null; then
      ok "$id up to date ($(git -C "$dst" rev-parse --short HEAD))"
    else
      # Local edits, a detached head, no network: all reasons to leave it
      # alone and say so rather than throwing away somebody's work.
      warn "$id could not be updated; left as it is"
    fi
  elif git clone --quiet "$url" "$dst" 2>/dev/null; then
    ok "$id cloned from $url"
  else
    warn "could not clone $url -- $id will be missing until it is"
  fi
done

# Most of those are only a directory: clone it and Kodi has the screen. Steam
# is not. It brings a menu tile, a privileged helper that lets it install
# Steam later without anybody typing a password at a television, and the
# switch that tells Kodi it may run the add-on at all -- Kodi registers one it
# merely finds on disk with enabled=0 and then answers RunScript with "not
# executing non-existing script", which reads as a broken add-on. Its own
# install.sh does all three, is idempotent, and knows it is already standing
# in ~/.kodi/addons, so it is handed over to rather than copied from.
# Two of them now, and for the same reason: an add-on that is only a
# directory needs nothing after the clone, and these two bring a menu tile and
# the switch that tells Kodi it may run them. Steam brings a privileged helper
# as well; Moonlight needs no root at all, because what it installs is a
# Flatpak for one user. Both installers are idempotent and both know they are
# already standing in ~/.kodi/addons.
STEAM_ADDON="$TARGET_HOME/.kodi/addons/script.steam"
if [ "$DRY" = 1 ]; then
  skip "would run $STEAM_ADDON/install.sh"
elif [ ! -x "$STEAM_ADDON/install.sh" ]; then
  [ -d "$STEAM_ADDON" ] && warn "no install.sh in $STEAM_ADDON"
elif [ "$TARGET_HOME" != "$HOME" ]; then
  # It installs for whoever runs it: a sudoers file, a tile in this user's
  # Kodi. None of that belongs to a throwaway --home directory.
  skip "not setting up Steam (installing into $TARGET_HOME)"
else
  if "$STEAM_ADDON/install.sh" 2>&1 | sed 's/^/  /'; then
    ok "Steam add-on set up"
  else
    warn "the Steam add-on did not finish setting up; run $STEAM_ADDON/install.sh"
  fi
fi

MOONLIGHT_ADDON="$TARGET_HOME/.kodi/addons/script.moonlight"
if [ "$DRY" = 1 ]; then
  skip "would run $MOONLIGHT_ADDON/install.sh"
elif [ ! -x "$MOONLIGHT_ADDON/install.sh" ]; then
  [ -d "$MOONLIGHT_ADDON" ] && warn "no install.sh in $MOONLIGHT_ADDON"
elif [ "$TARGET_HOME" != "$HOME" ]; then
  skip "not setting up Moonlight (installing into $TARGET_HOME)"
else
  if "$MOONLIGHT_ADDON/install.sh" 2>&1 | sed 's/^/  /'; then
    ok "Moonlight add-on set up"
  else
    warn "the Moonlight add-on did not finish; run $MOONLIGHT_ADDON/install.sh"
  fi
fi

# ----------------------------------------------------------- fourth player --
# Remote couch co-op: a guest opens a page somewhere else, plugs in their own
# controller and takes a seat in the game on this television. Its own project
# like the add-ons above, and cloned for the same reason -- but it is not a
# flat add-on repository, so it cannot join that loop. The Kodi screen at
# addons/script.fourthplayer is one face of a server that wants packages, a
# udev rule for /dev/uinput, a sudoers line for the GPU clocks and a user
# service, and only its own installer knows all of that. So this fetches the
# repository and hands over to it, rather than linking the add-on directory
# and leaving the menu entry to fail the first time somebody chooses it.
say "Fourth Player"
FP_URL=https://github.com/seastwood/Fourth-Player.git
FP_DIR="$TARGET_HOME/fourth-player"
FP_ADDON="$TARGET_HOME/.kodi/addons/script.fourthplayer"
if [ "$DRY" = 1 ]; then
  skip "would clone $FP_URL into $FP_DIR"
elif ! command -v git >/dev/null 2>&1; then
  warn "git is not installed, so Fourth Player was not fetched"
elif [ -d "$FP_DIR/.git" ]; then
  if git -C "$FP_DIR" pull --ff-only --quiet 2>/dev/null; then
    ok "fourth-player up to date ($(git -C "$FP_DIR" rev-parse --short HEAD))"
  else
    warn "fourth-player could not be updated; left as it is"
  fi
else
  # Before this phase existed the way to get it here was to rsync a working
  # tree across, which leaves a directory that looks right and cannot be
  # pulled. Move it aside rather than delete it: the settings and the session
  # state are elsewhere, but somebody may have edited this copy in place.
  if [ -e "$FP_DIR" ]; then
    mv "$FP_DIR" "$FP_DIR.replaced.$(date +%s)"
    ok "kept the old fourth-player as fourth-player.replaced.*"
  fi
  if git clone --quiet "$FP_URL" "$FP_DIR" 2>/dev/null; then
    ok "fourth-player cloned from $FP_URL"
  else
    warn "could not clone $FP_URL -- Fourth Player will be missing until it is"
  fi
fi

if [ "$DRY" = 1 ]; then
  skip "would run $FP_DIR/install/install.sh"
elif [ ! -x "$FP_DIR/install/install.sh" ]; then
  [ -d "$FP_DIR" ] && warn "no install/install.sh in $FP_DIR"
elif [ "$TARGET_HOME" != "$HOME" ]; then
  # It installs for whoever runs it: a user service, a udev rule, a sudoers
  # file. None of that belongs to a throwaway --home directory.
  skip "not installing Fourth Player (installing into $TARGET_HOME)"
elif [ "$SKIP_PACKAGES" = 1 ]; then
  skip "asked to skip packages, and Fourth Player installs its own"
  skip "run $FP_DIR/install/install.sh when you are ready for it"
else
  if [ "$(id -u)" != 0 ] && ! sudo -n true 2>/dev/null; then
    warn "this phase needs sudo as well; you will be prompted"
  fi
  "$FP_DIR/install/install.sh" 2>&1 | sed 's/^/   /'
  # A pipeline's status is the last command's, and sed always succeeds, so ask
  # for the installer's own -- otherwise a failed install reads as a good one.
  [ "${PIPESTATUS[0]}" = 0 ] || warn "the Fourth Player installer did not finish"
fi

# FOURTH PLAYER appears on the home menu when the add-on is on disk and not
# before, which is what makes this the check worth making: the console is
# meant to arrive with it, and printing "done" over a home menu that has no
# way to reach it would be the one failure nobody would go looking for.
if [ "$DRY" != 1 ] && [ "$TARGET_HOME" = "$HOME" ] && [ "$SKIP_PACKAGES" = 0 ] &&
   [ ! -e "$FP_ADDON" ]; then
  bad "Fourth Player is not on the home menu; run $FP_DIR/install/install.sh"
fi

# ------------------------------------------------------------------ assets --
say "Fonts and icons"
if [ -f "$REPO/assets/fonts/PressStart2P.ttf" ]; then
  copy_new "$REPO/assets/fonts/PressStart2P.ttf" "$TARGET_HOME/.local/share/fonts/PressStart2P.ttf"
  ok "pixel font in place (the picker and the exit bar both use it)"
else
  warn "no font in the repo; the picker will fall back to a default face"
fi
if [ -d "$REPO/assets/backgrounds" ]; then
  run "mkdir -p '$TARGET_HOME/.kodi/media/backgrounds'"
  for b in "$REPO"/assets/backgrounds/*.png; do
    [ -e "$b" ] && copy_new "$b" "$TARGET_HOME/.kodi/media/backgrounds/$(basename "$b")"
  done
  ok "menu background in place"
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
  :
  ok "restored this machine's captured state from local/"
else
  skip "no captured state (a fresh install: add ROMs and let the sync build the playlists)"
fi

# ---------------------------------------------------------- pro controller --
# A Nintendo Switch Pro Controller will not stay paired with a stock BlueZ:
# the input service refuses HID connections from devices that are not bonded,
# and the pad connects unbonded. It pairs, drops, and says nothing about why.
# switchpro.sh turns that limit off and names the adapter Nintendo, which the
# pad is happier against. Both are machine settings rather than this user's,
# which is why they are here and not in the Bluetooth add-on: whoever installs
# this console should not have to find a forum thread first.
say "Nintendo Switch Pro Controller"
if [ ! -x "$HERE/switchpro.sh" ]; then
  warn "switchpro.sh is missing; a Pro Controller may not pair"
elif [ "$DRY" = 1 ]; then
  "$HERE/switchpro.sh" --dry-run 2>&1 | sed 's/^/   --    /'
elif [ "$TARGET_HOME" != "$HOME" ]; then
  # /etc/bluetooth and the adapter belong to the machine, not to the throwaway
  # home being installed into.
  skip "not touching Bluetooth (installing into $TARGET_HOME)"
else
  "$HERE/switchpro.sh" 2>&1 | sed 's/^/   /'
  [ "${PIPESTATUS[0]}" = 0 ] || warn "the Pro Controller settings did not all apply"
fi

# --------------------------------------------------------------- autostart --
say "Starting Kodi at login"
# Without this a freshly built machine boots to a desktop and the television
# shows nothing until somebody finds a mouse.
if [ -f "$TARGET_HOME/.config/autostart/kodi.desktop" ]; then
  skip "already set to start at login"
elif [ -f "$REPO/templates/kodi.desktop" ]; then
  # .desktop files expand neither ~ nor $HOME in Exec=, so the template
  # carries @HOME@ and the real path is filled in here.
  copy_new "$REPO/templates/kodi.desktop" "$TARGET_HOME/.config/autostart/kodi.desktop"
  [ "$DRY" = 1 ] || sed -i "s|@HOME@|$TARGET_HOME|g" \
    "$TARGET_HOME/.config/autostart/kodi.desktop" 2>/dev/null
  # A copy the SETTINGS screen can put back after you switch autostart off.
  # Without it the toggle is one-way, which is worse than not having it.
  if [ "$DRY" != 1 ]; then
    mkdir -p "$TARGET_HOME/.local/share/retrobox"
    cp -f "$TARGET_HOME/.config/autostart/kodi.desktop" \
       "$TARGET_HOME/.local/share/retrobox/kodi.desktop.off" 2>/dev/null
  fi
  ok "Kodi will start at login (kodi-autostart.sh restarts it if it crashes)"
else
  warn "no autostart template; Kodi will not start on its own"
fi

# ------------------------------------------------------------------ games ---
say "Where games go"
GAMES="$TARGET_HOME/Games/emulation"
if [ "$DRY" = 1 ]; then
  skip "would create the ROM folders under $GAMES"
else
  made=0
  # One folder per system RetroArch can both identify and run -- 124 of them,
  # empty and waiting, so there is never a question about where something goes.
  while IFS=$'\t' read -r folder system core; do
    case "$folder" in ''|'#'*) continue ;; esac
    [ -d "$GAMES/$folder" ] || { mkdir -p "$GAMES/$folder"; made=$((made+1)); }
  done < "$REPO/system/systems.tsv"
  copy_new "$REPO/templates/games-README.txt" "$GAMES/README.txt"
  # A signpost from the repository, so the answer to "where do games go" is
  # visible from the place people will be looking.
  [ -e "$REPO/games" ] || ln -s "$GAMES" "$REPO/games"
  mkdir -p "$TARGET_HOME/Games/pc"
  copy_new "$REPO/templates/pc-README.txt" "$TARGET_HOME/Games/pc/README.txt"
  copy_new "$REPO/templates/pcgames.json" "$TARGET_HOME/.local/share/pcgames.json"
  # Where BIOS files go, said in the folder they go in.
  copy_new "$REPO/templates/bios-README.txt" \
           "$TARGET_HOME/.local/share/retroarch/system/README.txt"
  [ -e "$REPO/games" ] || ln -s "$GAMES" "$REPO/games"
  ok "$GAMES ($made folders created; see its README.txt)"
  ok "$TARGET_HOME/Games/pc for PC games, and BIOS files go in"
  ok "  $TARGET_HOME/.local/share/retroarch/system (see the README in it)"
fi

# ------------------------------------------------------------------- cores --
say "Emulator cores"
if [ "$DRY" = 1 ]; then
  skip "would download the cores listed in system/cores.txt"
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
if [ "$DRY" = 1 ]; then
  skip "would enable sync-games.timer and retro-backup.timer"
elif [ "$TARGET_HOME" != "$HOME" ]; then
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

# --------------------------------------------------------------- pc games ---
if [ "$WITH_OPTIONAL" = 1 ]; then
  say "PC games"
  if [ "$DRY" = 1 ]; then
    skip "would build JoyShockMapper"
  elif [ -x "$HERE/joyshockmapper.sh" ]; then
    "$HERE/joyshockmapper.sh" 2>&1 | sed 's/^/  /'
  else
    warn "joyshockmapper.sh is missing"
  fi
  # The two open-source engines. Separate script because it downloads a few
  # hundred megabytes and is worth being able to run on its own.
  if [ "$DRY" = 1 ]; then
    skip "would install Quake3e and ET Legacy"
  elif [ -x "$HERE/pcengines.sh" ]; then
    "$HERE/pcengines.sh" 2>&1 | sed 's/^/  /'
  else
    warn "pcengines.sh is missing"
  fi
fi

# -------------------------------------------------------------------- kodi --
say "Kodi"
if [ "$DRY" = 1 ]; then
  skip "would run install/kodi-setup.sh"
elif [ "$TARGET_HOME" != "$HOME" ]; then
  skip "not configuring Kodi (installing into $TARGET_HOME)"
elif [ -x "$HERE/kodi-setup.sh" ]; then
  if pgrep -x kodi.bin >/dev/null 2>&1; then
    warn "Kodi is running; quit it and run install/kodi-setup.sh"
  else
    "$HERE/kodi-setup.sh" 2>&1 | sed 's/^/  /'
  fi
else
  warn "kodi-setup.sh is missing; Kodi will keep its default look"
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
say "What is left to do"
cat <<'EOF'
   1. Put games in ~/Games/emulation/ -- there is a README.txt in there
      explaining the folders. BIOS files go in
      ~/.local/share/retroarch/system/ instead; system/bios-required.txt says
      which systems need which.

   2. Log out and back in, or just start Kodi. Your games appear on the home
      menu within ten minutes, with box art and player counts, or immediately
      if you run ~/.local/bin/sync_games.py.

   That is all for the consoles. There is a folder for every system RetroArch
   can run; the emulator core for one arrives the first time you put a game
   for it in.

   BIOS files go in ~/.local/share/retroarch/system/ -- there is a README in
   there, and system/bios-required.txt lists which systems need what.

   For Windows and native PC games, run install.sh --with-optional: that adds
   Wine and builds JoyShockMapper, and games are declared in
   ~/.local/share/pcgames.json (which explains itself).

   Achievements are switched on but have no account -- add yours in RetroArch's
   own menu. Backups do nothing until you name a destination in
   backup/backup.conf.
EOF

echo
if [ "$FAILED" = 0 ]; then
  printf '\033[1mdone\033[0m - %s\n' "$([ "$DRY" = 1 ] && echo 'dry run, nothing changed' || echo 'installed')"
else
  printf '\033[1mfinished with %d failure(s)\033[0m\n' "$FAILED"
fi
exit $FAILED
