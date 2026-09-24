"""An achievements account that is still there tomorrow.

Signing in from RetroArch's own menu worked and then did not: the account was
gone by the next game, every time. The reason is config_save_on_exit, which is
off, and has to stay off -- with it on, the per-launch fragment the player
picker hands RetroArch gets written back into retroarch.cfg and becomes
permanent, which is how one "start fresh" disabled automatic saving for every
game afterwards (see test_alwayssave). RetroArch writes cheevos_username and
cheevos_token only on a config save, so with saving off they were never
written at all.

So the token is fetched and stored from outside RetroArch, by the same
one-key-at-a-time merge install.sh uses. What is tested here is that the merge
is a merge -- every other setting in that file is load-bearing -- and that the
password is never one of the things written down.
"""
import ast
import importlib.machinery
import importlib.util
import os
import shutil
import sys
import tempfile
import types

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
MAIN = os.path.join(REPO, "addons", "plugin.program.retroarch", "main.py")

for name in ("xbmc", "xbmcgui", "xbmcplugin", "xbmcaddon", "xbmcvfs"):
    module = types.ModuleType(name)
    module.__getattr__ = lambda attr: (lambda *a, **k: None)
    sys.modules[name] = module
sys.modules["xbmcgui"].Dialog = lambda: types.SimpleNamespace(
    ok=lambda *a, **k: None, yesno=lambda *a, **k: False,
    select=lambda *a, **k: -1, input=lambda *a, **k: "")
sys.argv = ["plugin://x", "1", ""]

loader = importlib.machinery.SourceFileLoader("ra", MAIN)
ra = importlib.util.module_from_spec(
    importlib.util.spec_from_loader("ra", loader))
loader.exec_module(ra)

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


BEFORE = '''# a comment somebody wrote
video_driver = "gl"
cheevos_enable = "true"
cheevos_username = ""
savestate_auto_save = "true"
config_save_on_exit = "false"
'''

tmp = tempfile.mkdtemp(prefix="cheevos-")
cfg = os.path.join(tmp, "retroarch.cfg")
open(cfg, "w").write(BEFORE)
was, ra.RA_CFG = ra.RA_CFG, cfg
try:
    print("signing in writes the account into retroarch.cfg")
    ok = ra.ra_settings_write({"cheevos_username": "seth",
                               "cheevos_token": "AbC123",
                               "cheevos_password": "",
                               "cheevos_enable": "true"})
    check(ok, "the write reported success")
    after = open(cfg).read()
    check('cheevos_username = "seth"' in after, "the name is there")
    check('cheevos_token = "AbC123"' in after,
          "and the token, which is what RetroArch actually signs in with")
    check(ra.ra_setting("cheevos_token") == "AbC123",
          "and it reads back, got %r" % ra.ra_setting("cheevos_token"))

    print("\nand touches nothing else in a file every game depends on")
    check('video_driver = "gl"' in after, "the video driver is untouched")
    check('savestate_auto_save = "true"' in after,
          "automatic saving is untouched -- the whole reason this is done "
          "from out here")
    check('config_save_on_exit = "false"' in after,
          "and config saving is still off, or the next game to exit would "
          "write its launch fragment over all of this")
    check("# a comment somebody wrote" in after, "comments survive")
    check(after.count("cheevos_username") == 1,
          "the key was replaced, not added a second time")
    check(len(after.splitlines()) == len(BEFORE.splitlines()) + 2,
          "two new keys, no more: got %d lines from %d"
          % (len(after.splitlines()), len(BEFORE.splitlines())))

    print("\nthe password is not one of the things written down")
    check('cheevos_password = ""' in after,
          "it is cleared, not stored -- a token is what this machine keeps")
    source = open(MAIN).read()
    tree = ast.parse(source)
    login = next(n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == "cheevos_screen")
    written = set()
    for node in ast.walk(login):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") \
                == "ra_settings_write":
            for arg in node.args:
                if isinstance(arg, ast.Dict):
                    written |= {k.value for k in arg.keys
                                if isinstance(k, ast.Constant)}
    check("cheevos_password" in written and "cheevos_token" in written,
          "the screen writes the token and clears the password, got %s"
          % sorted(written))
    stored = []
    for node in ast.walk(login):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") \
                == "ra_settings_write":
            for arg in node.args:
                if isinstance(arg, ast.Dict):
                    stored += [getattr(v, "id", "") for v in arg.values]
    check("password" not in stored,
          "and the password itself is never among the values written, got %s"
          % sorted(set(v for v in stored if v)))

    print("\nsigning out takes both halves away")
    ra.ra_settings_write({"cheevos_username": "", "cheevos_token": "",
                          "cheevos_password": ""})
    check(ra.ra_setting("cheevos_username") == ""
          and ra.ra_setting("cheevos_token") == "",
          "nothing is left to sign in with")

    print("\na file that is not there yet is made rather than lost")
    ra.RA_CFG = os.path.join(tmp, "new", "retroarch.cfg")
    check(ra.ra_settings_write({"cheevos_username": "bob"}),
          "the write succeeded")
    check(ra.ra_setting("cheevos_username") == "bob", "and reads back")
finally:
    ra.RA_CFG = was
    shutil.rmtree(tmp, ignore_errors=True)

print("\nwhat the site says is what gets shown")
source = open(MAIN).read()
check("HTTPError" in source,
      "a refusal comes back as a 4xx with the reason in the body, so the "
      "body is read -- 'email not verified' is one of those, and reporting "
      "'401 Unauthorized' instead throws away the only useful part")
check("User-Agent" in source,
      "RetroAchievements rejects a request without one, and the error it "
      "gives for that is about something else entirely")
check("login2" in source, "the endpoint RetroArch itself uses")
tree = ast.parse(source)
screen = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "settings_screen")
check("cheevos_screen" in [c.func.id for c in ast.walk(screen)
                           if isinstance(c, ast.Call)
                           and isinstance(c.func, ast.Name)],
      "and there is a way into it from the sofa")

print()
if fails:
    print("FAILED: %d" % len(fails))
    for line in fails:
        print("  " + line)
    sys.exit(1)
print("test_cheevos: all ok")
