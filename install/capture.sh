#!/bin/bash
# Snapshot this machine's own state into local/, which git ignores.
#
# Code is symlinked, so it needs no capturing -- it is already the repository.
# This is for the things that live in place and are rewritten by other
# programs: RetroArch's config, the playlists, Kodi's settings, and the lists
# of what happens to be installed here.
#
# None of it is published. A person's playlists are their game library and
# their ROM paths; their Kodi settings carry their media server and their
# account names. The repository ships the *definition* (system/, templates/)
# so anyone can start from it; this captures the *state* so its owner can
# restore it from a backup.
set -u
R="$HOME/retro-console"
L="$R/local"
mkdir -p "$L/plists" "$L/kodi" "$R/system" "$R/secrets"

scrub_cfg() {
  sed -E 's/^(cheevos_token|cheevos_password) = ".*"/\1 = "REDACTED"/' "$1"
}
scrub_xml() {
  sed -E 's|(<setting id="services.webserverpassword"[^>]*>)[^<]*|\1REDACTED|' "$1"
}

# --- this machine's state ---------------------------------------------------
[ -f "$HOME/.config/retroarch/retroarch.cfg" ] &&
  scrub_cfg "$HOME/.config/retroarch/retroarch.cfg" > "$L/retroarch.cfg"
cp -f "$HOME/.local/share/retroarch/plists/"*.lpl "$L/plists/" 2>/dev/null
cp -f "$HOME/.local/share/gameplayers.manual.json" "$L/" 2>/dev/null
cp -f "$HOME/.local/share/pcgames.json" "$L/" 2>/dev/null
[ -f "$HOME/.kodi/userdata/guisettings.xml" ] &&
  scrub_xml "$HOME/.kodi/userdata/guisettings.xml" > "$L/kodi/guisettings.xml"
cp -f "$HOME/.kodi/userdata/addon_data/script.skinshortcuts/mainmenu.DATA.xml" \
      "$L/kodi/" 2>/dev/null
cp -f "$HOME/.config/autostart/kodi.desktop" "$L/kodi/" 2>/dev/null

# What is installed here, as opposed to what this console needs.
apt-mark showmanual 2>/dev/null | sort > "$L/packages.manual.txt"
ls "$HOME/.local/lib/retroarch/cores" 2>/dev/null | sort > "$L/retroarch-cores.txt"
ls "$HOME/.kodi/addons" 2>/dev/null | sort > "$L/kodi-addons.txt"
ls "$HOME/.local/share/retroarch/system" 2>/dev/null | sort > "$L/bios-present.txt"
uname -a > "$L/uname.txt"
lsb_release -ds 2>/dev/null > "$L/distro.txt"

# The real secrets, for the backup only; .gitignore excludes this directory.
{
  grep -E '^(cheevos_token|cheevos_password) = ' \
       "$HOME/.config/retroarch/retroarch.cfg" 2>/dev/null
  grep -oE '<setting id="services.webserverpassword"[^>]*>[^<]*' \
       "$HOME/.kodi/userdata/guisettings.xml" 2>/dev/null
} > "$R/secrets/values.txt" 2>/dev/null
chmod 600 "$R/secrets/values.txt" 2>/dev/null

# --- the shipped definition -------------------------------------------------
# Which home the absolute paths in the code point at. adopt.sh and install.sh
# both read this rather than guessing it out of the source, which a path that
# merely contains "/home/someone" was enough to fool.
printf '%s\n' "$HOME" > "$R/system/home.txt"
grep -rhoE 'ppa\.launchpadcontent\.net/[^/]+/[^/ ]+' /etc/apt/sources.list.d/* \
  2>/dev/null | sort -u > "$R/system/ppas.txt"
mkdir -p "$R/system/systemd"
cp -f "$HOME/.config/systemd/user/"{sync-games,retro-backup}.{service,timer} \
      "$R/system/systemd/" 2>/dev/null

echo "state captured into $L (not published); definition refreshed in $R/system"
