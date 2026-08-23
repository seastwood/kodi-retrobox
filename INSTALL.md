# Installing

Start to finish on a fresh machine. Twenty minutes or so, most of it spent
downloading.

## What you need

* **Linux Mint 22 or Ubuntu 24.04** (`noble`). The installer warns and carries
  on elsewhere, but nothing else has been tested.
* A normal user account **with sudo**. Do not run any of this as root.
* Network, and around **1 GB** of downloads: 138 MB of emulator cores, 59 MB of
  shaders, the rest packages. `--with-optional` adds Wine and a compiler and is
  nearer **3 GB**.
* **No GPU required.** Without one it all still runs, just slowly.

Once it is finished none of this needs a keyboard. Getting there does.

## 1. Clone the repository

    sudo apt install -y git
    git clone https://github.com/seastwood/kodi-retrobox ~/retrobox

Anywhere will do, under any name — every script resolves its own location, so
`~/retrobox` is only tidiness. Your username does not matter either; step 2
deals with that.

## 2. Run the installer

    ~/retrobox/install/install.sh

or, if you want Windows and native PC games as well:

    ~/retrobox/install/install.sh --with-optional

It asks for your sudo password early, to install packages, and then runs
unattended.

You do **not** need to run `adopt.sh` yourself. The code was written on a
machine whose user is `retro` and has absolute paths baked in; the installer
notices they do not match your home directory and rewrites them before anything
else happens.

### Reading what it prints

Each phase prints a line per thing it did:

    ok     done, or already true
    --     skipped on purpose
    WARN   did not work, but the install can go on without it
    FAIL   did not work, and it matters

It exits with the number of failures. **Every phase is idempotent**: the fix
for a failure is to deal with the cause and run the exact same command again.
Nothing is done twice.

The phases are packages, directories, code, fonts and icons, configuration,
autostart, game folders, cores, shaders, timers, PC games (with
`--with-optional`), Kodi, and last the test suites — a few hundred checks that
what it just built actually works. Then it prints what is left to do.

## 3. Log out and back in

Kodi is now set to start at login, and logging back in is also what puts you in
the `input` group that controller mapping needs to reach `/dev/uinput`.

Kodi should come up on its own, in the retro skin, with the console menu. It
should not ask you to enable any add-ons.

## 4. Put your games in

    ~/Games/emulation/<system>/

There is a folder for every system RetroArch can run — 124 of them, empty and
waiting — with a `README.txt` explaining the conventions:

    ~/Games/emulation/snes/Super Mario World (USA).sfc
    ~/Games/emulation/sega-genesis/Sonic The Hedgehog (USA, Europe).md

Within ten minutes a timer finds them, identifies them by hash, fetches box
art, works out how many players each takes and adds them to the Kodi menu.
Nothing needs restarting. To make it happen now:

    ~/.local/bin/sync_games.py

The emulator core for a system is downloaded the first time you put a game for
it in, so there is nothing to install per console.

## 5. BIOS files, for the systems that need them

    ~/.local/share/retroarch/system/

**Not** in the game folders. A BIOS sitting among the ROMs looks exactly like a
game, and the sync deliberately drops it. `system/bios-required.txt` lists
which systems want which files, and that folder has a README too.

If a game will not start, the launcher says so on the television and names the
file it wanted. That message is the authority.

## Updating

    ~/retrobox/install/update.sh

That is the whole update: it stashes anything uncommitted, pulls, and runs
`install.sh` for you. `install.sh` is idempotent, so the second run only
does what has changed: new packages, new cores, re-linking anything the update
added, and re-applying the settings templates. Add `--with-optional` if you
use the PC games support, so the Wine and JoyShockMapper half updates too.

**Your games, saves and settings are not touched.** They live outside the
clone — in `~/Games`, `~/.local/share/retroarch` and `~/.kodi` — and the
repository holds only the definition. `local/` and `secrets/` are ignored by
git, so a pull never overwrites what this machine captured.

**Why not plain `git pull`?** You can, and on a current install it works. But
a machine installed before the code stopped baking in a home directory has
`adopt.sh`'s rewrites sitting in every tracked file. Those are not your edits,
yet git refuses to pull and blames you for them. `update.sh` stashes whatever
is there first, so nothing is lost and nothing has to be untangled by hand; it
prints the stash name, and `git stash list` and `git stash pop` do the rest.

**Quit Kodi before updating** if the update touches the skin — `kodi-setup.sh`
edits the add-on database Kodi holds open and refuses while it is running.
`install.sh` warns and carries on rather than failing, so you can quit Kodi
and re-run it afterwards.

## Optional extras

None of these are needed to play games.

**PC games** live in `~/Games/pc/` and are declared in
`~/.local/share/pcgames.json`, which documents its own fields. Needs
`--with-optional`. JoyShockMapper maps a controller to keyboard and mouse per
game, and the CONTROLLER entry on the Kodi home menu edits those mappings with
a controller, so it needs no keyboard either.

**Achievements.** RetroAchievements is switched on but has no account — add
yours in RetroArch's own menu. Nothing in this repository carries credentials.

**USB over IP** borrows a controller plugged into another machine. Run
`sudo ~/retrobox/bin/usbip-setup-root.sh` once; see the *USB over IP*
section of the README for the two steps that follow.

**Backups** do nothing until you name a destination in `backup/backup.conf`.

## If something goes wrong

    install/install.sh --dry-run         # what it would do, changing nothing
    install/install.sh --skip-packages   # when only apt failed, skip it
    install/adopt.sh --check             # which paths would be rewritten

To re-run the checks on their own:

    cd ~/.local/share/gametests && for t in test_*.py; do python3 "$t"; done

`--home DIR` runs the whole install against a throwaway directory instead of
your real account, which is how it gets tested without a spare machine.
