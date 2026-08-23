"""adopt.sh must be safe to run twice.

install.sh adopts on every run, so adopt.sh is not a one-shot. The trap is
that the baked-in home is a *prefix* of the target -- a home ending in "2"
contains the one without it -- so a naive substitution rewrites an already
correct path and doubles the user name, then doubles it again on the next
install. That is how a working machine ends up with a sync service pointing
at a home that does not exist.

Every home in here is built from parts rather than written as a literal. A
literal would be rewritten by the very script under test, which is how this
file broke itself the first time.
"""
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADOPT = os.path.join(REPO, "install", "adopt.sh")

OLD = "/home/" + "retro"          # what the repository is written for
NEW = OLD + "2"                   # a name that *contains* it: the whole point
DOUBLED = OLD + "22"              # what the bug produced

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


def fake_repo(old_home):
    """The smallest tree adopt.sh will act on."""
    root = tempfile.mkdtemp()
    for sub in ("system", "bin", "install"):
        os.makedirs(os.path.join(root, sub))
    shutil.copy(ADOPT, os.path.join(root, "install", "adopt.sh"))
    with open(os.path.join(root, "system", "home.txt"), "w") as fh:
        fh.write(old_home + "\n")
    with open(os.path.join(root, "bin", "thing.py"), "w") as fh:
        fh.write('ROMS = "%s/Games/emulation"\n' % old_home)
        fh.write('LOG = "%s"\n' % old_home)                 # at end of line
        fh.write('OTHER = "%s-backup/x"\n' % old_home)      # must NOT change
    return root


def adopt(root, target):
    return subprocess.run([os.path.join(root, "install", "adopt.sh"), target],
                          capture_output=True, text=True, cwd=root)


def body(root):
    with open(os.path.join(root, "bin", "thing.py")) as fh:
        return fh.read()


print("-- adopting to a home that contains the old one --")
repo = fake_repo(OLD)
adopt(repo, NEW)
first = body(repo)
check("%s/Games/emulation" % NEW in first, "the path is adopted")
check(DOUBLED not in first, "and the user name is not doubled")

adopt(repo, NEW)
second = body(repo)
check(DOUBLED not in second, "still not doubled on the second run")
check(first == second, "a second adopt changes nothing at all")

adopt(repo, NEW)
check(body(repo) == first, "nor a third")

print("\n-- a longer name that merely starts the same is left alone --")
check("%s-backup/x" % OLD in body(repo),
      "%s-backup was not rewritten as if it were the home" % OLD)

print("\n-- the home at the very end of a line is still adopted --")
check('LOG = "%s"' % NEW in body(repo), "a path with nothing after it")

print("\n-- an ordinary, unrelated home --")
repo2 = fake_repo(OLD)
adopt(repo2, "/home/bob")
once = body(repo2)
adopt(repo2, "/home/bob")
check("/home/bob/Games/emulation" in once, "adopted")
check(body(repo2) == once, "and idempotent too")

print("\n-- this test survives being adopted itself --")
source = open(os.path.abspath(__file__)).read()
check(OLD not in source.replace('"/home/" + "retro"', ""),
      "no literal home anywhere in this file for adopt.sh to rewrite")

shutil.rmtree(repo, ignore_errors=True)
shutil.rmtree(repo2, ignore_errors=True)
print("\nFAILURES: %d" % len(fails))
sys.exit(1 if fails else 0)
