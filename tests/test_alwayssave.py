"""A game always writes down where you got to.

Two ways that stopped being true, both found the hard way.

"Start fresh" turned automatic *saving* off as well as automatic loading, so a
game started fresh and played for three hours wrote nothing when it closed.
Fresh means do not load what was saved. It cannot mean do not save.

And RetroArch had config_save_on_exit on, so the temporary fragment handed to
each launch was merged into its running configuration and then written back
into retroarch.cfg when it exited. One "start fresh" therefore disabled
automatic saving for every game afterwards. Found in the live config:

    savestate_auto_save = "false"          from one fresh start
    input_player2_joypad_index = "99"      parking, meant for one game
    input_player1_reserved_device = "Fourth Player 1"
"""
import importlib.machinery
import importlib.util
import os
import shutil
import sys
import tempfile

sys.argv = ["x"]
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


print("no launch ever turns automatic saving off")
for name, make in (("a fresh one", rp.fresh_override),
                   ("an ordinary one", rp.guard_override)):
    path = make()
    text = open(path).read()
    os.unlink(path)
    check("savestate_auto_save" not in text,
          "%s says nothing about saving: %r" % (name, text))

pads_cfg = rp.write_override([], 1, True)
text = open(pads_cfg).read()
os.unlink(pads_cfg)
check("savestate_auto_save" not in text,
      "and neither does a fresh launch with players picked")
check('savestate_auto_load = "false"' in text,
      "which still declines to load the old one, because that is what fresh is")

print("\nthe configuration a game is handed cannot become permanent")
tpl = open(os.path.join(REPO, "templates/retroarch-settings.conf")).read()
check('config_save_on_exit = "false"' in tpl,
      "config_save_on_exit is off in the template")
check('savestate_auto_save = "true"' in tpl, "and automatic saving is on")
check('savestate_auto_load = "true"' in tpl, "and automatic loading with it")

print("\nstarting fresh keeps the point it is stepping past")
work = tempfile.mkdtemp(prefix="always-")
rp.STATE_DIR = os.path.join(work, "states")
rp.PICKER_LOG = os.path.join(work, "picker.log")
core = os.path.join(rp.STATE_DIR, "Snes9x")
os.makedirs(core)
ROM = "/games/snes/Long Game (USA).sfc"
auto = os.path.join(core, "Long Game (USA).state.auto")
open(auto, "w").write("three hours in")
open(auto + ".png", "w").write("a picture of it")

rp.preserve_auto_state(ROM)
check(os.path.exists(auto + ".previous"), "the old point is copied aside")
check(open(auto + ".previous").read() == "three hours in",
      "byte for byte: %r" % open(auto + ".previous").read())
check(os.path.exists(auto + ".previous.png"), "and its picture with it")
check(open(auto).read() == "three hours in",
      "and the original is still where the game will find it")

print("\nand the copy is not mistaken for a save state of its own")
check(rp.state_files(ROM) == [],
      "it is not a numbered slot: %r" % rp.state_files(ROM))

print("\na game with nothing saved yet is no trouble")
os.unlink(auto)
os.unlink(auto + ".png")
os.unlink(auto + ".previous")
os.unlink(auto + ".previous.png")
rp.preserve_auto_state(ROM)
check(os.listdir(core) == [], "nothing to keep, nothing kept")
rp.preserve_auto_state("")
check(True, "and no game at all does not raise")

shutil.rmtree(work, ignore_errors=True)
print()
if fails:
    print("FAILURES: %d" % len(fails))
    sys.exit(1)
print("test_alwayssave: all ok")
