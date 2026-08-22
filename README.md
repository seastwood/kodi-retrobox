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

    git clone https://github.com/seastwood/kodi-retrobox ~/retro-console
    ~/retro-console/install/adopt.sh          # unless your user is `retro`
    ~/retro-console/install/install.sh

That adds the libretro PPA, installs the packages in
`system/packages.required.txt`, creates the directory layout, links the code
into place, merges `templates/retroarch-settings.conf` into RetroArch's config,
downloads the cores in `system/cores.txt` and the glsl shader pack, enables the
timers, and runs the test suites. It is idempotent — run it again after fixing
whatever went wrong.

Flags: `--dry-run`, `--skip-packages`, `--with-optional` (WineHQ, for the PC
games support), `--home DIR`.

Then add your own ROMs under `~/Games/emulation/<system>/` and any BIOS files
under `~/.local/share/retroarch/system/` (see `system/bios-required.txt`). The
sync timer picks them up within ten minutes, fetches box art, works out player
counts and rebuilds the Kodi menu.

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

Installing has been rehearsed by cloning this repository, adopting it to a
different home and installing into it: cores, shaders, add-ons, settings and
the full suite. It has **not** yet been run on genuinely fresh hardware, so the
package phase is the part still to prove.

## Hardware it grew up on

An AMD Phenom II with a Radeon RX 470, Linux Mint 22.3 (Ubuntu 24.04 noble).
Nothing is specific to that beyond the driver choices in the settings template.
