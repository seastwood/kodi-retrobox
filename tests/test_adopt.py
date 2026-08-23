"""adopt.sh must be safe to run twice.

install.sh adopts on every run, so adopt.sh is not a one-shot. The trap is
that the baked-in home is a *prefix* of the target: /home/retro sits inside
/home/retro2, so a naive substitution rewrites an already-correct path and
turns it into /home/retro22 -- then retro222 on the next install. That is how
a working machine ends up with a sync service pointing at a home that does
not exist.
"""
import os
import shutil
import subprocess
import sys
import tempfile

ADOPT = "/home/retro/retro-console/install/adopt.sh"
fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


def fake_repo(old_home):
    """The smallest tree adopt.sh will act on."""
    root = tempfile.mkdtemp()
    os.makedirs(os.path.join(root, "system"))
    os.makedirs(os.path.join(root, "bin"))
    os.makedirs(os.path.join(root, "install"))
    shutil.copy(ADOPT, os.path.join(root, "install", "adopt.sh"))
    with open(os.path.join(root, "system", "home.txt"), "w") as fh:
        fh.write(old_home + "\n")
    with open(os.path.join(root, "bin", "thing.py"), "w") as fh:
        fh.write('ROMS = "%s/Games/emulation"\n' % old_home)
        fh.write('LOG = "%s"\n' % old_home)          # at end of line
        fh.write('OTHER = "%s-backup/x"\n' % old_home)  # must NOT be rewritten
    return root


def adopt(root, target):
    return subprocess.run([os.path.join(root, "install", "adopt.sh"), target],
                          capture_output=True, text=True, cwd=root)


def body(root):
    with open(os.path.join(root, "bin", "thing.py")) as fh:
        return fh.read()


print("-- adopting to a home that contains the old one --")
repo = fake_repo("/home/retro")
adopt(repo, "/home/retro2")
first = body(repo)
check("/home/retro2/Games/emulation" in first, "the path is adopted")
check("/home/retro22" not in first, "and not doubled on the first run")

adopt(repo, "/home/retro2")
second = body(repo)
check("/home/retro22" not in second, "still not doubled on the second run")
check(first == second, "a second adopt changes nothing at all")

adopt(repo, "/home/retro2")
check(body(repo) == first, "nor a third")

print("\n-- a longer name that merely starts the same is left alone --")
check('"/home/retro-backup/x"' in body(repo) or "/home/retro-backup/x" in body(repo),
      "/home/retro-backup was not rewritten as if it were the home")

print("\n-- the home at the very end of a line is still adopted --")
check('LOG = "/home/retro2"' in body(repo), "a path with nothing after it")

print("\n-- an ordinary, unrelated home --")
repo2 = fake_repo("/home/retro")
adopt(repo2, "/home/bob")
once = body(repo2)
adopt(repo2, "/home/bob")
check("/home/bob/Games/emulation" in once, "adopted")
check(body(repo2) == once, "and idempotent too")

shutil.rmtree(repo, ignore_errors=True)
shutil.rmtree(repo2, ignore_errors=True)
print("\nFAILURES: %d" % len(fails))
sys.exit(1 if fails else 0)
