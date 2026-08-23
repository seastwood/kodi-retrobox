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
    docs         INSTALL.md, NOTICE.md, DEVELOPING.md
    local/       this machine's own state (git ignores it)
    secrets/     this machine's credentials (git ignores it)

## Installing
First, install Linux Mint XFCE on a machine. 
Then:

    sudo apt install -y git                   # a stock Mint 22 has no git
    git clone https://github.com/seastwood/kodi-retrobox ~/retrobox
    ~/retrobox/install/install.sh

Then log out and back in, and put your games in `~/Games/emulation/`. That is
the whole process — **[INSTALL.md](INSTALL.md) walks through it step by step**,
including BIOS files, what the output means when a phase fails, and the
optional extras.

The clone can go anywhere and be called anything — every script works out
where it lives. Your username does not matter either.

To update later: `install/update.sh`. It is idempotent, and
your games, saves and settings live outside the clone, so nothing of yours is
touched. [INSTALL.md](INSTALL.md#updating) has the detail.

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
else. A PC game is whatever you say it is, declared in
`~/.local/share/pcgames.json`, which documents its own fields. They appear in
Kodi behind the PC GAMES entry.

**You do not have to edit that file.** The last tiles behind PC GAMES are
**ADD GAME** and **SYNC GAMES**. Add opens Kodi's file browser at `~/Games/pc`,
you pick the program, name it, and say whether Kodi should close while it runs;
a `.exe` is wired up through Wine automatically. The menu button on any game
offers **Remove** and **Rename** — remove takes the entry off the menu and
leaves the game on disk, and rename keeps the id, since the id is what finds
the controller mapping.

All of it works with a controller — the browser takes the d-pad and the
keyboard is on-screen — so games can be added, renamed and removed from the
sofa. **SYNC GAMES** runs the scan that otherwise happens on a ten-minute
timer, which is what you want when you have just copied something in and are
standing there; it sits on the consoles screen too.

`install.sh --with-optional` also installs two open-source engines. **ET
Legacy** arrives complete: Wolfenstein: Enemy Territory is freeware, so the
engine and its game data are both fetched and it is playable immediately.
**Quake3e** is the engine only — Quake III Arena's data is commercial, so you
supply your own `pak0.pk3`. It is declared straight away and stays hidden until
you do, which is what the `requires` field is for.

You rarely need to name a mapping: the game's id finds it (`bf2` →
`games/bf2.txt`), and anything without one of its own still gets
`_default.txt`, so every PC game is playable with a pad and has the on-screen
reference. A game declared here but not yet copied over is hidden rather than
shown as a tile that fails — so restore the list first, copy the games in
after, and each appears as it arrives.

Games with no controller support are still playable with one:
**JoyShockMapper** maps a pad to keyboard and mouse, per game, loaded while the
game runs and unloaded afterwards. It is built from source by
`install/joyshockmapper.sh` because the Linux port needs patches
(`system/joyshockmapper/`, pinned to an upstream commit), and 35 ready-made
mappings are installed with it. The CONTROLLER entry on the Kodi home menu
edits them with a controller, so that needs no keyboard either.

### USB over IP

The USB DEVICES entry borrows a controller plugged into another machine (a Pi,
say) over the network, so a pad in another room shows up here as a local USB
device. Everything the add-on does needs root, which it cannot arrange for
itself, so run this once:

    sudo ~/retrobox/bin/usbip-setup-root.sh

It installs the tools, loads `vhci-hcd` and makes that permanent, and grants
the user passwordless sudo for the `usbip` binary alone. Re-running it is
harmless.

One thing worth knowing, because it is invisible: `/usr/bin/usbip` is only a
wrapper script from `linux-tools-common`. It execs
`/usr/lib/linux-tools/$(uname -r)/usbip`, and when that is missing it exits 2 --
so `usbip` can be installed, present and executable, and still do nothing.
`linux-tools-generic` follows the GA kernel line, which is not necessarily the
kernel you booted, so an HWE kernel or one upgraded since the last reboot lands
exactly there. The setup script tests by running `usbip`, not by looking for
the file, and installs `linux-tools-$(uname -r)` when it has to.

It also generates `~/.ssh/id_ed25519_usbip`, the key the add-on uses for the
server and nothing else, and then prints the two steps that remain. Both of
those are typed **here** as well, even though they act on the server:
`ssh-copy-id` to install that key there, and an `ssh` session to give the
server the usbip tools, a running `usbipd`, and passwordless sudo for its own
`usbip` binary — whose path differs by distro, so check it with
`command -v usbip` on that machine. Check setup inside the add-on lists the
same three steps.

## What is not in here

**No games, and no BIOS files.** Not one ROM, disc image or BIOS dump — those
are the copyright of the people who made them, and you supply your own.
`system/bios-required.txt` is a list of filenames, nothing more.

**No box art and no console logos either.** Box art is fetched from
`thumbnails.libretro.com` when a game is identified, and console icons are
copied from RetroArch's own XMB assets (the `retroarch-assets` package) the
first time a system gets a playlist. Both arrive from their own publishers on
your machine; neither is redistributed here.

The artwork that *is* here — the menu icons and the background — is generated
pixel art. The one font is under the SIL Open Font License, and the
JoyShockMapper patch is a modification of MIT-licensed source; both licences
travel with them. **[NOTICE.md](NOTICE.md)** has the details and lists
everything that gets downloaded at install time, and from whom.

This repository itself is MIT licensed — see [LICENSE](LICENSE).

**Nothing personal, either.** No credentials, no accounts, no game library:
this machine's own configuration and secrets are git-ignored and carried by the
backup instead. Achievements are switched on but have no account attached — add
yours in RetroArch's own menu. Backups are switched off until you name a
destination in `backup/backup.conf`.

## Backups

Destinations go in `backup/backup.conf`, one per line — `local:`, `ssh:` or
`path:` — and several can run at once. Snapshots are dated and hard-linked, so
a second generation of 200 MB costs about 2 MB, and yesterday's copy of a save
you have just corrupted is still there. Daily, via `retro-backup.timer`.

## Tests

    <clone>/tests/  →  run any of them with python3

223 checks covering the button mapping, the player picker, the sync pipeline,
the config guard, the hold-to-exit feedback, Bluetooth pairing and USB/IP. They
use synthetic devices and fake ROM trees, so they touch nothing real, and
`install.sh` runs them as its last phase.

## Working on it

[DEVELOPING.md](DEVELOPING.md) covers `adopt.sh`, `capture.sh`, what a
from-nothing install on a clean virtual machine has proved so far, and what
remains untested.
