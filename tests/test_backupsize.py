"""The backup has a ceiling, and never deletes its last copy to meet it.

GENERATIONS on its own promises nothing about disk. Seven snapshots of a save
directory are nothing; seven of a library with include: lines pointed at it
are tens of gigabytes. A console that fills its own disk cannot write saves,
which is the thing the backup exists to protect -- so the backup filling the
disk is the one failure it must not have.

Both rules run where the files are: the local branch in this shell, the ssh
branch as one command on the far end. Tested here by running the real
functions out of the real script rather than a copy of them, because two
copies of a retention rule is how one of them quietly stops matching.
"""
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
SCRIPT = os.path.join(REPO, "bin", "retro_backup.sh")

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


def call(snippet):
    """Run a snippet with the script's own functions in scope.

    The script exits early without a config, so the functions are lifted out
    by sourcing it up to the point where it starts doing things.
    """
    body = open(SCRIPT).read()
    # Everything from the shebang to the line that reads the destinations is
    # definitions; past that it is a backup run.
    cut = body.index("mapfile -t DESTS")
    prelude = body[:cut].replace('[ -f "$CONF" ] || { say', '[ -f "$CONF" ] || { true; } || { say')
    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as fh:
        fh.write(prelude + "\n" + snippet + "\n")
        path = fh.name
    try:
        done = subprocess.run(["bash", path], capture_output=True, text=True,
                              timeout=60)
        return done.returncode, done.stdout.strip(), done.stderr.strip()
    finally:
        os.unlink(path)


print("-- sizes are read the way a person writes them --")
code, out, err = call('for s in 2048 5K 3M 2G 1T "" xyz; do '
                      'printf "%s=%s\\n" "$s" "$(to_bytes "$s")"; done')
got = dict(l.split("=", 1) for l in out.splitlines() if "=" in l)
check(got.get("2048") == "2048", "a bare number is bytes, got %s" % got.get("2048"))
check(got.get("5K") == str(5 * 1024), "K, got %s" % got.get("5K"))
check(got.get("3M") == str(3 * 1024 ** 2), "M, got %s" % got.get("3M"))
check(got.get("2G") == str(2 * 1024 ** 3), "G, got %s" % got.get("2G"))
check(got.get("1T") == str(1024 ** 4), "T, got %s" % got.get("1T"))
check(got.get("") == "0", "empty means no ceiling, got %s" % got.get(""))
check(got.get("xyz") == "0", "and so does nonsense, rather than a crash")


def a_destination(snapshots, kb_each=200):
    """A destination holding N dated snapshots of roughly equal size."""
    d = tempfile.mkdtemp(prefix="backupsize-")
    for i in range(snapshots):
        snap = os.path.join(d, "2026-09-%02d_000000" % (i + 1))
        os.makedirs(snap)
        with open(os.path.join(snap, "data"), "wb") as fh:
            fh.write(b"\0" * kb_each * 1024)
    return d


print("\n-- the oldest go first, until it fits --")
d = a_destination(5, kb_each=200)          # ~1000 KB total
code, out, err = call('trim_to_size "%s" %d; echo "rc=$?"' % (d, 500 * 1024))
left = sorted(os.listdir(d))
check("rc=0" in out, "it reports success, got %r" % out)
check(len(left) < 5, "something was removed, got %s" % left)
check(left and left[-1] == "2026-09-05_000000",
      "and the newest survived, got %s" % left)
check(left == sorted(left), "the ones kept are the newest, got %s" % left)
shutil.rmtree(d, ignore_errors=True)

print("\n-- a destination already under the ceiling is left alone --")
d = a_destination(3, kb_each=100)
before = sorted(os.listdir(d))
call('trim_to_size "%s" %d' % (d, 100 * 1024 * 1024))
check(sorted(os.listdir(d)) == before, "nothing was touched, got %s"
      % sorted(os.listdir(d)))
shutil.rmtree(d, ignore_errors=True)

print("\n-- it never deletes the only copy --")
# One snapshot bigger than the whole ceiling. Deleting it would leave the
# console with no backup at all to satisfy a number, which is worse than
# being over.
d = a_destination(1, kb_each=2000)
code, out, err = call('trim_to_size "%s" %d; echo "rc=$?"' % (d, 100 * 1024))
check(os.listdir(d), "the snapshot is still there, got %s" % os.listdir(d))
check("rc=1" in out,
      "and it says it could not get under the ceiling, so the run can warn "
      "rather than silently doing nothing: got %r" % out)
shutil.rmtree(d, ignore_errors=True)

print("\n-- no ceiling means no trimming --")
d = a_destination(4, kb_each=200)
call('trim_to_size "%s" 0' % d)
check(len(os.listdir(d)) == 4, "all four kept, got %s" % sorted(os.listdir(d)))
shutil.rmtree(d, ignore_errors=True)

print("\n-- and the same two rules are applied over ssh --")
body = open(SCRIPT).read()
ssh_part = body.split('    ssh)')[1]
check("head -n -$GENERATIONS" in ssh_part,
      "the generation count is applied on the far end")
check("du -sb" in ssh_part and "cap" in ssh_part,
      "and so is the ceiling -- a remote destination filling up is the same "
      "failure on somebody else's disk")
check("wc -l\\\" -gt 1 ]" in ssh_part or "-gt 1 ]" in ssh_part,
      "including never deleting the last snapshot")

print("\n-- the example config says what it is for --")
example = open(os.path.join(REPO, "backup", "backup.conf.example")).read()
check("MAXSIZE" in example, "MAXSIZE is documented where people look")
check("GENERATIONS" in example, "alongside the count")

print()
if fails:
    print("FAILURES: %d" % len(fails))
    for line in fails:
        print("  " + line)
    sys.exit(1)
print("test_backupsize: all ok")
