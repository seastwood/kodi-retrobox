"""The one setting that decides whether a Switch Pro Controller pairs at all.

BlueZ's input service will not accept a HID connection from a device that is
not bonded, and a Pro Controller connects unbonded -- so the pad pairs, drops
a second later, and nothing in the log says why. install/switchpro.sh turns
that limit off in /etc/bluetooth/input.conf.

The file it edits belongs to bluez, not to us, and can be in four states by
the time we see it: the setting commented out (how it ships), set to true, set
to false already (a second install), or missing entirely. All four have to end
as exactly one uncommented ClassicBondedOnly=false inside [General] -- one,
because a second copy of the key would be read after the first and could put
the limit back.

--file is what makes this testable: it rewrites the file it is given and does
nothing else -- no adapter, no service, no root -- so none of this touches the
machine it runs on.
"""
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
SCRIPT = os.path.join(REPO, "install", "switchpro.sh")

# How bluez ships it, trimmed to the shape that matters: the comment block
# above the setting mentions the key by name in prose, which is exactly the
# kind of line a careless match would edit.
STOCK = """# Configuration file for the input service

[General]

# Enable HID protocol handling in userspace input profile
#UserspaceHID=true

# Limit HID connections to bonded devices
# Defaults to true for security.
#ClassicBondedOnly=true

#LEAutoSecurity=true
"""

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


def run(text, *args):
    """Rewrite text with the script and hand back what it said and wrote."""
    fd, path = tempfile.mkstemp(prefix="input.conf.")
    with os.fdopen(fd, "w") as fh:
        fh.write(text)
    proc = subprocess.run([SCRIPT, "--file", path] + list(args),
                          capture_output=True, text=True)
    with open(path) as fh:
        after = fh.read()
    os.unlink(path)
    return proc, after


def settings(text):
    """Every line that actually sets the key -- commented ones do not count."""
    return [ln.strip() for ln in text.splitlines()
            if ln.strip().lower().startswith("classicbondedonly")]


print("the setting bluez ships commented out")
proc, after = run(STOCK)
check(proc.returncode == 0, "the script succeeds")
check(settings(after) == ["ClassicBondedOnly=false"],
      "one uncommented false and nothing else: %s" % settings(after))
check("#ClassicBondedOnly=true" not in after, "the commented original is gone")
check("# Limit HID connections to bonded devices" in after,
      "the prose around it is left alone")
check("#UserspaceHID=true" in after and "#LEAutoSecurity=true" in after,
      "and so is every other setting in the file")
check(after.index("ClassicBondedOnly=false") > after.index("[General]"),
      "it lands inside [General]")

print("...and a second install changes nothing")
proc, again = run(after)
check(proc.returncode == 0 and again == after, "the file is byte for byte the same")
check("already" in proc.stdout, "and it says so rather than claiming a fix: %r"
      % proc.stdout.strip())

print("the setting left at true, by hand or by an older bluez")
proc, after = run(STOCK.replace("#ClassicBondedOnly=true", "ClassicBondedOnly=true"))
check(settings(after) == ["ClassicBondedOnly=false"],
      "is turned over, not duplicated: %s" % settings(after))

print("both a commented and an uncommented copy")
both = STOCK.replace("#ClassicBondedOnly=true",
                     "#ClassicBondedOnly=true\nClassicBondedOnly=true")
proc, after = run(both)
check(settings(after) == ["ClassicBondedOnly=false"],
      "leave one line, because the last one read would win: %s" % settings(after))

print("no such setting anywhere in the file")
proc, after = run("# Configuration file for the input service\n\n[General]\n"
                  "#IdleTimeout=30\n")
check(settings(after) == ["ClassicBondedOnly=false"], "it is added")
check(after.index("ClassicBondedOnly=false") > after.index("[General]"),
      "under [General], where the input service reads it")
check("#IdleTimeout=30" in after, "beside what was already there")

print("and no [General] section either")
proc, after = run("# nothing here at all\n")
check(settings(after) == ["ClassicBondedOnly=false"], "the setting is added")
check("[General]" in after and
      after.index("[General]") < after.index("ClassicBondedOnly=false"),
      "with a section for it to live in")
check("# nothing here at all" in after, "and the file is kept")

print("a copy under some other section is not ours")
other = STOCK + "\n[SomethingElse]\nClassicBondedOnly=true\n"
proc, after = run(other)
check("[SomethingElse]\nClassicBondedOnly=true" in after,
      "left exactly as it was")
check(after.count("ClassicBondedOnly=false") == 1, "and ours is still the one")

print("--dry-run writes nothing")
proc, after = run(STOCK, "--dry-run")
check(after == STOCK, "the file is untouched")
check("would" in proc.stdout, "and it says what it would do: %r"
      % proc.stdout.strip())

print(("FAILED: %d" % len(fails)) if fails else "test_switchpro: all ok")
sys.exit(1 if fails else 0)
