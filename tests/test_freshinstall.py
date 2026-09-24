"""What a stranger's first install tells them when part of it did not work.

Found by running install.sh into a throwaway home -- the thing DEVELOPING.md
says that flag is for -- on a machine without RetroArch or python3-evdev, which
is a fair approximation of a fresh one whose package phase did not get sudo.
Two things it said were wrong, and both of them would send somebody chasing
the wrong fault.

It ended with

    FAIL  14 suites failed

and nothing anywhere connecting that to the one missing module behind all
fourteen. A person reading it concludes the code is broken. What is broken is
the install they have just run: without python3-evdev the player picker cannot
start, and the player picker is what starts every game.

And it reported all seven launcher settings missing immediately after writing
all thirty-nine of them correctly, because retrobox-ready reads
~/.config/retroarch/retroarch.cfg and "~" was the invoking user, not the home
being installed into.
"""
import os
import re
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
INSTALL = os.path.join(REPO, "install", "install.sh")
READY = os.path.join(REPO, "bin", "retrobox-ready")

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


source = open(INSTALL).read()

print("a suite that could not run is not a suite that failed")
check("ModuleNotFoundError" in source,
      "the runner recognises a suite that could not be imported at all")
check("skipped=$((skipped+1))" in source,
      "and counts it apart from a failure")
verify = source.split("Checking it works")[1][:2600]
check('bad "$failed suites failed"' in verify,
      "a real failure is still a failure")
check("suites could not run" in verify,
      "and the ones that could not run say so in those words")
check("python3-evdev" in verify and "starts every game" in verify,
      "naming the package and what it costs, rather than leaving fourteen "
      "identical WARN lines to be interpreted")
check("--skip-packages" in verify,
      "and saying which phase installs it")

print("\nthe readiness check is run against the home being installed into")
ready_call = [l for l in source.splitlines() if "retrobox-ready" in l and "HOME=" in l]
check(ready_call,
      "retrobox-ready is invoked with HOME set to the target, the same way "
      "deploy.sh is -- otherwise it grades the wrong machine")

print("\nretrobox-ready knows what the launcher is made of")
ready = open(READY).read()
check("find_spec" in ready, "it looks for the modules rather than assuming them")
for module, package in (("evdev", "python3-evdev"), ("pygame", "python3-pygame")):
    check(package in ready, "%s is named" % package)
check("starts every game" in ready,
      "and evdev's absence is described by what it costs, not by its name")

print("\nand it really reports them")
done = subprocess.run([sys.executable, READY], capture_output=True, text=True,
                      timeout=120)
out = re.sub(r"\x1b\[[0-9;]*m", "", done.stdout)
check("What the launcher itself needs" in out,
      "the section is in the output")
import importlib.util                                       # noqa: E402
for module, package in (("evdev", "python3-evdev"), ("pygame", "python3-pygame"),
                        ("PIL", "python3-pil")):
    there = importlib.util.find_spec(module) is not None
    line = [l for l in out.splitlines() if package in l]
    check(line, "%s has a line" % package)
    if line:
        said_ok = line[0].strip().startswith("ok")
        check(said_ok == there,
              "and it matches reality: %s is %s here and the line says %s"
              % (package, "installed" if there else "absent",
                 "ok" if said_ok else "missing"))

print("\nit reads the home it is told about, not the one it was started from")
tmp = tempfile.mkdtemp(prefix="ready-")
os.makedirs(os.path.join(tmp, ".config", "retroarch"))
with open(os.path.join(tmp, ".config", "retroarch", "retroarch.cfg"), "w") as fh:
    for line in ('log_verbosity = "true"', 'log_to_file = "false"',
                 'network_cmd_enable = "true"', 'savestate_auto_save = "true"',
                 'savestate_auto_load = "true"',
                 'config_save_on_exit = "false"', 'frontend_log_level = "1"'):
        fh.write(line + "\n")
env = dict(os.environ)
env["HOME"] = tmp
done = subprocess.run([sys.executable, READY], capture_output=True, text=True,
                      env=env, timeout=120)
out = re.sub(r"\x1b\[[0-9;]*m", "", done.stdout)
settings = out.split("Settings the launcher depends on")[1].split("==")[0]
check("MISS" not in settings,
      "every launcher setting in that home reads as present, got:\n%s"
      % settings.rstrip())
import shutil                                               # noqa: E402
shutil.rmtree(tmp, ignore_errors=True)

print()
if fails:
    print("FAILED: %d" % len(fails))
    for line in fails:
        print("  " + line)
    sys.exit(1)
print("test_freshinstall: all ok")
