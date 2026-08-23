# Developing

Notes for working on this repository rather than installing from it.

## adopt.sh

Absolute paths are baked into the code — it was written on a machine whose user
is `retro`, which is invisible there and fatal anywhere else. `adopt.sh`
rewrites them, and `system/home.txt` records which home the code currently
points at.

Nothing needs remembering when installing: `install.sh` compares `home.txt`
against `$HOME` and runs `adopt.sh` itself, on a fresh install and again after
any update that pulls in files still carrying the old home.

    install/adopt.sh --check     report what would change, touch nothing
    install/adopt.sh /home/bob   adopt to a specific home

It matches files by content rather than by extension, which is why the
extensionless scripts (`jsm-hud`, `osk-toggle`) are caught too.

## capture.sh and deploy.sh

`install/capture.sh` snapshots this machine's current configuration into
`local/` and its credentials into `secrets/`. Both are git-ignored: they are one
person's library, settings and accounts. The backup carries them, so a full
restore needs a backup as well as a clone. What the repository publishes is the
*definition* — code, package lists, settings templates — which is what lets a
stranger start from it.

## Tests

    tests/   →  run any of them with python3

223 checks across seven suites: button mapping, the player picker, the sync
pipeline, the config guard, the hold-to-exit feedback, Bluetooth pairing and
USB/IP. They use synthetic devices and fake ROM trees, so they touch nothing
real. `install.sh` runs the lot as its last phase.

`install.sh --home DIR` runs the whole install against a throwaway directory
instead of a real account.

## State of testing

Built from nothing on a clean Linux Mint 22.3 virtual machine and played: wipe
the home directory, clone, one `install.sh` (52 seconds), drop a Mega Drive ROM
into `~/Games/emulation/sega-genesis/`, and the game appears on the Kodi home
menu with box art and a player count and launches with the CRT filter on.

Doing that found eight things no amount of testing on the original machine
could have, every one of them silent: a PPA name stripped twice, an apt failure
reported as success, a config-repair heuristic that called a brand new config
broken, Kodi never being started at login, every add-on needing approval by
hand, the skin never being fetched, and — the two that made a working install
look like an empty one — `content_database_path` and `libretro_info_path` never
being set, so RetroArch scanned a folder of games, recognised nothing, and
wrote no playlist without complaining.

A ninth turned up later: `/usr/bin/usbip` is a wrapper script that exits 2 when
the tools for the running kernel are missing, so every check that looked for
the file passed while usbip did nothing.

What remains untested is a controller: the virtual machine has no pads, so the
player picker and the hold-to-exit bar are proven only on the original machine.

## Hardware it grew up on

An AMD Phenom II with a Radeon RX 470, Linux Mint 22.3 (Ubuntu 24.04 noble).
Nothing is specific to that beyond the driver choices in the settings template.
