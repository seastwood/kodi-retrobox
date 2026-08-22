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
fails=0
while :; do
    started=$(date +%s)
    kodi -fs
    rc=$?
    [ "$rc" -eq 0 ] && break
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
