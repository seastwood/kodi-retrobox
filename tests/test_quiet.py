"""Nothing this console says out loud makes a noise.

Kodi rings the notification chime for every popup, and this machine raises a
lot of them: one as each game starts, over the music the game is beginning to
play; one every ten minutes from the games sync. Silence is available -- the
Python API's notification() takes sound=False -- but only to code running
inside Kodi.

The two programs that are not inside Kodi, the games sync and the player
picker, used kodi-send and Kodi's Notification() builtin, which takes no such
argument and cannot be made quiet. So they go through the add-on instead, by
RunPlugin, and raise the same popup through the API that can be silenced.

This reads the source rather than running any of it: every one of these calls
is a line in a branch that only happens when something has gone wrong, and a
new one added without sound=False would ring for months before anybody
connected the noise to the commit.
"""
import ast
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


ADDONS = [
    os.path.join(REPO, "addons", "plugin.program.retroarch", "main.py"),
    os.path.join(REPO, "addons", "script.joyshock", "main.py"),
    os.path.join(REPO, "addons", "script.joyshock", "service.py"),
]

print("every popup an add-on raises is silent")
total = 0
for path in ADDONS:
    if not os.path.exists(path):
        continue
    tree = ast.parse(open(path).read())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "notification":
            continue
        total += 1
        quiet = any(kw.arg == "sound" and kw.value.value is False
                    for kw in node.keywords if kw.arg)
        # The fifth positional argument is sound, if anybody passes it there.
        if len(node.args) >= 5 and isinstance(node.args[4], ast.Constant):
            quiet = quiet or node.args[4].value is False
        check(quiet, "%s line %d asks for silence"
              % (os.path.basename(os.path.dirname(path)), node.lineno))
check(total >= 10, "there are %d of them to get wrong" % total)

print("\nand so is everything raised from outside Kodi")
for name, path in (("the games sync", os.path.join(REPO, "bin", "sync_games.py")),
                   ("the player picker", os.path.join(REPO, "bin", "ra_players.py")),
                   ("the PC game launcher",
                    os.path.join(REPO, "bin", "pcgame_launch.py"))):
    source = open(path).read()
    check("--action=Notification(" not in source
          and "Notification(%s" not in source,
          "%s no longer uses the builtin that cannot be quietened" % name)
    check("RunPlugin(plugin://plugin.program.retroarch/" in source,
          "%s raises its popups through the add-on instead" % name)
    # Kodi splits a builtin's arguments on commas, so a game called
    # "Sonic & Knuckles, Volume 2" has to survive the trip.
    check("urlencode" in source,
          "%s encodes what it is saying, so a comma in a game's name does "
          "not truncate the message" % name)

print("\nthe add-on has somewhere for them to arrive")
main = open(ADDONS[0]).read()
tree = ast.parse(main)
names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
check("show_notice" in names, "there is a function that raises one")
check('args.get("notify")' in main,
      "and the route that reaches it, or every one of those RunPlugin calls "
      "lands on the console's list of games instead")
notice = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "show_notice")
call = next((c for c in ast.walk(notice)
             if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
             and c.func.attr == "notification"), None)
check(call is not None and any(kw.arg == "sound" and kw.value.value is False
                               for kw in call.keywords if kw.arg),
      "and it is the silent one, which is the entire point of the detour")

print("\nthe launch popup is the one that mattered most")
where = main.index('xbmcgui.Dialog().notification("RetroArch", what')
check("sound=False" in main[where:where + 200],
      "a game starting no longer chimes over its own opening music")

print()
if fails:
    print("FAILED: %d" % len(fails))
    for line in fails:
        print("  " + line)
    sys.exit(1)
print("test_quiet: all ok")
