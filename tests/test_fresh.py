"""Starting a game from its own title screen instead of where it was left.

Every game here resumes from an automatic save state, which is the right
default and not always what is wanted. "Start fresh" turns that off for one
launch -- and turns auto-*save* off with it, because a fresh run that saved on
exit would write over the state being kept.

In-game saving is a different mechanism and is deliberately untouched.
"""
import importlib.machinery
import importlib.util
import os
import sys

sys.argv = ["x"]
# The repository this test lives in, rather than a path with a clone name in
# it. The README promises the clone can go anywhere and be called anything;
# hard-coding one machine's name for it broke every one of these on a fresh
# install, where it is called something else.
# realpath, not abspath: install.sh runs these through
# ~/.local/share/gametests, which is a symlink to this directory, and abspath
# does not resolve symlinks -- so the repo appeared to be ~/.local/share and
# nothing could be imported.
REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
loader = importlib.machinery.SourceFileLoader(
    "rp", os.path.join(REPO, "bin", "ra_players.py"))
rp = importlib.util.module_from_spec(
    importlib.util.spec_from_loader("rp", loader))
loader.exec_module(rp)

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


print("the override says exactly what it should")
path = rp.fresh_override()
text = open(path).read()
os.unlink(path)
check('savestate_auto_load = "false"' in text, "the automatic load is off")
check('savestate_auto_save = "false"' in text,
      "and so is the automatic save, or the fresh run overwrites the state")
check("savefile" not in text and "sram" not in text.lower(),
      "nothing touches in-game saving, which is a different thing entirely")

print("and it rides along with the player assignments when there are any")
with_players = rp.write_override([], slots=2, fresh=True)
text = open(with_players).read()
os.unlink(with_players)
check("input_player1_joypad_index" in text, "the ports are still parked")
check('savestate_auto_load = "false"' in text, "and the save state is still off")

plain = rp.write_override([], slots=2)
text = open(plain).read()
os.unlink(plain)
check("savestate_auto" not in text,
      "an ordinary launch says nothing about save states, so the config decides")

print("--fresh is consumed here and never reaches RetroArch")
seen = {}
rp.run_retroarch = lambda args, override=None, shader=None: seen.update(
    args=args, override=override, shader=shader) or 0
rp.input_devices = lambda: []          # no pads: the picker stands down
rp.guard_config = lambda: None
rp.restore_stale_state = lambda: None
sys.argv = ["ra_players.py", "--fresh", "--max-players", "1",
            "--shader", "none", "-f", "-L", "core.so", "rom.sfc"]
rp.main()
check(seen.get("args") == ["-f", "-L", "core.so", "rom.sfc"],
      "RetroArch gets only its own arguments: %s" % (seen.get("args"),))
check(seen.get("override") and 'savestate_auto_load = "false"'
      in open(seen["override"]).read(),
      "and an override that turns the save state off")
if seen.get("override"):
    os.unlink(seen["override"])

print("...and an ordinary launch still gets none")
seen.clear()
sys.argv = ["ra_players.py", "--max-players", "1", "-f", "-L", "core.so", "rom.sfc"]
rp.main()
check(seen.get("args") == ["-f", "-L", "core.so", "rom.sfc"], "arguments unchanged")
check(seen.get("override") is None, "and no override at all")

print(("FAILED: %d" % len(fails)) if fails else "test_fresh: all ok")
sys.exit(1 if fails else 0)
