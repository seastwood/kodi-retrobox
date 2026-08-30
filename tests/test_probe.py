"""Never ask a running game whether it is ready.

Polling GET_STATUS every quarter of a second from the moment the process
started segfaulted RetroArch within seconds. Measured on this machine, on
Advance Wars under SkyEmu: three clean thirty-second runs with no polling,
against two crashes out of two with it. The probe written to find out whether
the game was ready was killing the game.

So the command channel is write-only, and readiness is read out of the
emulator's own stdout, which this process already has in a file.
"""
import importlib.machinery
import importlib.util
import inspect
import os
import shutil
import sys
import tempfile
import threading
import time

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


print("there is no way to ask a game anything")
src = inspect.getsource(rp.send_command)
check("recvfrom" not in src, "send_command never reads a reply")
check(len(inspect.signature(rp.send_command).parameters) == 1,
      "and takes only the word to send")
body = open(os.path.join(REPO, "bin", "ra_players.py")).read()
sending = [l for l in body.splitlines()
           if "send_command(" in l and "def " not in l]
check(all("GET_STATUS" not in l for l in sending),
      "nothing sends GET_STATUS any more: %r" % sending)

print("readiness comes out of the game's own log")
work = tempfile.mkdtemp(prefix="probe-")
rp.LAUNCH_LOG = os.path.join(work, "launch.log")
open(rp.LAUNCH_LOG, "w").write("[INFO] starting up\n")
check(not rp.wait_for_log(rp.UP_MARKER, time.time() + 1),
      "a log that has not said it yet is not ready")

def write_later():
    time.sleep(0.6)
    with open(rp.LAUNCH_LOG, "a") as fh:
        fh.write("[INFO] [NetCMD] bringing_up_command_interface_at_port 55355.\n")

threading.Thread(target=write_later, daemon=True).start()
check(rp.wait_for_log(rp.UP_MARKER, time.time() + 10),
      "and one that does say it is")

print("a game that has gone is not waited on")
stop = threading.Event()
open(rp.LAUNCH_LOG, "w").write("nothing yet\n")
threading.Thread(target=lambda: (time.sleep(0.4), stop.set()),
                 daemon=True).start()
began = time.time()
check(rp.wait_for_log(rp.UP_MARKER, time.time() + 30, stop) is False,
      "it gives up when told the game is gone")
check(time.time() - began < 5,
      "immediately, rather than sitting out the whole deadline (%.1fs)"
      % (time.time() - began))

print("the load is confirmed from the log too, not assumed")
open(rp.LAUNCH_LOG, "w").write("[INFO] [State] Loading state \"x\", 10 bytes.\n")
check(rp.wait_for_log(rp.LOADED_MARKER, time.time() + 1),
      "a state that loaded says so")
open(rp.LAUNCH_LOG, "w").write("[INFO] no state here\n")
check(not rp.wait_for_log(rp.LOADED_MARKER, time.time() + 1),
      "and one that did not, does not")

print("a thumbnail is not a save state")
rp.STATE_DIR = os.path.join(work, "states")
core = os.path.join(rp.STATE_DIR, "SkyEmu")
os.makedirs(core)
stem = os.path.join(core, "Advance Wars (USA)")
for name in (".state", ".state.png", ".state3", ".state3.png",
             ".state.auto", ".state.auto.png"):
    open(stem + name, "w").write("x")
found = sorted(os.path.basename(f) for f in
               rp.state_files("/games/Advance Wars (USA).gba"))
check(found == ["Advance Wars (USA).state", "Advance Wars (USA).state3"],
      "only the slots, not their pictures or the auto state: %r" % found)
check(rp.state_slot_of(stem + ".state3") == 3, "and slot 3 reads as 3")

shutil.rmtree(work, ignore_errors=True)
print()
if fails:
    print("FAILED: %d" % len(fails))
    sys.exit(1)
print("ok - the game is listened to, never interrogated")
