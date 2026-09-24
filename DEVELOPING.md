# Developing

Notes for working on this repository rather than installing from it.

## adopt.sh

**The code no longer contains a home directory.** Python resolves its own paths
with `os.path.expanduser("~/...")`, shell uses `$HOME`, systemd units use `%h`,
and the two Kodi files that expand none of those — `kodi.desktop` and the skin
settings — carry an `@HOME@` placeholder that the installer fills in. So there
is nothing in the repository for a different username to break.

What `adopt.sh` is still for is **captured state**: `local/` and `state/` hold
this machine's playlists, `pcgames.json` and Kodi settings, and those contain
real absolute paths because RetroArch and Kodi wrote them. Restoring a backup
onto a different user needs them rewritten. `system/home.txt` records which
home that captured state was written for, and `install.sh` runs `adopt.sh`
itself when it differs from `$HOME`.

**It must be safe to run twice**, because `install.sh` runs it every time. The
old home can be a *prefix* of the new one, so the match stops at a path-name
boundary — otherwise adopting to a name ending in `2` doubles the user name,
and doubles it again on the next install. `tests/test_adopt.py` covers exactly
that, and builds its homes from parts so the script under test cannot rewrite
its own fixtures.

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

About 760 checks across 36 suites -- the exact number depends on the machine, because the suites that need evdev or node skip where those are missing, and install.sh counts fewer again because it runs before the input group it just granted has taken effect: button mapping, the player picker, the sync
pipeline, the config guard, the hold-to-exit feedback, the Bluetooth setting a
Switch Pro Controller needs, carrying a game across a re-pick, joining a
multi-disc game that was unpacked one folder per disc, the controller profiles
reaching RetroArch at all, the progress bars actually moving, the
achievements account surviving an exit, only one launcher having the
screen, the password in front of Kodi's web server, the BIOS a system
needs before a game is launched, Quit meaning quit, and the daily check
that notices what nothing else was watching. They use synthetic devices and fake ROM trees, so they touch
nothing real. `install.sh` runs the lot as its last phase. Bluetooth pairing
and USB/IP have suites of their own, in the repositories that hold those
add-ons.

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

Later, the same thing again on real hardware rather than a virtual machine --
a wiped Linux Mint 22.3 desktop with different silicon -- and it found six
more, every one of them invisible on the machine this grew up on: a question
asked through a pipe that nobody could see and that waited for ever; the same
question asked again after a fix that tested the wrong stream; a phase that
worked only when run from inside its own checkout; bluetoothctl waiting for
ever on a machine with no Bluetooth adapter; H.264 reported as unavailable
because x264enc is in gstreamer's ugly set and a Mint desktop installs bad;
and a login-screen hook that granted access to a hardcoded username.

What remains untested is a controller: neither test machine had pads, so the
player picker and the hold-to-exit bar are proven only on the original one.

## Hardware it grew up on

An AMD Phenom II with a Radeon RX 470, Linux Mint 22.3 (Ubuntu 24.04 noble).
Nothing is specific to that beyond the driver choices in the settings template.
