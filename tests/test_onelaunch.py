"""One launcher at a time.

Reported from the sofa: "sometimes when I start a game, another game I did not
select starts at the exact same time, then closes, then my game starts". That
is two of these running at once -- two RetroArch instances fighting over the
display, the loser going down a second later.

What produces the second launch is not the point. A press that registered
twice, CONTINUE going off beside the game that was picked, a launch arriving
while the last game is still closing: any of them, and the answer is the same.
A second launcher supersedes the first, before either has told RetroArch to
start anything, which is what keeps the wrong game off the television rather
than merely taking it away again a moment later.

The handover has to take the emulator with it. The signal handler that stands
a launcher down used to exit without touching the RetroArch it had started,
which would have left a game holding the screen that nothing was watching --
worse than the double launch it was meant to cure.
"""
import ast
import os
import subprocess
import sys
import tempfile
import textwrap
import time

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
PICKER = os.path.join(REPO, "bin", "ra_players.py")

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


source = open(PICKER).read()
tree = ast.parse(source)

print("the lock is taken before anything else happens")
main = next(n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "main")
# By line number: ast.walk yields breadth-first, which is not the order the
# code runs in, and the whole question here is what happens first.
calls = [c.func.id for c in sorted(
    (c for c in ast.walk(main)
     if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)),
    key=lambda c: (c.lineno, c.col_offset))]
check("take_the_screen" in calls, "main asks for the screen")
for after in ("guard_config", "restore_stale_state", "restore_carried"):
    check(after in calls
          and calls.index("take_the_screen") < calls.index(after),
          "and before %s, which is state two launchers would be doing to "
          "each other at the same time" % after)

print("\nstanding down takes the emulator with it")
bail = next((n for n in ast.walk(tree)
             if isinstance(n, ast.FunctionDef) and n.name == "_bail"), None)
check(bail is not None, "the signal handler is there to read")
if bail is not None:
    body = ast.dump(bail)
    check("'terminate'" in body,
          "it asks RetroArch to stop -- SIGTERM, which RetroArch handles, so "
          "the cartridge save and the automatic save state are written")
    check("'kill'" in body, "and insists if it will not")
    check("restore_screen" in body, "and still puts the screen blanking back")

print("\ntwo launchers, one screen")
# The real thing, with the parts that need a controller and a television cut
# out: a process that takes the lock and then sits there, and a second that
# arrives while it is sitting.
tmp = tempfile.mkdtemp(prefix="onelaunch-")
lock = os.path.join(tmp, "launching.lock")
holder_src = textwrap.dedent('''
    import importlib.machinery, importlib.util, os, signal, sys, time
    loader = importlib.machinery.SourceFileLoader("rp", %r)
    rp = importlib.util.module_from_spec(
        importlib.util.spec_from_loader("rp", loader))
    loader.exec_module(rp)
    rp.LAUNCH_LOCK = %r
    rp.PICKER_LOG = os.path.join(%r, "picker.log")
    rp.KODI_SEND = os.path.join(%r, "no-kodi-send")
    stood_down = []
    signal.signal(signal.SIGTERM, lambda *a: (
        open(os.path.join(%r, "stood-down"), "w").write("yes"), os._exit(0)))
    rp.take_the_screen("first game")
    print("holding", flush=True)
    time.sleep(30)
''') % (PICKER, lock, tmp, tmp, tmp)

try:
    import evdev                                            # noqa: F401
    import pygame                                           # noqa: F401
except ImportError as exc:
    print("  SKIP  %s, so the picker cannot be loaded here" % exc)
else:
    holder = subprocess.Popen([sys.executable, "-c", holder_src],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        # pygame greets the community on stdout when it is imported, so the
        # marker is looked for rather than assumed to be the first line.
        ready = ""
        for _ in range(20):
            line = holder.stdout.readline().decode().strip()
            if not line:
                break
            if line == "holding":
                ready = line
                break
        check(ready == "holding", "the first launcher has the screen")

        second_src = holder_src.replace('rp.take_the_screen("first game")',
                                        'got = rp.take_the_screen("second game")\n'
                                        'print("got", got, flush=True)')
        second_src = second_src.replace("time.sleep(30)", "time.sleep(0.2)")
        started = time.time()
        second = subprocess.run([sys.executable, "-c", second_src],
                                capture_output=True, timeout=40)
        took = time.time() - started
        out = second.stdout.decode()
        check("got True" in out,
              "the second one takes it, got %r" % out.strip())
        check(took < 12, "promptly -- %.1fs" % took)
        check(os.path.exists(os.path.join(tmp, "stood-down")),
              "and the first was asked to stand down rather than left running")
        holder.wait(timeout=10)
        check(holder.returncode == 0, "which it did")

        log = open(os.path.join(tmp, "picker.log")).read()
        check("taking over" in log,
              "and the handover is in the log, because the next report of "
              "this will be somebody describing what they saw")
    finally:
        if holder.poll() is None:
            holder.kill()

    print("\nnothing in the way is not a problem")
    alone_src = holder_src.replace('rp.take_the_screen("first game")',
                                   'print("got", rp.take_the_screen("only game"), flush=True)')
    alone_src = alone_src.replace("time.sleep(30)", "")
    alone_src = alone_src.replace('print("holding", flush=True)', "")
    alone = subprocess.run([sys.executable, "-c", alone_src],
                           capture_output=True, timeout=30)
    check("got True" in alone.stdout.decode(),
          "a launcher with the screen to itself just takes it, got %r"
          % alone.stdout.decode().strip())

import shutil                                               # noqa: E402
shutil.rmtree(tmp, ignore_errors=True)

print()
if fails:
    print("FAILED: %d" % len(fails))
    for line in fails:
        print("  " + line)
    sys.exit(1)
print("test_onelaunch: all ok")
