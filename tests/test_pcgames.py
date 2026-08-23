"""PC games: which entries are shown, and what ADD GAME names them.

The add-on cannot be imported without Kodi, so xbmc* are stubbed. Nothing here
touches a real game or a real pcgames.json.
"""
import importlib.machinery
import importlib.util
import json
import os
import sys
import tempfile
import types

# ---------------------------------------------------------------- stubs ----
for name in ("xbmc", "xbmcgui", "xbmcplugin", "xbmcaddon", "xbmcvfs"):
    mod = types.ModuleType(name)
    mod.__getattr__ = lambda attr: (lambda *a, **k: None)     # any call is a no-op
    sys.modules.setdefault(name, mod)

# Answers the stubbed dialogs give, and what they were asked.
ANSWERS = {"yesno": True, "input": "RENAMED"}
ASKED = []


class _Dialog(object):
    def yesno(self, title, message, *a, **k):
        ASKED.append(message)
        return ANSWERS["yesno"]

    def input(self, *a, **k):
        return ANSWERS["input"]

    def notification(self, *a, **k):
        pass

    def ok(self, *a, **k):
        pass

    def textviewer(self, *a, **k):
        pass


sys.modules["xbmcgui"].Dialog = _Dialog
sys.modules["xbmcgui"].NOTIFICATION_INFO = 0
sys.modules["xbmcgui"].NOTIFICATION_ERROR = 1
sys.modules["xbmc"].executebuiltin = lambda *a, **k: None
sys.modules["xbmcaddon"].Addon = lambda *a, **k: types.SimpleNamespace(
    getAddonInfo=lambda key: "", getSetting=lambda key: "")

sys.argv = ["plugin://plugin.program.retroarch/", "1", ""]
ldr = importlib.machinery.SourceFileLoader(
    "pcaddon", os.path.expanduser("~/retro-console/addons/plugin.program.retroarch/main.py"))
A = importlib.util.module_from_spec(importlib.util.spec_from_loader("pcaddon", ldr))
ldr.exec_module(A)

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


tmp = tempfile.mkdtemp()
here = os.path.join(tmp, "game")
os.makedirs(here)
exe = os.path.join(here, "run.x86_64")
open(exe, "w").close()
os.chmod(exe, 0o755)
data = os.path.join(here, "pak0.pk3")

print("-- an engine without its data does not appear --")
entry = {"id": "q", "exec": [exe], "cwd": here, "requires": data}
check(A.game_installed(entry) is False,
      "declared but the required data file is missing")
open(data, "w").close()
check(A.game_installed(entry) is True, "and it appears once the data is there")

print("\n-- a Wine game is judged by its folder, not by the runner --")
# exec[0] is run-wine-game.sh, which always exists, so testing it would call
# every Wine game installed whether its folder is there or not.
runner = os.path.join(tmp, "run-wine-game.sh")
open(runner, "w").close()
check(A.game_installed({"id": "w", "exec": [runner, "x", "y"],
                        "cwd": os.path.join(tmp, "not-here")}) is False,
      "missing game folder means not installed")
check(A.game_installed({"id": "w", "exec": [runner, "x", "y"],
                        "cwd": here}) is True,
      "and present when the folder is there")

print("\n-- a native game is judged by its executable --")
check(A.game_installed({"id": "n", "exec": [os.path.join(tmp, "gone")]}) is False,
      "missing executable means not installed")
check(A.game_installed({"id": "n", "exec": [exe]}) is True, "present when it is there")
check(A.game_installed({"id": "n", "exec": []}) is False, "no exec at all is not a game")

print("\n-- ~ in a declaration is expanded --")
check(A.game_installed({"id": "h", "exec": ["~"]}) is True,
      "a ~ path is resolved rather than taken literally")

print("\n-- ADD GAME picks a usable id --")
check(A._slug("QUAKE III", set()) == "quake-iii", "name becomes a slug")
check(A._slug("Rage of Mages 2", set()) == "rage-of-mages-2", "digits and case handled")
check(A._slug("QUAKE III", {"quake-iii"}) == "quake-iii-2",
      "a clash gets a suffix rather than overwriting the other game")
check(A._slug("QUAKE III", {"quake-iii", "quake-iii-2"}) == "quake-iii-3",
      "and keeps counting")
check(A._slug("!!!", set()) == "game", "a name with nothing usable still yields an id")
check(len(A._slug("x" * 80, set())) <= 26, "an absurd name is trimmed")


print("\n-- removing an entry added by mistake --")
# kodi_menu.py is stubbed out: a test must not rebuild the real home menu.
A.subprocess.call = lambda *a, **k: 0
store = os.path.join(tmp, "pcgames.json")
A.PCGAMES = store


def write(*ids):
    import json as _j
    _j.dump({"games": [{"id": i, "name": i.upper(), "exec": [exe]} for i in ids]},
            open(store, "w"))


def ids():
    import json as _j
    return [g["id"] for g in _j.load(open(store))["games"]]


write("keep", "bad")
ANSWERS["yesno"] = False
A.remove_pc_game("bad")
check(ids() == ["keep", "bad"], "answering Keep removes nothing")

ANSWERS["yesno"] = True
A.remove_pc_game("bad")
check(ids() == ["keep"], "answering Remove drops only that entry, got %r" % ids())
check(any("left on disk" in m for m in ASKED),
      "and the prompt promises the game itself is not deleted")

A.remove_pc_game("nosuch")
check(ids() == ["keep"], "removing an id that is not there does nothing")

print("\n-- renaming --")
A.rename_pc_game("keep")
import json as _json
renamed = _json.load(open(store))["games"][0]
check(renamed["name"] == "RENAMED", "the label changes")
check(renamed["id"] == "keep",
      "but the id does not -- the id is what finds the pad mapping")

print("\nFAILURES: %d" % len(fails))
sys.exit(1 if fails else 0)
