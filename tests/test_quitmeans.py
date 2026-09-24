"""Choosing Quit has to actually quit.

Kodi 20 segfaults tearing down Python interpreters at shutdown when an add-on
service has not stopped in time. On one machine here that is
plugin.video.jellyfin, which logs "failed to stop ... (may have ended)"
immediately before the crash, and twelve of the thirteen crash logs on that
machine are the same stack:

    #0  PyObject_GC_UnTrack ()          libpython3.12
    #6  Py_EndInterpreter ()
    #7  CPythonInvoker::onExecutionDone()

Several of them are from somebody simply choosing Quit. Jellyfin is configured
against a real server on both machines, so removing it is not the answer, and
the crash is not ours to fix.

What is ours is what happens next. The wrapper restarts Kodi on any non-zero
exit, and an orderly shutdown that segfaults on its last step exits 139 --
exactly like a crash in the middle of a game. So Kodi came straight back up
and there was no way to leave it from the sofa at all.

Kodi writes "Stopping the application..." when it begins an orderly shutdown
and nothing else writes it. Everything after that line is teardown -- the
player stopped, the library closed, the settings written -- so a crash after
it has cost nothing and is not something to restart from.
"""
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
SCRIPT = os.path.join(REPO, "bin", "kodi-autostart.sh")

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


source = open(SCRIPT).read()

print("the wrapper knows the difference")
check("quit_was_asked_for" in source, "there is a test for it")
check("Stopping the application" in source,
      "and it is Kodi's own shutdown line, not a guess at the exit code")

print("\nit is asked in the right order")
# Stopping Kodi to give a game the whole screen is also an orderly shutdown,
# and that one does have to come back -- so the hold file has to be looked at
# first or every PC game would leave the television on a desktop.
hold = source.index('if [ -e "$HOLD" ]; then')
quit_ = source.index("if quit_was_asked_for; then")
restore = source.index('if [ -e "$RESTORE_REQ" ]; then')
check(restore < quit_, "a restore request is handled before it")
check(hold < quit_,
      "and so is the hold a running game takes, or quitting Kodi for a game "
      "would be read as quitting for good and the game would come back to a "
      "desktop")

print("\nand it runs somewhere a core dump does no harm")
check('cd "$HOME"' in source,
      "Kodi is started from home: a core dump goes to the working directory, "
      "and started from the clone -- which is how install.sh starts it -- "
      "that is a multi-gigabyte file inside a git checkout")
check("core" in open(os.path.join(REPO, ".gitignore")).read().split(),
      "with core files ignored as well, so one that does land there cannot "
      "be swept into a stash by update.sh")


def run_wrapper(log_tail, exit_code):
    """Run the real decision with a fake Kodi and a fake log.

    The loop itself is what is under test, so kodi, pgrep and the rest are
    replaced rather than the logic being copied out and re-read here.
    """
    tmp = tempfile.mkdtemp(prefix="quit-")
    home = os.path.join(tmp, "home")
    os.makedirs(os.path.join(home, ".kodi", "temp"))
    os.makedirs(os.path.join(home, ".local", "state"))
    os.makedirs(os.path.join(home, ".config"))
    with open(os.path.join(home, ".kodi", "temp", "kodi.log"), "w") as fh:
        fh.write(log_tail)
    fake = os.path.join(tmp, "bin")
    os.makedirs(fake)
    # A Kodi that exits how the test says, once; a second call would mean the
    # loop went round again, which is the failure being looked for.
    with open(os.path.join(fake, "kodi"), "w") as fh:
        fh.write("#!/bin/sh\necho ran >> %s/ran\nexit %d\n" % (tmp, exit_code))
    for stub, body in (("pgrep", "exit 1"), ("logger", "exit 0"),
                       ("pkill", "exit 0"), ("notify-send", "exit 0")):
        with open(os.path.join(fake, stub), "w") as fh:
            fh.write("#!/bin/sh\n%s\n" % body)
    for name in os.listdir(fake):
        os.chmod(os.path.join(fake, name), 0o755)
    env = dict(os.environ)
    env["HOME"] = home
    env["PATH"] = fake + os.pathsep + env["PATH"]
    try:
        done = subprocess.run(["sh", SCRIPT], env=env, timeout=90,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        started = 0
        try:
            started = len(open(os.path.join(tmp, "ran")).read().split())
        except OSError:
            pass
        return started, done.returncode
    except subprocess.TimeoutExpired:
        return -1, -1
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


ORDERLY = ("info <general>: Stopping the application...\n"
           "info <general>: Stopping player\n"
           "info <general>: CServiceAddonManager: failed to stop "
           "plugin.video.jellyfin (may have ended)\n")
MIDGAME = ("info <general>: Loading skin file\n"
           "info <general>: GL_VENDOR = Intel\n")

print("\na segfault on the way out of a deliberate quit is not a crash")
started, _rc = run_wrapper(ORDERLY, 139)
check(started == 1,
      "Kodi was started once and left alone, got %s starts" % started)

print("\na segfault with no shutdown behind it still brings Kodi back")
started, _rc = run_wrapper(MIDGAME, 139)
check(started > 1,
      "Kodi was restarted, got %s starts -- a real crash mid-game must not "
      "leave the television on a desktop" % started)

print("\nand a clean exit is still a clean exit")
started, _rc = run_wrapper(MIDGAME, 0)
check(started == 1, "started once, got %s" % started)

print()
if fails:
    print("FAILED: %d" % len(fails))
    for line in fails:
        print("  " + line)
    sys.exit(1)
print("test_quitmeans: all ok")
