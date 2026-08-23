#!/bin/sh
# Launch Kodi at session start, and put it back if it dies.
#
# Guard: two Kodi instances fight over the display and produce a black,
# unresponsive screen, so never start a second one.
if pgrep -x kodi.bin >/dev/null 2>&1; then
    exit 0
fi
# Let the desktop session, audio and input devices settle first. Joystick
# enumeration in particular is happier once udev has finished.
sleep 10

# Kodi crashing used to leave a bare XFCE desktop on the television, which a
# controller cannot recover from -- it meant fetching a keyboard. Restart it
# instead. A clean exit (the user choosing Quit, or shutting down) is code 0
# and is left alone.
#
# The counter is there so a Kodi that dies instantly and repeatedly -- a broken
# add-on, a bad skin -- gives up rather than spinning forever and hiding the
# real problem behind a flickering screen.
# pcgame_launch.py leaves this file behind while a game that wants the whole
# screen is running. Kodi was killed on purpose, so the non-zero exit is not a
# crash and must not be treated as one.
HOLD="$HOME/.local/state/kodi-hold"
# Settings > "Restart Kodi if it crashes" writes this. Someone debugging a
# skin or an add-on wants Kodi to stay down when it dies, not to be put back
# five times before the message can be read.
NO_RESTART="$HOME/.config/retrobox-no-restart"

fails=0
while :; do
    started=$(date +%s)
    kodi -fs
    rc=$?
    [ "$rc" -eq 0 ] && break

    if [ -e "$HOLD" ]; then
        # Wait out the game rather than fighting it for the display. The file
        # holds the launcher's pid, so a launcher that was killed without
        # cleaning up is noticed straight away instead of stranding the
        # television on a desktop until some timeout expires.
        waited=0
        while [ -e "$HOLD" ]; do
            holder=$(cat "$HOLD" 2>/dev/null)
            if [ -n "$holder" ] && ! kill -0 "$holder" 2>/dev/null; then
                logger -t kodi-autostart "launcher $holder is gone; releasing the hold"
                rm -f "$HOLD"
                break
            fi
            sleep 5
            waited=$(( waited + 5 ))
        done
        logger -t kodi-autostart "game finished after ${waited}s; bringing Kodi back"
        fails=0
        sleep 2
        continue
    fi
    if [ -e "$NO_RESTART" ]; then
        logger -t kodi-autostart "Kodi exited $rc; restarting is switched off"
        break
    fi
    ran=$(( $(date +%s) - started ))
    if [ "$ran" -gt 60 ]; then
        fails=0                 # it worked for a while; this is a fresh problem
    else
        fails=$(( fails + 1 ))
    fi
    if [ "$fails" -ge 5 ]; then
        notify-send -u critical "Kodi keeps crashing" \
            "Gave up after 5 attempts. Exit code $rc." 2>/dev/null
        break
    fi
    logger -t kodi-autostart "Kodi exited $rc after ${ran}s; restarting (attempt $fails)"
    sleep 3
done
