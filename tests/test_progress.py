"""The progress bars, which used to show 0% for the whole job and then vanish.

All five of them -- backup, update, sync, and the two menu rebuilds -- created
a dialog, called a blocking subprocess.run(), and closed it. update() was
never reached once, so the bar sat at nothing for a minute or four. A bar that
cannot move is worse than no bar at all: it reads as a job that has hung, and
the obvious thing to do about a hung console is pull its plug, in the middle
of an install.

So the jobs are followed line by line now, and each one's output is mapped
onto a percentage. Two things have to hold. The bar may not go backwards, and
it may not claim a phase that has not started -- between two marks it creeps
on elapsed time, but never past the next mark. And nothing that draws one of
these dialogs may go back to running its job in one blocking call.
"""
import ast
import os
import sys
import types

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
MAIN = os.path.join(REPO, "addons", "plugin.program.retroarch", "main.py")

for name in ("xbmc", "xbmcgui", "xbmcplugin", "xbmcaddon", "xbmcvfs"):
    module = types.ModuleType(name)
    module.__getattr__ = lambda attr: (lambda *a, **k: None)
    sys.modules[name] = module
sys.modules["xbmc"].sleep = lambda ms: None


class _BG:
    pass


sys.modules["xbmcgui"].DialogProgressBG = _BG
sys.argv = ["plugin://x", "1", ""]

import importlib.machinery                                  # noqa: E402
import importlib.util                                       # noqa: E402

loader = importlib.machinery.SourceFileLoader("ra", MAIN)
ra = importlib.util.module_from_spec(
    importlib.util.spec_from_loader("ra", loader))
loader.exec_module(ra)

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


class Bar(_BG):
    """A DialogProgressBG that writes down what it was told."""

    def __init__(self):
        self.seen = []

    def update(self, percent, heading="", message=""):
        self.seen.append((percent, message))


print("a job's own output drives the bar")
bar = Bar()
script = ("import sys, time\n"
          "for line in ['controller profiles copied in: 3',"
          "'scanned: nintendo', 'art: 1 exact', 'done']:\n"
          "    print(line); sys.stdout.flush(); time.sleep(0.05)\n")
code, out = ra.follow([sys.executable, "-c", script], bar, "Games",
                      ra.SYNC_MARKS, expect=60.0, timeout=30)
percents = [p for p, _m in bar.seen]
check(code == 0, "the job's exit status comes back, got %s" % code)
check("scanned: nintendo" in out, "and everything it said, for the log")
check(percents == sorted(percents),
      "the bar never goes backwards, got %s" % percents)
check(max(percents) == 100, "it reaches the end, got %s" % max(percents))
check(len(set(percents)) > 3,
      "and it actually moved on the way, got %s" % sorted(set(percents)))
captions = [m for _p, m in bar.seen if m]
check("Scanning for new games" in captions,
      "saying what it is doing, got %s" % sorted(set(captions)))

print("\nit never claims a phase that has not started")
bar = Bar()
# A job that says nothing for a while. The creep may fill the gap, but the
# next mark is 4% -- "controller profiles" -- so it may not reach it.
quiet = ("import sys, time\n"
         "time.sleep(0.6)\n"
         "print('done'); sys.stdout.flush()\n")
ra.follow([sys.executable, "-c", quiet], bar, "Games", ra.SYNC_MARKS,
          expect=0.5, timeout=30)
seen = [p for p, _m in bar.seen]
before_end = seen[:seen.index(100)] if 100 in seen else seen
check(before_end and all(p < ra.SYNC_MARKS[0][1] for p in before_end),
      "a silent job creeps but stops below the first thing it has to say, "
      "got %s" % sorted(set(before_end)))
check(len(set(before_end)) > 1,
      "and it does creep, so a long silent phase does not look like a hang, "
      "got %s" % sorted(set(before_end)))

print("\na job that fails is reported as one")
bar = Bar()
code, out = ra.follow([sys.executable, "-c",
                       "import sys; print('boom'); sys.exit(3)"],
                      bar, "Update", ra.UPDATE_MARKS, expect=5.0, timeout=30)
check(code == 3, "its exit status is passed on, got %s" % code)
check("boom" in out, "and its output kept, so it can be shown in full")

print("\nthe marks describe jobs that really print those lines")
sync = open(os.path.join(REPO, "bin", "sync_games.py")).read()
for needle, _pct, _what in ra.SYNC_MARKS:
    check(needle in sync, "the sync prints %r" % needle)
# "Update this console" is update.sh, which hands over to install.sh partway
# through -- so the phases come from both, and both are read.
updating = (open(os.path.join(REPO, "install", "update.sh")).read()
            + open(os.path.join(REPO, "install", "install.sh")).read())
for needle, _pct, _what in ra.UPDATE_MARKS:
    phase = needle[3:] if needle.startswith("== ") else needle
    check(('say "%s' % phase) in updating,
          "an update prints a phase called %r" % phase)
for marks, name in ((ra.SYNC_MARKS, "sync"), (ra.UPDATE_MARKS, "update"),
                    (ra.BACKUP_MARKS, "backup"), (ra.MENU_MARKS, "menu")):
    rising = [p for _n, p, _w in marks]
    check(rising == sorted(rising),
          "the %s marks are in the order the job reaches them, got %s"
          % (name, rising))

print("\nnothing draws a bar and then blocks behind it")
tree = ast.parse(open(MAIN).read())
for node in ast.walk(tree):
    if not isinstance(node, ast.FunctionDef):
        continue
    body = ast.dump(node)
    # Functions that *raise* one of these dialogs. bar_update only asks which
    # kind it has been handed, and has no job of its own to follow.
    if "DialogProgress" not in body or "attr='create'" not in body:
        continue
    blocks = "attr='run'" in body and "subprocess" in body
    check(not blocks,
          "%s does not call subprocess.run behind its own progress bar"
          % node.name)
    check("'follow'" in body,
          "%s follows the job instead" % node.name)

print()
if fails:
    print("FAILED: %d" % len(fails))
    for line in fails:
        print("  " + line)
    sys.exit(1)
print("test_progress: all ok")
