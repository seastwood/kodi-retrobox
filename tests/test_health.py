"""The check that notices the things nothing else notices.

Everything wrong with these machines this week was found by somebody going
looking. The three scripts that could have said so -- retrobox-check,
retrobox-ready, security-check -- all answer on a terminal, and nobody using a
games console sits at one.

The failure that makes the case: one machine's nightly backup had been doing
nothing since it was installed. No backup.conf, so retro_backup.sh printed
"nothing configured, doing nothing" and exited 0, and systemd recorded a
success every night for weeks. Game saves unprotected, nothing said.

Two things have to hold for this to be worth having. It has to catch that --
a success that did nothing is the hardest kind of failure to see -- and it has
to stay quiet. A console that says the same thing every morning is one whose
notifications stop being read, which is the state it exists to fix.
"""
import importlib.machinery
import importlib.util
import json
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
loader = importlib.machinery.SourceFileLoader(
    "health", os.path.join(REPO, "bin", "retrobox-health"))
m = importlib.util.module_from_spec(
    importlib.util.spec_from_loader("health", loader))
loader.exec_module(m)

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


tmp = tempfile.mkdtemp(prefix="health-")
m.HOME = tmp
m.STATE = os.path.join(tmp, "state.json")
m.KODI_SEND = os.path.join(tmp, "no-kodi-send")     # nothing is ever sent

told = []
m.tell_kodi = lambda title, message: told.append((title, message))

# What each shelled-out command pretends to say.
SCRIPT = {}


def fake_run(args, timeout=120):
    key = " ".join(str(a) for a in args)
    for needle, answer in SCRIPT.items():
        if needle in key:
            return answer
    return 0, ""


m.run = fake_run


def healthy():
    SCRIPT.clear()
    SCRIPT.update({
        "ExecMainStartTimestamp": (0, "Thu 2026-09-24 00:02:27 CDT"),
        "-u retro-backup.service": (0, "00:02:29 backed up 477M to /srv/nas/2026-09-24"),
        "show fourth-player.service": (0, "active"),
        "show sync-games.timer": (0, "waiting"),
        "show retro-backup.timer": (0, "waiting"),
        "show retro-padmap.path": (0, "active"),
        "--failed": (0, ""),
        "-u fourth-player": (0, "everything fine\n"),
        "coredumpctl": (0, ""),
        "retrobox-ready": (0, "   ok    all good\n"),
        "-u sync-games.service": (0, "scanned: nothing\ndone\n"),
    })


print("-- a console with nothing wrong says nothing --")
healthy()
code = m.main(["--quiet"])
check(code == 0, "it exits 0, got %s" % code)
check(m.problems == [], "and reports no problems, got %s" % m.problems)

print("\n-- a backup that runs, does nothing, and succeeds --")
# The one that hid for weeks. Exit 0, a systemd success, and no data saved.
healthy()
SCRIPT["-u retro-backup.service"] = (
    0, "06:33:08 no /home/x/backup/backup.conf - nothing configured, doing nothing")
code = m.main(["--quiet"])
keys = [k for k, _ in m.problems]
check("backup-unconfigured" in keys,
      "it is caught, got %s" % keys)
check(code == 1, "and the exit status says so")
said = dict(m.problems)["backup-unconfigured"]
check("backup.conf" in said and "Fix:" in said,
      "and the line says what to do about it: %r" % said[:80])

print("\n-- a backup onto the machine's own disk is worth a word, not an alarm --")
healthy()
SCRIPT["-u retro-backup.service"] = (
    0, "00:02:29 backed up 477M to %s/backups/2026-09-24" % tmp)
m.main(["--quiet"])
check("backup-unconfigured" not in [k for k, _ in m.problems],
      "it is not called a failure -- it is working")
check(any("own disk" in n for n in m.notes),
      "but it is noted, got %s" % m.notes)

print("\n-- a service being restarted round the clock is invisible without this --")
# It is "active" every time anybody looks. The crash count is the only tell.
healthy()
SCRIPT["-u fourth-player"] = (0, "Fatal Python error: Segmentation fault\n" * 7)
m.main(["--quiet"])
said = dict(m.problems).get("fourth-player-segv", "")
check("7 time(s)" in said, "the count is reported, got %r" % said[:70])

print("\n-- and the assertion behind it is a note, not an alarm --")
healthy()
SCRIPT["-u fourth-player"] = (0, "G_IS_OBJECT assertion\n" * 8)
m.main(["--quiet"])
check(not any(k == "fourth-player-segv" for k, _ in m.problems),
      "a warning without a crash is not a crash")
check(any("no longer fatal" in n for n in m.notes),
      "but it is said, because it means the bug is still there: %s" % m.notes)

print("\n-- it says a thing once, not every morning --")
os.unlink(m.STATE) if os.path.exists(m.STATE) else None
del told[:]
healthy()
SCRIPT["-u retro-backup.service"] = (0, "nothing configured, doing nothing")
m.main([])
check(len(told) == 1, "the first run puts it on the television, got %s" % told)
m.main([])
check(len(told) == 1,
      "the second run does not, because nothing is new: got %d notification(s)"
      % len(told))

print("\n-- but a new problem does get through --")
SCRIPT["show fourth-player.service"] = (0, "failed")
m.main([])
check(len(told) == 2, "a problem that was not there yesterday is told, got %s"
      % len(told))
check("more" in told[-1][1] or "down" in told[-1][1] or "failed" in told[-1][1],
      "and it is the new one that is named: %r" % (told[-1],))

print("\n-- a problem going away is remembered, so it can be news again --")
healthy()
m.main([])
kept = json.load(open(m.STATE))["problems"]
check(kept == [], "nothing is remembered once it is fixed, got %s" % kept)
del told[:]
SCRIPT["-u retro-backup.service"] = (0, "nothing configured, doing nothing")
m.main([])
check(len(told) == 1, "so the same fault coming back is told again")

print("\n-- --quiet never touches the television --")
del told[:]
m.main(["--quiet"])
check(told == [], "nothing was sent, got %s" % told)

print("\n-- the timer is installed and enabled by the install --")
units = os.path.join(REPO, "system", "systemd")
check(os.path.exists(os.path.join(units, "retrobox-health.timer")),
      "there is a timer")
check(os.path.exists(os.path.join(units, "retrobox-health.service")),
      "and a service for it")
service = open(os.path.join(units, "retrobox-health.service")).read()
check("SuccessExitStatus=0 1" in service,
      "exit 1 means 'found something', not 'the check broke' -- without this "
      "systemd reports the check itself as failed every time it works")
install = open(os.path.join(REPO, "install", "install.sh")).read()
check("retrobox-health.timer" in install, "and install.sh enables it")

shutil.rmtree(tmp, ignore_errors=True)
print()
if fails:
    print("FAILURES: %d" % len(fails))
    for line in fails:
        print("  " + line)
    sys.exit(1)
print("test_health: all ok")
