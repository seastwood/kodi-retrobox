# kodi-retrobox

A Linux Mint / XFCE machine turned into a games console: Kodi as the front end,
RetroArch behind it, a player-picker before every game, achievements, backups,
and a test suite. This repository is the whole definition, so the same console
can be built again on other hardware.

## What it actually does

* **Kodi is the console.** Games appear on the home menu per system, with box
  art, the number of players each takes, favourites, recently played, and a
  MULTIPLAYER view that lists everything four people can play across every
  system at once.
* **A player picker before each game** assigns controllers to ports, sized to
  the game — one-player games with one pad skip it entirely. It reads each
  pad's real buttons from RetroArch's own controller profiles, so "A" is the
  button printed A whether that is an Xbox pad or a Switch pad.
* **Hold Start for two seconds to quit**, with a progress bar drawn over the
  running game. Games auto-save and auto-resume, so quitting is closer to
  putting a console to sleep.
* **Failures are visible.** A missing BIOS or a missing core says so on the
  television instead of dropping you back to the menu in silence.
* **It looks after itself.** The RetroArch config is repaired if a bad exit
  breaks it, Kodi restarts if it crashes, new ROMs are found and given box art
  and player counts on a timer, and everything that cannot be reinstalled is
  backed up.

## Layout

    bin/         the scripts, symlinked into ~/.local/bin
    addons/      four hand-written Kodi add-ons, symlinked into ~/.kodi/addons
    tests/       seven suites, 223 checks, symlinked to ~/.local/share/gametests
    assets/      the pixel font and the menu icons
    templates/   the RetroArch settings this console sets
    system/      what to install: packages, PPAs, cores, BIOS notes, units
    install/     install.sh, adopt.sh, deploy.sh, capture.sh
    backup/      backup.conf.example - copy to backup.conf and edit
    local/       this machine's own state (git ignores it)
    secrets/     this machine's credentials (git ignores it)

## Installing

    sudo apt install -y git                   # a stock Mint 22 has no git
    git clone https://github.com/seastwood/kodi-retrobox ~/retro-console
    ~/retro-console/install/adopt.sh          # unless your user is `retro`
    ~/retro-console/install/install.sh

Then put your games in `~/Games/emulation/` and start Kodi. That is the whole
process.

For Windows and native PC games as well, use `install.sh --with-optional`:
that adds Wine and builds JoyShockMapper (see *PC games* below).

That adds the libretro PPA, installs the packages in
`system/packages.required.txt`, creates the directory layout, links the code
into place, merges `templates/retroarch-settings.conf` into RetroArch's config,
downloads the cores in `system/cores.txt` and the glsl shader pack, enables the
timers, and runs the test suites. It is idempotent — run it again after fixing
whatever went wrong.

Flags: `--dry-run`, `--skip-packages`, `--with-optional` (WineHQ, for the PC
games support), `--home DIR`.

## Games

`~/Games/emulation/` has **a folder for every system RetroArch can identify and
run** -- 124 of them, empty and waiting. Drop a game in and within ten minutes
(or immediately, with `~/.local/bin/sync_games.py`) it is identified, given box
art and a player count, and added to the Kodi menu. **The emulator core for a
system is downloaded the first time you put a game for it in**, so there is
nothing to install per console.

The folder name is a convention rather than a rule: games are identified by
hashing them, so one in the "wrong" folder is still filed correctly.

### BIOS files

Some systems cannot run without one -- Sega CD, Saturn, Dreamcast, PlayStation,
PC Engine CD, 3DO, Lynx and a few more. They go in

    ~/.local/share/retroarch/system/

**not** in the ROM folders, where a stray BIOS looks exactly like a game and is
deliberately dropped from the playlist. `system/bios-required.txt` lists every
system that needs one and the exact filename; the same advice is put in that
folder as a README when you install. And if a game will not start, the launcher
names the missing file on the television.

### PC games

`~/Games/emulation` is for emulated consoles; `~/Games/pc/` is for everything
else. Nothing there is scanned -- a PC game is whatever you say it is, declared
in `~/.local/share/pcgames.json`, which documents its own fields. They appear
in Kodi behind the PC GAMES entry.

Games with no controller support are still playable with one:
**JoyShockMapper** maps a pad to keyboard and mouse, per game, loaded while the
game runs and unloaded afterwards. It is built from source by
`install/joyshockmapper.sh` because the Linux port needs patches
(`system/joyshockmapper/`, pinned to an upstream commit), and 35 ready-made
mappings are installed with it. The CONTROLLER entry on the Kodi home menu
edits them with a controller, so that needs no keyboard either.

### adopt.sh

Absolute paths are baked into the code — it was written on a machine whose user
is `retro`. That is invisible there and fatal anywhere else, so `adopt.sh`
rewrites them once and `install.sh` refuses to run until they agree.

## Nothing personal is in here

No credentials, no accounts, no game library. `install/capture.sh` snapshots
this machine's configuration into `local/` and its credentials into `secrets/`,
both of which git ignores; the backup carries them, and a restore needs a
backup as well as a clone. What ships is the definition — code, package lists,
settings template — which is why a stranger can start from it.

Achievements are switched on but have no account attached; add yours in
RetroArch's own menu. Backups are switched off until you name a destination in
`backup/backup.conf`.

## Backups

Destinations go in `backup/backup.conf`, one per line — `local:`, `ssh:` or
`path:` — and several can run at once. Snapshots are dated and hard-linked, so
a second generation of 200 MB costs about 2 MB, and yesterday's copy of a save
you have just corrupted is still there. Daily, via `retro-backup.timer`.

## Tests

    ~/retro-console/tests/  →  run any of them with python3

223 checks covering the button mapping, the player picker, the sync pipeline,
the config guard, the hold-to-exit feedback, Bluetooth pairing and USB/IP. They
use synthetic devices and fake ROM trees, so they touch nothing real.

## State of testing

Built from nothing on a clean Linux Mint 22.3 virtual machine and played: wipe
the home directory, clone, `adopt.sh`, one `install.sh` (52 seconds), drop a
Mega Drive ROM into `~/Games/emulation/sega-genesis/`, and the game appears on
the Kodi home menu with box art and a player count and launches with the CRT
filter on.

Doing that found eight things no amount of testing on the original machine
could have, every one of them silent: a PPA name stripped twice, an apt failure
reported as success, a config-repair heuristic that called a brand new config
broken, Kodi never being started at login, every add-on needing approval by
hand, the skin never being fetched, and -- the two that made a working install
look like an empty one -- `content_database_path` and `libretro_info_path`
never being set, so RetroArch scanned a folder of games, recognised nothing,
and wrote no playlist without complaining.

What remains untested is a controller: the virtual machine has no pads, so the
player picker and the hold-to-exit bar are proven only on the original machine.

## Hardware it grew up on

An AMD Phenom II with a Radeon RX 470, Linux Mint 22.3 (Ubuntu 24.04 noble).
Nothing is specific to that beyond the driver choices in the settings template.
