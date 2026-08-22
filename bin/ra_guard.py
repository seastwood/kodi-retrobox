#!/usr/bin/env python3
"""Keep RetroArch's own config from bricking every launch.

`config_save_on_exit` is on, so RetroArch rewrites retroarch.cfg every time it
exits -- which means one bad write is permanent. That is not hypothetical: on
2026-08-21 a throwaway set of headless drivers was written into the real config
on exit, `sdl2` segfaults during video init on this GPU, and every launch died
instantly with nothing on screen to say why.

Only the handful of keys that decide whether RetroArch can start at all are
policed, and only those are ever rewritten, so everything a person changes in
the RetroArch menu is left alone.
"""

import os
import shutil
import sys

CFG = "/home/retro/.config/retroarch/retroarch.cfg"
GOOD = "/home/retro/.local/state/retroarch/retroarch.cfg.known-good"

# Values known to work on this machine. `sdl2` is absent from video_driver on
# purpose: it segfaults during video init on this GPU.
SAFE = {
    "video_driver": ({"gl", "glcore", "vulkan", "xvideo"}, "gl"),
    "audio_driver": ({"pulse", "alsa", "alsathread"}, "pulse"),
    "input_driver": ({"x", "udev", "sdl2"}, "x"),
    "input_joypad_driver": ({"udev", "sdl2", "linuxraw"}, "udev"),
    "menu_driver": ({"ozone", "xmb", "rgui", "glui"}, "ozone"),
}
# A truncated write, as opposed to a small but perfectly good config. Counting
# settings rather than bytes: a freshly installed machine has only the settings
# install.sh applied -- 26 of them, under a kilobyte -- and RetroArch does not
# write its full ~110 KB config until it has run once. Judging that by size
# called a healthy new machine broken.
MIN_SETTINGS = 10


def read_cfg(path):
    values = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                key, sep, value = line.partition("=")
                if sep:
                    values[key.strip()] = value.strip().strip('"')
    except OSError:
        return None
    return values


def faults(values):
    """The policed keys whose value would stop RetroArch starting."""
    if values is None:
        return [("<file>", "unreadable")]
    out = []
    for key, (allowed, _default) in sorted(SAFE.items()):
        value = values.get(key)
        if value is None:
            continue                      # absent means RetroArch's own default
        if value not in allowed:
            out.append((key, value))
    return out


def repair(bad, good_values):
    """Rewrite only the broken keys, in place, preserving every other line."""
    fixes = {}
    for key, _value in bad:
        want = good_values.get(key) if good_values else None
        if want not in SAFE[key][0]:
            want = SAFE[key][1]
        fixes[key] = want
    with open(CFG, encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()
    for i, line in enumerate(lines):
        key = line.partition("=")[0].strip()
        if key in fixes:
            lines[i] = '%s = "%s"\n' % (key, fixes[key])
    tmp = CFG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.writelines(lines)
    os.replace(tmp, CFG)
    return fixes


def settings_count(path):
    values = read_cfg(path)
    return 0 if values is None else len(values)


def main():
    os.makedirs(os.path.dirname(GOOD), exist_ok=True)
    count = settings_count(CFG) if os.path.exists(CFG) else 0

    # A truncated or missing config cannot be repaired key by key.
    if count < MIN_SETTINGS:
        if os.path.exists(GOOD) and settings_count(GOOD) >= MIN_SETTINGS:
            shutil.copy2(GOOD, CFG)
            print("restored the whole config: it had %d settings" % count)
            return 0
        print("config has %d settings and there is no known-good copy" % count,
              file=sys.stderr)
        return 1

    values = read_cfg(CFG)
    bad = faults(values)
    if not bad:
        # Healthy, so this is what to come back to.
        shutil.copy2(CFG, GOOD)
        return 0

    fixed = repair(bad, read_cfg(GOOD))
    for key, was in bad:
        print("repaired %s: %r -> %r" % (key, was, fixed[key]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
