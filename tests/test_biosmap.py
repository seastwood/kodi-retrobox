"""The machine-readable BIOS list agrees with the prose one, and with reality.

Two lists of the same thing is how they drift, and drift here is silent: a
system missing from bios.tsv is simply never checked, so retrobox-ready says
everything is fine about a game that cannot start. That is worse than not
checking at all, because it is checked and cleared.

So the filenames in bios.tsv have to appear in bios-required.txt, the folders
have to be folders systems.tsv actually knows about, and every folder named
here has to be one install.sh creates.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
BIOS_TSV = os.path.join(REPO, "system", "bios.tsv")
BIOS_TXT = os.path.join(REPO, "system", "bios-required.txt")
SYSTEMS = os.path.join(REPO, "system", "systems.tsv")

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


def rows(path):
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            yield line.rstrip("\n").split("\t")


entries = [r for r in rows(BIOS_TSV) if len(r) >= 3]
folders = {r[0] for r in rows(SYSTEMS) if r}
prose = open(BIOS_TXT, encoding="utf-8").read()

print("the table is shaped the way retrobox-ready reads it")
check(len(entries) > 5, "it lists %d systems" % len(entries))
for folder, rule, files in [(r[0], r[1].strip(), r[2]) for r in entries]:
    check(rule in ("any", "all"),
          "%s says any or all, not %r" % (folder, rule))
    check(bool(files.strip()), "%s names at least one file" % folder)

print("\nevery folder is one this console actually makes")
for row in entries:
    check(row[0] in folders,
          "%s is a folder systems.tsv knows about" % row[0])

print("\nand every filename is one the prose list mentions")
# The prose file is what a person reads when a game will not start, and it is
# the one the launcher's on-screen message points at. A file named here and
# not there is a file nobody can look up.
for row in entries:
    for name in [f.strip() for f in row[2].split(",") if f.strip()]:
        bare = os.path.basename(name)
        check(bare in prose,
              "%s (%s) is described in bios-required.txt" % (bare, row[0]))

print("\nand nothing is listed twice")
seen = [r[0] for r in entries]
check(len(seen) == len(set(seen)), "one row per folder: %d rows, %d folders"
      % (len(seen), len(set(seen))))

print()
if fails:
    print("FAILURES: %d" % len(fails))
    sys.exit(1)
print("test_biosmap: all ok")
