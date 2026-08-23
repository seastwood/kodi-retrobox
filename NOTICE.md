# Third-party components

What this repository carries that someone else wrote, and under what terms.

## Included in the repository

**Press Start 2P** — `assets/fonts/PressStart2P.ttf`
Copyright 2012 The Press Start 2P Project Authors (cody@zone38.net),
Reserved Font Name "Press Start 2P". Licensed under the SIL Open Font License
1.1, whose text is in `assets/fonts/OFL.txt` beside it, as that licence
requires.

**JoyShockMapper patch** — `system/joyshockmapper/linux-fixes.patch`
A modification of [JoyShockMapper](https://github.com/JibbSmart/JoyShockMapper)
by Julian "Jibb" Smart and contributors, MIT licensed. The patch is a
derivative of that source, so their licence travels with it in
`system/joyshockmapper/UPSTREAM-LICENSE.md`. Only the patch is here; the
source itself is cloned from upstream at install time, pinned to the commit in
`upstream-commit.txt`. (GitHub reports the project as "NOASSERTION" because
its `LICENSE.md` opens with a Markdown heading; the text underneath is the
plain MIT licence.)

**Everything else** — the artwork in `assets/` is generated pixel art, the
scripts and Kodi add-ons are original, and `system/bios-required.txt` is a list
of filenames.

## Fetched at install or run time, never redistributed here

| What | From | When |
| --- | --- | --- |
| Emulator cores | `buildbot.libretro.com` | first game for a system appears |
| Shader pack | `buildbot.libretro.com` | install |
| Box art | `thumbnails.libretro.com` | a game is identified |
| Kodi skin and add-ons | `mirrors.kodi.tv` | install |
| JoyShockMapper source | `github.com/JibbSmart/JoyShockMapper` | `--with-optional` |
| Wine | `dl.winehq.org` | `--with-optional` |
| RetroArch, Kodi, tools | Ubuntu archive and the libretro PPA | install |

These land on your machine from their own publishers. Nothing is mirrored or
re-hosted here.

## Acknowledged, not used

The USB/IP add-on's design — which four `usbip` calls to make, and on which
side — was learned from reading **usb-audio-ip-client**, a PyQt tool by another
author. No code from it is here; see the note at the top of
`addons/script.usbip/usbip_core.py`.
