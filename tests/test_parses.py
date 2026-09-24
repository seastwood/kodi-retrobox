"""Every script in this repository is at least valid Python.

The cheapest possible check, written after the dearest possible mistake: a
script was edited, the edit broke its indentation, and it was committed,
pushed and installed on three machines. The local check that should have
caught it grepped the output for particular words rather than looking at the
exit status, so a script that died on import looked exactly like one that had
nothing to report.

A syntax error is the one kind of fault that cannot hide behind test fixtures
or a machine that is set up differently, so it is worth a suite of its own
that needs nothing to run.
"""
import ast
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


def looks_like_python(path):
    if path.endswith(".py"):
        return True
    if "." in os.path.basename(path):
        return False
    try:
        with open(path, "rb") as fh:
            return b"python" in fh.readline()
    except OSError:
        return False


checked = 0
for folder in ("bin", "install", "lib", "addons", "tests"):
    root = os.path.join(REPO, folder)
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in sorted(files):
            path = os.path.join(dirpath, name)
            if not looks_like_python(path):
                continue
            checked += 1
            rel = os.path.relpath(path, REPO)
            try:
                with open(path, encoding="utf-8") as fh:
                    ast.parse(fh.read(), filename=rel)
            except SyntaxError as exc:
                check(False, "%s: %s at line %s" % (rel, exc.msg, exc.lineno))
            except (OSError, UnicodeDecodeError) as exc:
                check(False, "%s: could not read it (%s)" % (rel, exc))

check(checked > 25, "%d python files were parsed" % checked)
if not fails:
    print("  ok   all %d parse" % checked)

print()
if fails:
    print("FAILURES: %d" % len(fails))
    for line in fails:
        print("  " + line)
    sys.exit(1)
print("test_parses: all ok")
