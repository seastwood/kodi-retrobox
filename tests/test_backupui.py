"""Backups a person at the television can actually set up.

backup.conf was a file only somebody with a terminal could edit, and the
result was a console whose nightly backup had been doing nothing since it was
installed -- no destination, so the script printed "nothing configured" and
exited 0, and systemd recorded a success every night for weeks.

So the screen owns the file. What is tested here is the round trip: what the
screen writes must be what retro_backup.sh reads, because those are two
programs agreeing about one file and nothing else checks that they still do.
"""
import importlib.machinery
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
MAIN = os.path.join(REPO, "addons", "plugin.program.retroarch", "main.py")

for name in ("xbmc", "xbmcgui", "xbmcplugin", "xbmcaddon", "xbmcvfs"):
    module = types.ModuleType(name)
    module.__getattr__ = lambda attr: (lambda *a, **k: None)
    sys.modules[name] = module
sys.modules["xbmcgui"].Dialog = lambda: types.SimpleNamespace(
    ok=lambda *a, **k: None, yesno=lambda *a, **k: False,
    select=lambda *a, **k: -1, input=lambda *a, **k: "",
    textviewer=lambda *a, **k: None, browse=lambda *a, **k: "")
sys.argv = ["plugin://x", "1", ""]

loader = importlib.machinery.SourceFileLoader("ra", MAIN)
ra = importlib.util.module_from_spec(
    importlib.util.spec_from_loader("ra", loader))
loader.exec_module(ra)

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


tmp = tempfile.mkdtemp(prefix="backupui-")
ra.BACKUP_CONF = os.path.join(tmp, "backup.conf")

print("-- what the screen writes, the screen reads back --")
wrote = ["local:/home/x/backups", "ssh:pi@192.168.1.50:/srv/retro-backup"]
ra.write_backup_settings(wrote, "9", "20G")
dests, generations, maxsize, passfile = ra.backup_settings()
check(dests == wrote, "the destinations survive, got %s" % dests)
check(generations == "9", "the count survives, got %s" % generations)
check(maxsize == "20G", "the ceiling survives, got %s" % maxsize)

print("\n-- and the backup script reads the same file the same way --")
# Two programs agreeing about one file. Nothing else checks that they do, and
# a screen that writes a key the script does not read would be a backup
# silently ignoring its own limit.
script = open(os.path.join(REPO, "bin", "retro_backup.sh")).read()
body = open(ra.BACKUP_CONF).read()
for key, pattern in (("GENERATIONS", r"GENERATIONS=\(\[0-9\]\+\)"),
                     ("MAXSIZE", r"MAXSIZE=\(\[0-9\]\+"),
                     ("SSH_KEY", r"SSH_KEY=")):
    check(key + "=" in body, "the screen writes %s" % key)
    check(key in script, "and the script reads %s" % key)
# The destination lines are matched by the script with this exact grep.
found = [l for l in body.splitlines()
         if re.match(r"^(local|ssh|path):", l)]
check(found == wrote,
      "and the destination lines match the script's own pattern, got %s" % found)

print("\n-- a console with nowhere to back up says so rather than looking fine --")
ra.write_backup_settings([], "7", "5G")
check(not ra.backup_configured(),
      "backup_configured() is false, which is what stops run_backup pretending")
body = open(ra.BACKUP_CONF).read()
check("nowhere yet" in body,
      "and the file says why it is empty, for whoever opens it next")

print("\n-- the ceiling offered is one the script understands --")
sizes = ["1G", "5G", "10G", "20G", "50G", ""]
for size in sizes:
    ra.write_backup_settings(["local:/x"], "7", size)
    _d, _g, back, _p = ra.backup_settings()
    check(back == size, "%r survives the round trip" % size)
# to_bytes is the script's own parser; every size the screen offers must parse.
prelude = script[:script.index("mapfile -t DESTS")]
# The script gives up early when there is no config, which is right for the
# script and unhelpful here: only its definitions are wanted.
prelude = re.sub(r'\[ -f "\$CONF" \] \|\| \{[^}]*\}', ":", prelude)
with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as fh:
    fh.write(prelude + "\n"
             + "for s in 1G 5G 10G 20G 50G; do to_bytes \"$s\"; done\n")
    probe = fh.name
done = subprocess.run(["bash", probe], capture_output=True, text=True, timeout=60)
os.unlink(probe)
parsed = [l for l in done.stdout.split() if l.isdigit() and l != "0"]
check(len(parsed) == 5,
      "all five sizes parse to real byte counts, got %s" % done.stdout.split())

print("\n-- a password is kept out of the backup it protects --")
check("BACKUP_PASSFILE" in open(MAIN).read(),
      "there is somewhere to put one")
check(".config/retrobox-backup-pass" in open(MAIN).read(),
      "under ~/.config, which is not among the things retro_backup.sh copies")
sources = script[script.index("SOURCES=("):script.index("while read -r extra")]
check("retrobox-backup-pass" not in sources,
      "and the backup does not carry it: a backup on somebody else's disk "
      "must not carry the credentials for that disk")
check("0o600" in open(MAIN).read(), "it is written readable only by its owner")

print("\n-- and the script prefers a key, but can use the password --")
check("sshpass -f" in script,
      "the password is handed over in a file, never on a command line where "
      "ps would show it to every account on the machine")
check("SSH_PASSFILE" in script, "the script reads the same key the screen writes")

print("\n-- what it contains is written down where it is asked --")
text = ra.BACKUP_CONTENTS
for want in ("save states", "playlists", "NOT carry your ROMs"):
    check(want in text, "it says %r" % want)

shutil.rmtree(tmp, ignore_errors=True)
print()
if fails:
    print("FAILURES: %d" % len(fails))
    for line in fails:
        print("  " + line)
    sys.exit(1)
print("test_backupui: all ok")
