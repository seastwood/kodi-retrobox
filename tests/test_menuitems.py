"""Switching home menu rows off, and back on.

Nobody needs every row. A console with no aerial has no use for TV; a house
with one PC has no use for Moonlight. This is the part that decides what the
home menu contains, so two things have to hold.

The first is that a choice sticks to the thing it was made about. The consoles
are numbered games-0, games-1 and so on in playlist order, so adding one
system renumbers every system after it -- and a preference stored against the
number would quietly begin hiding a different console than the one somebody
chose. They are keyed by the system's own name instead, and that is tested by
adding a playlist and checking the choice did not move.

The second is that Settings can never be switched off, because it is the only
way back to this screen. A menu that can hide its own way out is a door locked
from the inside.

The screen itself is a numbered list whose branches are matched by index, so
inserting a row shifts every action below it. That alignment is checked here
by reading the source, because the failure is silent: the wrong row still
does something, just not the thing it is labelled.
"""
import ast
import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.dirname(HERE)

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


def load_menu():
    loader = importlib.machinery.SourceFileLoader(
        "km", os.path.join(ROOT, "bin", "kodi_menu.py"))
    module = importlib.util.module_from_spec(
        importlib.util.spec_from_loader("km", loader))
    loader.exec_module(module)
    return module


def a_console(folder, systems):
    """A playlist directory with a game in each of the named systems."""
    plists = os.path.join(folder, "plists")
    os.makedirs(plists, exist_ok=True)
    for system in systems:
        with open(os.path.join(plists, system + ".lpl"), "w") as fh:
            json.dump({"items": [{"label": "A game"}]}, fh)
    return plists


def menu(module, hidden=(), plists=None, folder=None, shown=()):
    """Build the menu with a given set of rows switched off, and on.

    Two sets because the two defaults both exist: a row is on until it is in
    `hidden`, but a single console is off until it is in `shown` -- the
    consoles live behind the one CONSOLES row now, and are only pinned to the
    home screen one at a time on purpose.
    """
    module.HIDDEN = os.path.join(folder, "hidden.json")
    with open(module.HIDDEN, "w") as fh:
        json.dump({"hidden": list(hidden), "shown": list(shown)}, fh)
    if plists:
        module.PL = plists
    xml, consoles, seen = module.build()
    labels = re.findall(r"<label>([^<]*)</label>", xml)
    ids = re.findall(r"<defaultID>([^<]*)</defaultID>", xml)
    return xml, labels, ids, seen


folder = tempfile.mkdtemp()
km = load_menu()
plists = a_console(folder, ["Nintendo - Game Boy", "Sega - Saturn",
                            "Sony - PlayStation"])

print("everything the menu can hold is offered, whether or not it is showing")
xml, labels, ids, seen = menu(km, plists=plists, folder=folder)
keys = [i["key"] for i in seen]
check(len(seen) > 8, "the catalogue has %d entries" % len(seen))
check("movies" in keys and "settings" in keys, "the fixed rows are in it")
check("console:Sega - Saturn" in keys,
      "and a console is keyed by its own name, not its position")
check(all(i["label"] for i in seen), "every entry has something to show")

print("\nswitching one off takes it out of the menu and nothing else")
before = list(labels)
xml, labels, ids, seen = menu(km, ["movies"], plists, folder)
check("MOVIES" not in labels, "the row is gone")
check(len(labels) == len(before) - 1, "and only that row, got %d of %d"
      % (len(labels), len(before) - 1))
check([i["key"] for i in seen] == keys,
      "but it is still offered, or it could never be switched back on")

print("\nSettings cannot be switched off")
xml, labels, ids, seen = menu(km, ["settings", "movies"], plists, folder)
check("SETTINGS" in labels,
      "asking to hide it does not hide it -- it is the way back to the screen "
      "that would put it back")
check(any(i["key"] == "settings" and i["fixed"] for i in seen),
      "and the screen is told it is fixed, so it can say so rather than "
      "silently ignoring a press")

print("\nevery console is behind one row rather than being a row each")
# Eleven systems put eleven tiles on the home screen and pushed everything
# else off the end of it. They are a list, and a list belongs one level down.
xml, labels, ids, seen = menu(km, plists=plists, folder=folder)
check("CONSOLES" in labels, "there is a row for all of them, got %s" % labels)
check("SATURN" not in labels and "PLAYSTATION" not in labels
      and "GAMEBOY" not in labels,
      "and not one of its own, got %s" % labels)
check(sum(1 for i in seen if i["key"].startswith("console:")) == 3,
      "all three are still offered, or none could ever be pinned back")
check(all(i["default_off"] for i in seen if i["key"].startswith("console:")),
      "and the screen is told they are off by default, so it can say where "
      "they already are rather than calling them hidden")
check(not any(i["default_off"] for i in seen if i["key"] == "consoles"),
      "the row that holds them is an ordinary one, on until switched off")
