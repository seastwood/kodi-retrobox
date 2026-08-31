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
# And saving is NOT turned off. "Fresh" means do not load what was saved; it
# used to mean do not save either, and a game started fresh and played for
# three hours then wrote nothing down when it closed. What keeps a fresh run
# from overwriting the point somebody stepped past is preserve_auto_state,
# which copies it aside first -- not silence.
check("savestate_auto_save" not in text,
      "saving is left alone, so the session is not lost: %r" % text)
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
rp.run_retroarch = lambda args, override=None, shader=None, repick=None, \
    load_slot=None: seen.update(
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

print("...and an ordinary launch says nothing about save states")
seen.clear()
sys.argv = ["ra_players.py", "--max-players", "1", "-f", "-L", "core.so", "rom.sfc"]
rp.main()
check(seen.get("args") == ["-f", "-L", "core.so", "rom.sfc"], "arguments unchanged")
plain = open(seen["override"]).read() if seen.get("override") else ""
check("savestate_auto" not in plain,
      "an ordinary launch leaves the save state alone: %r" % plain)

# Every launch gets one thing whatever else it gets: RetroArch's own menu is
# on a held Select by default, which is both the gesture that asks for the
# player picker and a way into the whole emulator for anyone holding a pad --
# guests included, whose entire permitted vocabulary is "move a gamepad".
print("every launch shuts the pad's way into the emulator menu")
for label, argv in (
        ("an ordinary launch",
         ["ra_players.py", "--max-players", "1", "-f", "-L", "c.so", "r.sfc"]),
        ("a fresh one",
         ["ra_players.py", "--fresh", "--max-players", "1", "-f", "-L",
          "c.so", "r.sfc"])):
    seen.clear()
    sys.argv = argv
    rp.main()
    text = open(seen["override"]).read() if seen.get("override") else ""
    check('input_menu_toggle_gamepad_combo = "0"' in text,
          "%s cannot open the menu from a pad" % label)
    if seen.get("override"):
        os.unlink(seen["override"])

# The two holds are separately configurable but deliberately the same, so
# neither one is the odd gesture that has to be learned differently.
print("both holds take the same two seconds")
check(rp.hold_fraction(rp.REPICK_SECONDS, rp.REPICK_SECONDS) >= 1.0,
      "a full Select hold asks for the picker")
check(rp.hold_fraction(rp.REPICK_SECONDS / 2, rp.REPICK_SECONDS) < 1.0,
      "half of one does not")
check(rp.hold_fraction(rp.HOLD_SECONDS) >= 1.0,
      "and Start still quits in its own two seconds")
check(rp.hold_fraction(0.1, rp.REPICK_SECONDS) is None,
      "a tap is not a hold at all, whichever button it is")

print(("FAILED: %d" % len(fails)) if fails else "test_fresh: all ok")
sys.exit(1 if fails else 0)
