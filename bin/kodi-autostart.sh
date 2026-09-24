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
# This script is symlinked into ~/.local/bin, so resolve the link before
# walking up out of bin/ -- $0 is the link, not the file.
REPO_DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
HOLD="$HOME/.local/state/kodi-hold"
# Settings > "Restart Kodi if it crashes" writes this. Someone debugging a
# skin or an add-on wants Kodi to stay down when it dies, not to be put back
# five times before the message can be read.
NO_RESTART="$HOME/.config/retrobox-no-restart"
# Kodi writes "Stopping the application..." the moment it begins an orderly
# shutdown, and nothing else writes it. See quit_was_asked_for.
KODI_LOG="$HOME/.kodi/temp/kodi.log"
# Settings > "Restore from a backup" writes the chosen backup here and quits
# Kodi. A restore cannot run while Kodi is up, so it happens in this gap.
RESTORE_REQ="$HOME/.local/state/restore-request"
RESTORE_LOG="$HOME/.local/state/restore.log"

# A JoyShockMapper left over from a game types into whatever has focus, and
# once Kodi is the thing with focus that is the menu. With no hold file there
# is no game entitled to the screen, so anything still running is a leftover.
tidy_orphans() {
    [ -e "$HOLD" ] && return 0
    for p in JoyShockMapper jsm-hud; do
        if pgrep -x "$p" >/dev/null 2>&1; then
            logger -t kodi-autostart "stopping orphaned $p before starting Kodi"
            pkill -x "$p" 2>/dev/null
        fi
    done
}

# Whether Kodi was on its way out on purpose, whatever it exited with.
#
# Kodi 20 segfaults tearing down Python interpreters at shutdown when an
# add-on service has not stopped in time -- plugin.video.jellyfin here, whose
# own log line is "failed to stop ... (may have ended)" immediately before the
# crash. Twelve of the thirteen crash logs on one machine are that, and
# several of them are from somebody simply choosing Quit.
#
# The exit code cannot tell the difference: an orderly shutdown that segfaults
# on the last step exits 139, exactly like a crash mid-game. So this loop put
# Kodi straight back up, and choosing Quit did not quit -- there was no way to
# leave Kodi from the sofa at all, and the television could not be got back to
# a desktop without ssh.
#
# The log can tell the difference. Everything Kodi does after that line is
# teardown: the player is stopped, the library closed, the settings written.
# A crash after it has cost nothing, and it is not something to restart from.
quit_was_asked_for() {
    [ -f "$KODI_LOG" ] || return 1
    tail -n 60 "$KODI_LOG" 2>/dev/null | grep -q "Stopping the application"
}

fails=0
while :; do
    tidy_orphans
    started=$(date +%s)
    # Not from whatever directory this was started in. A Kodi that dumps core
    # does it in its working directory, and started from the clone -- which is
    # how install.sh starts it -- that is a multi-gigabyte file inside a git
    # checkout, which update.sh then tries to stash.
    cd "$HOME" || exit 1
    kodi -fs
    rc=$?

    # Before the clean-exit check: a restore is asked for by quitting Kodi, so
    # rc is 0 and the loop would otherwise stop here and never come back.
    if [ -e "$RESTORE_REQ" ]; then
        from=$(head -1 "$RESTORE_REQ" 2>/dev/null)
        rm -f "$RESTORE_REQ"
        if [ -n "$from" ] && [ -d "$from" ]; then
            logger -t kodi-autostart "restoring from $from"
            notify-send "Restoring" "$(basename "$from")" 2>/dev/null
            "$REPO_DIR/install/restore.sh" --yes --from "$from" \
                > "$RESTORE_LOG" 2>&1
            if [ $? -eq 0 ]; then
                notify-send "Restore finished" "Kodi is starting again" 2>/dev/null
            else
                notify-send -u critical "Restore failed" \
                    "See $RESTORE_LOG" 2>/dev/null
            fi
        else
            logger -t kodi-autostart "restore asked for, but $from is not there"
        fi
        fails=0
        sleep 2
        continue
    fi

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
    # After the hold check, not before it: stopping Kodi to give a game the
    # screen is also an orderly shutdown, and that one does have to come back.
    if quit_was_asked_for; then
        logger -t kodi-autostart \
            "Kodi exited $rc, but it had been asked to quit; not restarting"
        break
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
