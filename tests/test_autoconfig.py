"""Controller profiles reaching RetroArch at all.

`joypad_autoconfig_dir` does not add a directory to the places RetroArch looks
for controller profiles. It *is* the place it looks -- there is no search
path -- so naming a directory of our own hid all 786 profiles the libretro
package ships. A Switch Pro Controller, which has a profile in that set under
exactly the name the kernel reports it by, therefore arrived in a game with
nothing bound and had to be mapped by hand, once per game, with the mapping
lost on exit.

The player picker read both directories all along, which is why the picker
screen printed the right button names while the game that followed it knew
none of them.

So the packaged profiles are copied into the directory RetroArch reads, and
the only rule that matters is that a copy never lands on a profile that is
already there: that one was either saved on this machine or copied by an
earlier run, and in both cases it wins.
"""
import importlib.machinery
import importlib.util
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
loader = importlib.machinery.SourceFileLoader(
    "sg", os.path.join(REPO, "bin", "sync_games.py"))
sg = importlib.util.module_from_spec(
    importlib.util.spec_from_loader("sg", loader))
loader.exec_module(sg)

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


def profile(folder, name, body):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    open(path, "w").write(body)
    return path


tmp = tempfile.mkdtemp(prefix="autoconf-")
packaged = os.path.join(tmp, "packaged")
mine = os.path.join(tmp, "mine")
profile(packaged, "Pro Controller.cfg", 'input_device = "Pro Controller"\n')
profile(packaged, "Core (Plus) Wired Controller.cfg", 'input_b_btn = "2"\n')
profile(packaged, "notes.txt", "not a profile\n")
# Some builds file these by input driver instead of flat.
profile(os.path.join(packaged, "udev"), "8BitDo SN30.cfg", 'input_a_btn = "1"\n')
# One that is already here, with something in it nothing packaged would say.
profile(mine, "Pro Controller.cfg", 'input_device = "mine, hand-mapped"\n')

was = (sg.PACKAGED_AUTOCONFIG, sg.USER_AUTOCONFIG)
sg.PACKAGED_AUTOCONFIG, sg.USER_AUTOCONFIG = packaged, mine
try:
    copied = sg.seed_autoconfig()
    here = sorted(os.listdir(mine))
    check(copied == 2, "the two new profiles were copied, got %d" % copied)
    check("Core (Plus) Wired Controller.cfg" in here,
          "the flat one arrived, got %s" % here)
    check("8BitDo SN30.cfg" in here,
          "and the one filed under its input driver, flattened into the one "
          "directory RetroArch reads, got %s" % here)
    check("notes.txt" not in here, "and nothing that is not a profile")
    check(open(os.path.join(mine, "Pro Controller.cfg")).read().strip()
          == 'input_device = "mine, hand-mapped"',
          "the profile that was already here was left exactly as it was -- "
          "that is the one somebody saved")

    again = sg.seed_autoconfig()
    check(again == 0, "a second pass copies nothing, got %d" % again)

    sg.PACKAGED_AUTOCONFIG = os.path.join(tmp, "nothing-here")
    check(sg.seed_autoconfig() == 0,
          "and a machine with no packaged profiles is not an error")
finally:
    sg.PACKAGED_AUTOCONFIG, sg.USER_AUTOCONFIG = was
    shutil.rmtree(tmp, ignore_errors=True)

print("\nthe settings that make any of it count")
tpl = open(os.path.join(REPO, "templates", "retroarch-settings.conf")).read()
check('input_autodetect_enable = "true"' in tpl,
      "autodetection is on -- without it the profiles are found and then "
      "ignored, which looks identical to their not being there")
check('joypad_autoconfig_dir = "~/.config/retroarch/autoconfig"' in tpl,
      "and the directory is still the writable one, because it is the only "
      "one RetroArch can save a profile of its own into")
check("/usr/share/libretro/autoconfig" in tpl,
      "with the packaged set named in the template, so the next person to "
      "read it learns that pointing this elsewhere hides it")

print("\nand the install does it too, for a machine that never syncs")
inst = open(os.path.join(REPO, "install", "install.sh")).read()
check("/usr/share/libretro/autoconfig" in inst,
      "install.sh knows where the packaged profiles are")
check("[ -e \"$dest\" ] && continue" in inst,
      "and skips any profile already in place rather than copying over it")

sync = open(os.path.join(REPO, "bin", "sync_games.py")).read()
check("seed_autoconfig()" in sync.split("def main():")[1],
      "the sync runs it as well, so a console that was installed before this "
      "existed repairs itself without anybody re-running the install")

print()
if fails:
    print("FAILED: %d" % len(fails))
    for line in fails:
        print("  " + line)
    sys.exit(1)
print("test_autoconfig: all ok")