check("plugin://plugin.program.retroarch/," in xml,
      "the row opens the add-on's own list of consoles")

print("\nand one can still be pinned to the home screen on its own")
xml, labels, ids, seen = menu(km, plists=plists, folder=folder,
                              shown=["console:Sega - Saturn"])
check("SATURN" in labels, "the pinned one is there, got %s" % labels)
check("PLAYSTATION" not in labels and "GAMEBOY" not in labels,
      "and only that one, got %s" % labels)
check("CONSOLES" in labels, "the row holding the rest stays")

print("\na choice about one console stays about that console")
# Saturn is pinned, then a system that sorts before it arrives. The ids are
# numbered games-0, games-1 and so on in playlist order, so a preference
# stored against the number would move to a different console; the name does
# not move.
bigger = a_console(folder, ["Nintendo - Game Boy", "Sega - Saturn",
                            "Sony - PlayStation", "Atari - 2600"])
xml, labels, ids, seen = menu(km, plists=bigger, folder=folder,
                              shown=["console:Sega - Saturn"])
check("SATURN" in labels,
      "the pinned one is still Saturn after the renumbering, got %s" % labels)
check("2600" not in " ".join(labels),
      "and the new console did not inherit the choice")
check(any(i["key"] == "console:Atari - 2600" for i in seen),
      "though it is offered, so it can be pinned too")

print("\nthe rows on the settings screen line up with what they do")
source = open(os.path.join(ROOT, "addons", "plugin.program.retroarch",
                           "main.py")).read()
tree = ast.parse(source)
screen = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "settings_screen"),
              None)
check(screen is not None, "settings_screen is there to read")
if screen:
    rows = next((n for n in ast.walk(screen)
                 if isinstance(n, ast.Assign)
                 and getattr(n.targets[0], "id", "") == "rows"), None)
    labels = [e.value for e in rows.value.elts
              if isinstance(e, ast.Constant)] if rows else []
    # A row built with a format string is one of the toggles at the top; they
    # keep their positions, so counting them is enough.
    total = len(rows.value.elts) if rows else 0
    check(total >= 8, "there are %d rows" % total)

    # What each index actually runs.
    runs = {}
    for node in ast.walk(screen):
        if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) \
                and node.left.id == "pick" and isinstance(node.ops[0], ast.Eq):
            want = node.comparators[0]
            if isinstance(want, ast.Constant):
                parent = next((p for p in ast.walk(screen)
                               if isinstance(p, ast.If) and p.test is node), None)
                # Only this branch's own body. An elif chain nests inside the
                # orelse of the branch above it, so walking the whole If would
                # credit index 2 with everything from index 2 downwards -- and
                # then an off-by-one, which is the failure this is looking
                # for, would still pass.
                called = [c.func.id for stmt in (parent.body if parent else [])
                          for c in ast.walk(stmt)
                          if isinstance(c, ast.Call)
                          and isinstance(c.func, ast.Name)]
                runs[want.value] = called

    said = [e.value for e in rows.value.elts if isinstance(e, ast.Constant)]
    menu_row = next((i for i, e in enumerate(rows.value.elts)
                     if isinstance(e, ast.Constant)
                     and "menu items" in e.value.lower()), None)
    check(menu_row is not None, "the new row is on the screen")
    if menu_row is not None:
        check("menu_items_screen" in runs.get(menu_row, []),
              "and its index runs the screen that switches items on and off, "
              "not the row that used to be there (index %s runs %s)"
              % (menu_row, runs.get(menu_row)))
    # The rows that moved down by one.
    # "Restore from a backup" is no longer a row of its own: it lives inside
    # Backups, next to where the backups are configured, which is where
    # somebody looking for it actually goes.
    for word, function in (("sync", "sync_games_now"),
                           ("stop a game", "stop_stuck_game"),
                           ("update", "update_system"),
                           ("backups", "backups_screen")):
        where = next((i for i, e in enumerate(rows.value.elts)
                      if isinstance(e, ast.Constant)
                      and word in e.value.lower()), None)
        check(where is not None and function in runs.get(where, []),
              "%r still runs %s (index %s runs %s)"
              % (word, function, where, runs.get(where)))
    # Close is the last row, and the early return has to name its index.
    close = len(rows.value.elts) - 1
    check(("(-1, %d)" % close) in source,
          "Close is index %d and the screen returns on it" % close)

    backups = next((n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef)
                    and n.name == "backups_screen"), None)
    check(backups is not None, "and there is a Backups screen to reach")
    if backups is not None:
        called = [c.func.id for c in ast.walk(backups)
                  if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)]
        check("restore_backup" in called,
              "restore is offered there, so moving it did not lose it")
        check("destinations_screen" in called,
              "along with where the backups go")

shutil.rmtree(folder, ignore_errors=True)
print()
if fails:
    print("FAILED: %d" % len(fails))
    for line in fails:
        print("  " + line)
    sys.exit(1)
print("test_menuitems: all ok")
