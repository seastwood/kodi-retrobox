#!/bin/sh
# Run a Windows game under Wine.
#
# Three display strategies, picked per game through the env dict in pcgames.json:
#
#   (default)   Let the game change the display mode. Full-screen picture, but
#               this TV drops HDMI sync for a few seconds on every mode change,
#               and pcgame_launch.py has to put the mode back afterwards.
#
#   FB_SCALE=WxH
#               Pin the output to 1920x1080_60 and shrink the *framebuffer* to
#               WxH, which the GPU upscales to the panel. The game finds the
#               screen already at its own resolution, so no mode change happens
#               and the TV never re-syncs.
#
#   WINE_DESKTOP=<name>,<W>x<H>
#               Run inside a Wine virtual desktop. The game never owns the
#               display, so minimising and restoring is an ordinary window
#               operation instead of a lost D3D device and a black screen.
#               Size it to the *screen*: Wine only offers the game resolutions
#               that fit inside the desktop.
#
#   Dynamic scaling does NOT work: BF1942 renders its front-end menu at a fixed
#   800x600 (no .con setting changes it) and only switches to the configured
#   mode at level load, but xrandr cannot resize the framebuffer while the game
#   holds the display -- Configure crtc 0 failed -- and Wine pins its desktop
#   window at 0,0 so it cannot be moved or centred either. The small menu window
#   is therefore unavoidable when the desktop is screen-sized.
#
# usage: run-wine-game.sh <game-dir> <exe> [args...]
set -e
DIR="$1"; shift
EXE="$1"; shift
export WINEPREFIX="${WINEPREFIX:-$HOME/.local/share/wine/wc3}"
export WINEARCH=win32
export WINEDEBUG=-all
export DISPLAY="${DISPLAY:-:0}"

OUTPUT=HDMI-A-0
MODE=1920x1080_60
FULL_W=1920
FULL_H=1080

unscale() {
    xrandr --output "$OUTPUT" --scale 1x1 --mode "$MODE" 2>/dev/null || true
}

cleanup() {
    [ -n "$FB_SCALE" ] && unscale
    return 0
}

if [ -n "$FB_SCALE" ]; then
    # Trap first: a crash must not leave the screen stuck at a small framebuffer.
    trap cleanup EXIT HUP INT TERM
fi

[ -n "$FB_SCALE" ] && xrandr --output "$OUTPUT" --mode "$MODE" --scale-from "$FB_SCALE" 2>/dev/null || true

cd "$DIR"
if [ -n "$WINE_DESKTOP" ]; then
    wine explorer /desktop="$WINE_DESKTOP" "$EXE" "$@"
elif [ -n "$FB_SCALE" ]; then
    wine "$EXE" "$@"
else
    exec wine "$EXE" "$@"
fi
