"""A console that blanks its own screen and then asks for a password.

Four separate things wanted to do that -- light-locker, xfce4-power-manager's
DPMS, the X server's own screen saver, and xscreensaver -- and turning off any
three of them leaves a television that still goes black on its own. From the
sofa that is indistinguishable from a machine that has crashed.

--home is what makes this testable: it writes the autostart entries into the
directory it is given and touches no running session at all, so none of this
reaches the machine it runs on. That also means the xfconf half is not
exercised here; it needs a session bus, and a test that needed one would only
run on a machine that already worked.
"""
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
SCRIPT = os.path.join(REPO, "install", "noblank.sh")

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


def run(home, *args):
    return subprocess.run([SCRIPT, "--home", home, *args],
                          capture_output=True, text=True)


def entry(home, name):
    path = os.path.join(home, ".config", "autostart", name)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return handle.read()


check(os.access(SCRIPT, os.X_OK), "install/noblank.sh is there and runnable")

print("\na dry run changes nothing")
with tempfile.TemporaryDirectory() as home:
    done = run(home, "--dry-run")
    check(done.returncode == 0, "it succeeds")
    check("would" in done.stdout, "and says what it would do")
    check(not os.path.exists(os.path.join(home, ".config")),
          "without writing anything at all")

print("\nthe things that blank or lock a television are switched off")
with tempfile.TemporaryDirectory() as home:
    done = run(home)
    check(done.returncode == 0, "it succeeds: " + done.stderr.strip()[:80])
    for name, what in (("light-locker.desktop", "the locker LightDM ships"),
                       ("xscreensaver.desktop", "xscreensaver")):
        body = entry(home, name)
        check(body is not None, "%s has an override: %s" % (what, name))
        if body:
            # Hidden is the one that counts. A .desktop that merely exists,
            # or that has only X-GNOME-Autostart-enabled, is still started by
            # some launchers -- and the name has to match the file in
            # /etc/xdg/autostart exactly or it overrides nothing.
            check("Hidden=true" in body, "  and is hidden, not merely present")

print("\nand blanking is turned off again at every login")
# xset is a request to the running X server, not a setting. The next server
# knows nothing about it, so without an autostart entry this would be true
# until the first reboot and never again.
with tempfile.TemporaryDirectory() as home:
    run(home)
    body = entry(home, "retrobox-noblank.desktop")
    check(body is not None, "there is an entry that runs at login")
    if body:
        check("xset" in body and "-dpms" in body and "s off" in body,
              "  and it turns off both the screen saver and DPMS: "
              + next((l for l in body.splitlines() if l.startswith("Exec")), "?"))
        check("Hidden=true" not in body,
              "  and is not itself hidden, which would be a fine joke")

print("\nrunning it twice is the same as running it once")
with tempfile.TemporaryDirectory() as home:
    run(home)
    first = sorted(os.listdir(os.path.join(home, ".config", "autostart")))
    bodies = {n: entry(home, n) for n in first}
    run(home)
    again = sorted(os.listdir(os.path.join(home, ".config", "autostart")))
    check(first == again, "the same files: " + ", ".join(again))
    check(all(entry(home, n) == bodies[n] for n in again),
          "with the same contents, so a second install changes nothing")

print("\nit leaves anything else in there alone")
with tempfile.TemporaryDirectory() as home:
    where = os.path.join(home, ".config", "autostart")
    os.makedirs(where)
    keep = os.path.join(where, "kodi.desktop")
    with open(keep, "w", encoding="utf-8") as handle:
        handle.write("[Desktop Entry]\nExec=kodi-standalone\n")
    run(home)
    with open(keep, encoding="utf-8") as handle:
        check("kodi-standalone" in handle.read(),
              "the entry that starts Kodi is untouched -- this runs on a "
              "machine that is already set up")

print()
if fails:
    print("FAILURES: %d" % len(fails))
    sys.exit(1)
print("test_noblank: all ok")
