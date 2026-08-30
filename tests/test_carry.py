"""Bringing a game across a change of players without losing anyone's save.

Adding a player to a game already running means restarting the emulator: which
ports exist is decided when a game starts and never revisited. The game itself
can be carried across, but only through a save state -- and RetroArch will only
write those into numbered slots, choosing whichever one the player was last
using. That is somebody's save, possibly hours of it.

So every slot is copied out of the way first and put back the moment the new
run has read what it needed, and a note on disk means being killed in between
is recoverable too. These are the tests for that promise.
"""
import importlib.machinery
import importlib.util
import json
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


work = tempfile.mkdtemp(prefix="carry-")
rp.STATE_DIR = os.path.join(work, "states")
rp.STATE_BACKUP = os.path.join(work, "carried")
rp.STATE_MANIFEST = os.path.join(work, "carried.json")
rp.LAUNCH_LOG = os.path.join(work, "launch.log")
CORE = os.path.join(rp.STATE_DIR, "Snes9x")
os.makedirs(CORE)
ROM = "/games/snes/Super Test (USA).sfc"
STEM = os.path.join(CORE, "Super Test (USA)")


def put(name, body):
    with open(name, "w") as fh:
        fh.write(body)


print("a slot number is read off the file name, and slot 0 has no number")
check(rp.state_slot_of(STEM + ".state") == 0, "no suffix is slot 0")
check(rp.state_slot_of(STEM + ".state3") == 3, "a suffix is the slot")
check(rp.state_slot_of(STEM + ".state12") == 12, "including two digits")

print("the automatic state is not one of the slots")
put(STEM + ".state", "slot zero")
put(STEM + ".state2", "slot two")
put(STEM + ".state.auto", "where they left off")
found = rp.state_files(ROM)
check(sorted(os.path.basename(f) for f in found) ==
      ["Super Test (USA).state", "Super Test (USA).state2"],
      "only the numbered slots: %r" % [os.path.basename(f) for f in found])

print("carrying the game writes a state and says which slot it went to")
saved = {}


def fake_save(word, reply=False):
    """Stand in for RetroArch, which would write the slot it is sitting on."""
    if word == "SAVE_STATE":
        put(STEM + ".state2", "the middle of the game")
        saved["asked"] = True
        return True
    return True


rp.send_command = fake_save
slot = rp.carry_state(ROM)
check(saved.get("asked"), "RetroArch was asked to save")
check(slot == 2, "the slot that moved is the slot to load: %r" % slot)

print("and the save it wrote over is still safe on disk")
note = json.load(open(rp.STATE_MANIFEST))
check(len(note["files"]) == 2, "both slots were copied aside")
backups = {open(f["backup"]).read() for f in note["files"]}
check(backups == {"slot zero", "slot two"},
      "byte for byte, before the emulator touched them: %r" % backups)

print("putting them back leaves not a trace of the borrowing")
rp.restore_carried()
check(open(STEM + ".state").read() == "slot zero", "slot 0 is untouched")
check(open(STEM + ".state2").read() == "slot two",
      "slot 2 is the player's save again, not the carried one")
check(open(STEM + ".state.auto").read() == "where they left off",
      "the automatic state was never in this at all")
check(not os.path.exists(rp.STATE_MANIFEST), "the note is gone")
check(os.listdir(rp.STATE_BACKUP) == [], "and so are the copies")

print("a slot the game invented is litter, and is cleared away")
put(STEM + ".state", "slot zero")
os.unlink(STEM + ".state2")


def fake_new_slot(word, reply=False):
    if word == "SAVE_STATE":
        put(STEM + ".state5", "somewhere new")
        return True
    return True


rp.send_command = fake_new_slot
check(rp.carry_state(ROM) == 5, "the new file is the one that moved")
rp.restore_carried()
check(not os.path.exists(STEM + ".state5"),
      "a file that was not there before is not left behind")
check(open(STEM + ".state").read() == "slot zero", "and slot 0 is still slot 0")

print("a save that never happens does not leave saves borrowed")
rp.send_command = lambda word, reply=False: True     # says yes, writes nothing
check(rp.carry_state(ROM) is None, "nothing moved, so nothing is carried")
check(not os.path.exists(rp.STATE_MANIFEST),
      "and the borrowing was already undone")
check(open(STEM + ".state").read() == "slot zero", "the save is where it was")

print("a game nothing has ever saved is carried without ceremony")
os.unlink(STEM + ".state")
os.unlink(STEM + ".state.auto")
rp.send_command = fake_new_slot
check(rp.carry_state(ROM) == 5, "still finds the slot it wrote")
rp.restore_carried()
check(rp.state_files(ROM) == [], "and leaves the game as bare as it found it")

print("the request from a browser is a file, read once")
rp.REPICK_FLAG = os.path.join(work, "repick")
check(rp.repick_asked() is False, "no file, no request")
put(rp.REPICK_FLAG, "Dave\n")
check(rp.repick_asked() is True, "the file is the request")
check(rp.repick_asked() is False,
      "and asking twice would put the picker up twice")

shutil.rmtree(work, ignore_errors=True)
print()
if fails:
    print("FAILED: %d" % len(fails))
    sys.exit(1)
print("ok - a game can change players without costing anybody a save")
