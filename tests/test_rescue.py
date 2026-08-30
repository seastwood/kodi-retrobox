"""What happens when the game does not come back.

Not hypothetical: Advance Wars on the SkyEmu core runs perfectly on this
machine at seventy-five per cent of a CPU and answers not one network command,
then segfaults. Asking for the player picker mid-game therefore saved the game,
closed it, re-picked, relaunched -- and then waited a silent minute for a reply
that was never coming and deleted the only copy of where the player was.

The saves that were borrowed still go back. The carried game does not get
thrown away with them.
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


work = tempfile.mkdtemp(prefix="rescue-")
rp.STATE_DIR = os.path.join(work, "states")
rp.STATE_BACKUP = os.path.join(work, "carried")
rp.STATE_MANIFEST = os.path.join(work, "carried.json")
rp.PICKER_LOG = os.path.join(work, "picker.log")
CORE = os.path.join(rp.STATE_DIR, "SkyEmu")
os.makedirs(CORE)
ROM = "/games/gba/Advance Wars (USA).gba"
STEM = os.path.join(CORE, "Advance Wars (USA)")


def put(name, body):
    with open(name, "w") as fh:
        fh.write(body)


def save_into(path, body):
    def fake(word, reply=False):
        if word == "SAVE_STATE":
            put(path, body)
        return True
    return fake


print("a game that never answers keeps its place instead of losing it")
put(STEM + ".state", "somebody's own save")
rp.send_command = save_into(STEM + ".state", "the middle of a war")
slot = rp.carry_state(ROM)
check(slot == 0, "carried into slot 0: %r" % slot)
note = json.load(open(rp.STATE_MANIFEST))
check(note.get("carried") == STEM + ".state",
      "and wrote down which file that was: %r" % note.get("carried"))

rp.restore_carried(rescue=True)
check(open(STEM + ".state").read() == "somebody's own save",
      "the player's own slot is back, untouched")
check(os.path.exists(STEM + ".state.auto"),
      "and the carried game was kept")
check(open(STEM + ".state.auto").read() == "the middle of a war",
      "as the automatic state, which an ordinary launch loads")
check(not os.path.exists(rp.STATE_MANIFEST), "the note is cleared")

print("a game that does come back leaves nothing lying about")
os.unlink(STEM + ".state.auto")
put(STEM + ".state", "somebody's own save")
rp.send_command = save_into(STEM + ".state", "carried again")
rp.carry_state(ROM)
rp.restore_carried(rescue=False)
check(open(STEM + ".state").read() == "somebody's own save",
      "the slot is theirs again")
check(not os.path.exists(STEM + ".state.auto"),
      "and no automatic state was invented behind their back")

print("a crash is reported however long the game had been running")
log = os.path.join(work, "launch.log")
put(log, "[INFO] nothing wrong here\n")
check(rp.diagnose(log, -11, 300) is not None,
      "a segfault after five minutes is not 'they finished playing'")
check("signal 11" in (rp.diagnose(log, -11, 300) or ""),
      "and says which: %r" % rp.diagnose(log, -11, 300))
check(rp.diagnose(log, 0, 300) is None,
      "an ordinary quit after five minutes is still silence")
check(rp.diagnose(log, 1, 300) is None, "and so is code 1")

print("but a crash on the way out of a quit we asked for is not news")
# SkyEmu segfaults every time it closes, on every GBA game here. Reporting
# that would mean a scare message after every ordinary quit.
check(rp.diagnose(log, -11, 300, asked=True) is None,
      "dying during a shutdown we asked for stays quiet")
check(rp.diagnose(log, -11, 300, asked=False) is not None,
      "dying when nobody asked does not")
check(rp.QUIT_ASKED[0] == 0.0, "and nothing has asked yet in this test")

print("the picker writes where RetroArch cannot overwrite it")
check(rp.PICKER_LOG != rp.LAUNCH_LOG,
      "its own log, not the one the emulator streams into")
rp.log_line("a note worth keeping")
check("a note worth keeping" in open(rp.PICKER_LOG).read(),
      "and the note is there")

shutil.rmtree(work, ignore_errors=True)
print()
if fails:
    print("FAILED: %d" % len(fails))
    sys.exit(1)
print("ok - a game that will not come back is kept, not deleted")
