# -*- coding: utf-8 -*-
"""JoyShockMapper configuration front end for Kodi.

Everything is driven from Kodi's own dialogs, so it navigates with the game
controller through kodi-peripheral-joystick -- no keyboard is needed on the TV.

The parsing, the button and action tables and the file writing all live in
jsmconfig, which the in-game overlay (jsm-hud) uses as well. Only the Kodi
specific screens are in this file, so the two front ends cannot drift apart in
how they read or write a config.
"""

import os
import shutil
import sys

import xbmc
import xbmcgui

sys.path.insert(0, "/home/retro/.local/lib/jsmconfig")
from jsmconfig import *          # noqa: F401,F403  -- the shared config layer
import jsmconfig


# ---------------------------------------------------------------------------
# Dialog helpers
# ---------------------------------------------------------------------------

def choose(heading, rows, preselect=-1):
    """rows is a list of (label, label2, payload); returns the chosen index."""
    items = [xbmcgui.ListItem(label=r[0], label2=r[1]) for r in rows]
    index = xbmcgui.Dialog().select(heading, items, useDetails=True,
                                    preselect=preselect)
    return None if index < 0 else index


def pick(heading, values, current=None):
    """Plain single-column picker over strings."""
    preselect = values.index(current) if current in values else -1
    index = xbmcgui.Dialog().select(heading, values, preselect=preselect)
    return None if index < 0 else values[index]


def notify(message, error=False):
    icon = (xbmcgui.NOTIFICATION_ERROR if error
            else xbmcgui.NOTIFICATION_INFO)
    xbmcgui.Dialog().notification(TITLE, message, icon, 3000)


def ask_text(heading, default=""):
    text = xbmcgui.Dialog().input(heading, default,
                                  type=xbmcgui.INPUT_ALPHANUM)
    return text.strip() if text else None


# ---------------------------------------------------------------------------
# Pickers for a single value
# ---------------------------------------------------------------------------

def pick_action(heading, current, allow_pair=True):
    """Choose what a button does. Returns "" to clear, a value, or None to
    cancel. Two space-separated values are JSM's tap-and-hold form: the first
    fires on a tap, the second when the button is held past HOLD_PRESS_TIME."""
    while True:
        fixed = [("Clear this binding", "", None),
                 ("Nothing (NONE)", "", None)]
        if allow_pair:
            fixed.append(("Tap and hold: two different actions...",
                          current if current and " " in current else "", None))
        rows = list(fixed)
        rows += [(name, ", ".join(values[:6]) + " ...", None)
                 for name, values in ACTION_GROUPS]
        index = choose(heading, rows)
        if index is None:
            return None
        if index == 0:
            return ""
        if index == 1:
            return "NONE"
        if allow_pair and index == 2:
            pair = pick_tap_hold(heading, current)
            if pair:
                return pair
            continue
        name, values = ACTION_GROUPS[index - len(fixed)]
        value = pick(name, values, current)
        if value is not None:
            return value


def pick_tap_hold(heading, current):
    parts = (current or "").split()
    tap = pick_action("%s  -  on TAP" % heading,
                      parts[0] if parts else None, allow_pair=False)
    if not tap:
        return None
    hold = pick_action("%s  -  on HOLD" % heading,
                       parts[1] if len(parts) > 1 else None, allow_pair=False)
    if not hold:
        return None
    return "%s %s" % (tap, hold)


def pick_number(heading, choices, current):
    values = list(choices)
    if current and current not in values:
        values.insert(0, current)
    rows = [("Clear -- inherit from the base config", "", None)]
    rows += [(v, "current" if v == current else "", None) for v in values]
    rows.append(("Type a value...", "", None))
    index = choose(heading, rows)
    if index is None:
        return None
    if index == 0:
        return ""
    if index == len(rows) - 1:
        text = ask_text(heading, current or "")
        if not text:
            return None
        try:
            float(text)
        except ValueError:
            notify("Not a number: %s" % text, error=True)
            return None
        return text
    return values[index - 1]


def pick_enum(heading, choices, current):
    rows = [("Clear -- inherit from the base config", "", None)]
    rows += [(v, "current" if v == current else "", None) for v in choices]
    index = choose(heading, rows)
    if index is None:
        return None
    return "" if index == 0 else choices[index - 1]


def pick_button(heading, current):
    rows = [("Clear -- inherit from the base config", "", None),
            ("No button (gyro always on)", "NONE", None)]
    rows += [(BUTTON_LABELS[k], k, None) for k in BUTTON_NAMES]
    index = choose(heading, rows)
    if index is None:
        return None
    if index == 0:
        return ""
    if index == 1:
        return "NONE"
    return BUTTON_NAMES[index - 2]


# ---------------------------------------------------------------------------
# The editor
# ---------------------------------------------------------------------------

def value_label(cfg, key, gyro_note=""):
    """What a button row shows on the right. gyro_note flags the button that
    the GYRO_OFF/GYRO_ON setting points at -- without it that button reads as
    "not set" even though holding it is what silences the gyro."""
    value, origin = cfg.effective(key)
    if value is None:
        return gyro_note or "not set"
    if origin is None:
        text = "%s   -   set here" % value
    else:
        text = "%s   -   from %s" % (value, os.path.basename(origin))
    return "%s   +   %s" % (text, gyro_note) if gyro_note else text


def editor_rows(cfg):
    rows = []
    base = cfg.base_spec()
    rows.append(("Base config", os.path.basename(base) if base else "none",
                 ("base", None)))
    rows.append(("Show the whole layout", "", ("show", None)))
    gyro_notes = {}
    off = cfg.effective("GYRO_OFF")[0]
    on = cfg.effective("GYRO_ON")[0]
    if off and off != "NONE":
        gyro_notes[off] = "gyro OFF while held"
    if on and on != "NONE":
        gyro_notes[on] = "gyro ON while held"
    for group, pairs in BUTTON_GROUPS:
        rows.append(("--  %s  --" % group, "", ("nop", None)))
        for key, label in pairs:
            rows.append((label, value_label(cfg, key, gyro_notes.get(key, "")),
                         ("btn", key)))
    for group, settings in SETTING_GROUPS:
        rows.append(("--  %s  --" % group, "", ("nop", None)))
        for key, label, _kind, _choices in settings:
            rows.append((label, value_label(cfg, key), ("set", key)))
    combos = cfg.effective_bindings("+")
    chords = cfg.chord_buttons()
    doubles = cfg.doubles()
    rows.append(("--  COMBOS AND LAYERS  --", "", ("nop", None)))
    rows.append(("Combos", "%d set" % len(combos) if combos else "none",
                 ("combos", None)))
    rows.append(("Hold layers",
                 ", ".join(blabel(b) for b in chords) if chords else "none",
                 ("layers", None)))
    rows.append(("Double presses", "%d set" % len(doubles) if doubles
                 else "none", ("doubles", None)))
    target = cfg.own("-++")
    rows.append(("Desktop layer",
                 os.path.basename(target.strip('"')) if target else "off",
                 ("desktop", None)))
    rows.append(("--  FILE  --", "", ("nop", None)))
    rows.append(("Undo every change made on this screen", "", ("undo", None)))
    return rows


def blabel(button):
    """Friendly name for a button id, falling back to the id itself."""
    return BUTTON_LABELS.get(button, button)


def combo_label(first, op, second):
    joiner = " + " if op == "+" else " then "
    return blabel(first) + joiner + blabel(second)


def pick_combo_key(op, heading):
    """Ask for the two buttons of a combo and return its canonical key."""
    first = pick_button_id("%s: first button" % heading)
    if first is None:
        return None
    second = pick_button_id("%s: second button" % heading)
    if second is None:
        return None
    return first + op + second


def pick_button_id(heading):
    rows = [(BUTTON_LABELS[k], k, None) for k in BUTTON_NAMES]
    index = choose(heading, rows)
    return None if index is None else BUTTON_NAMES[index]


def combos_screen(path):
    """Simultaneous presses: both buttons within SIM_PRESS_WINDOW."""
    index = 0
    while True:
        cfg = Config(path)
        items = cfg.effective_bindings("+")
        rows = [("Add a combo...", "", None)]
        for key, value, inherited in items:
            first, op, second = split_combo(key)
            rows.append((combo_label(first, op, second),
                         "%s   -   from base" % value if inherited else value,
                         None))
        index = choose("Combos - both buttons pressed together", rows, index)
        if index is None:
            return
        if index == 0:
            key = pick_combo_key("+", "New combo")
            if not key:
                continue
            if cfg.own(key) is not None:
                notify("That combo is already set")
                continue
            value = pick_action("New combo: %s" % key, None)
            if not value:
                continue
            cfg.set(key, value)
            cfg.save()
            continue
        key, value, _inherited = items[index - 1]
        first, op, second = split_combo(key)
        new = pick_action(combo_label(first, op, second), value)
        if new is None:
            continue
        if new == "":
            cfg.clear(key)
        else:
            cfg.set(key, new)
        cfg.save()


def doubles_screen(path):
    """A button chorded with itself is JSM's double press."""
    index = 0
    while True:
        cfg = Config(path)
        items = cfg.doubles()
        rows = [("Add a double press...", "", None)]
        for key, value in items:
            rows.append(("Double tap " + blabel(split_combo(key)[0]), value,
                         None))
        index = choose("Double presses", rows, index)
        if index is None:
            return
        if index == 0:
            button = pick_button_id("Double press of which button?")
            if button is None:
                continue
            key = "%s,%s" % (button, button)
            if cfg.own(key) is not None:
                notify("That double press is already set")
                continue
            value = pick_action("Double tap %s" % blabel(button), None)
            if not value:
                continue
            cfg.set(key, value)
            cfg.save()
            continue
        key, value = items[index - 1]
        new = pick_action("Double tap " + blabel(split_combo(key)[0]), value)
        if new is None:
            continue
        if new == "":
            cfg.clear(key)
        else:
            cfg.set(key, new)
        cfg.save()


def layers_screen(path):
    """Hold layers are chords: while the held button is down, the other
    buttons take their chorded bindings instead of their normal ones."""
    index = 0
    while True:
        cfg = Config(path)
        held = cfg.chord_buttons()
        rows = [("Add a hold layer...", "", None)]
        for button in held:
            binds = len([k for k, _v in cfg.all_bindings(",")
                         if split_combo(k)[0] == button])
            sets = len(cfg.chord_settings(button))
            what = ["%d binding%s" % (binds, "" if binds == 1 else "s")]
            if sets:
                what.append("%d setting%s" % (sets, "" if sets == 1 else "s"))
            rows.append(("While %s is held" % blabel(button),
                         ", ".join(what), None))
        index = choose("Hold layers", rows, index)
        if index is None:
            return
        if index == 0:
            button = pick_button_id("Hold which button to enter the layer?")
            if button is None:
                continue
            if button in held:
                notify("%s already has a layer" % blabel(button))
                continue
            layer_editor(path, button)
            continue
        layer_editor(path, held[index - 1])


def layer_editor(path, held):
    """Edit one hold layer. Every key written here is "<held>,<button>"."""
    heading = "While %s is held" % blabel(held)
    index = 0
    while True:
        cfg = Config(path)
        rows = []
        for group, pairs in BUTTON_GROUPS:
            rows.append(("--  %s  --" % group, "", ("nop", None)))
            for key, label in pairs:
                if key == held:
                    continue          # a button cannot chord with itself here
                rows.append((label, layer_value_label(cfg, held, key),
                             ("btn", key)))
        rows.append(("--  SETTINGS WHILE HELD  --", "", ("nop", None)))
        for key, value in cfg.chord_settings(held):
            rows.append((SETTING_LABELS[split_combo(key)[2]], value,
                         ("set", split_combo(key)[2])))
        rows.append(("Change a setting while held...", "", ("addset", None)))
        rows.append(("--  LAYER  --", "", ("nop", None)))
        rows.append(("Delete this whole layer", "", ("delete", None)))

        index = choose(heading, rows, index)
        if index is None:
            return
        kind, key = rows[index][2]
        if kind == "nop":
            continue
        if kind == "delete":
            if xbmcgui.Dialog().yesno(
                    TITLE, "Remove every binding made while %s is held?"
                           % blabel(held)):
                cfg.clear_layer(held)
                cfg.save()
                return
            continue
        if kind == "addset":
            spec = pick_setting_spec("Which setting?")
            if spec is None:
                continue
            key, kind = spec[0], "set"
        chord = "%s,%s" % (held, key)
        if kind == "btn":
            value = pick_action("%s  ->  %s" % (heading, blabel(key)),
                                cfg.own(chord))
        else:
            _key, label, mode, choices = setting_spec(key)
            current = cfg.own(chord)
            if mode == "button":
                value = pick_button(label, current)
            elif mode == "enum":
                value = pick_enum(label, choices, current)
            else:
                value = pick_number(label, choices, current)
        if value is None:
            continue
        if value == "":
            cfg.clear(chord)
        else:
            cfg.set(chord, value)
        cfg.save()


def layer_value_label(cfg, held, key):
    """What a button does inside a hold layer, and what it would do without
    the layer -- a chord only overrides while the chord button is down."""
    own = cfg.own("%s,%s" % (held, key))
    if own is not None:
        return own
    plain, origin = cfg.effective(key)
    if plain is None:
        return "not set"
    return "unchanged: %s" % plain


def pick_setting_spec(heading):
    rows = []
    specs = []
    for group, settings in SETTING_GROUPS:
        for row in settings:
            rows.append((row[1], group, None))
            specs.append(row)
    index = choose(heading, rows)
    return None if index is None else specs[index]


DESKTOP_TEMPLATE = os.path.join(JSM_ROOT, "layers", "_desktop_template.txt")


def desktop_layer_screen(path):
    """The toggle layer: "-" and "+" together load a cursor-driven config over
    this one, and it loads this one back."""
    while True:
        cfg = Config(path)
        target = (cfg.own("-++") or "").strip('"')
        rows = []
        if target:
            rows.append(("Currently", os.path.basename(target), ("nop",)))
            resolved = resolve(target)
            if resolved and os.path.exists(resolved):
                rows.append(("Edit %s" % os.path.basename(target), "",
                             ("edit", resolved)))
            rows.append(("Turn the desktop layer off", "", ("off",)))
        else:
            rows.append(("Turn the desktop layer on", "made from the template",
                         ("on",)))
        index = choose("Desktop layer  ( - and + together )", rows)
        if index is None:
            return
        action = rows[index][2][0]
        if action == "nop":
            continue
        if action == "edit":
            edit_config(rows[index][2][1])
        elif action == "off":
            cfg.clear("-++")
            cfg.save()
            notify("Desktop layer off")
        elif action == "on":
            made = make_desktop_layer(path)
            if made:
                cfg.set("-++", '"%s"' % made)
                cfg.save()
                notify("Desktop layer on")


def make_desktop_layer(path):
    """Copy the template, pointing its exit back at this config. Returns the
    new layer as a JSM_ROOT-relative path, or None."""
    if not os.path.exists(DESKTOP_TEMPLATE):
        notify("No layer template installed", error=True)
        return None
    name = os.path.splitext(os.path.basename(path))[0] + "_desktop.txt"
    layers = os.path.join(JSM_ROOT, "layers")
    if not os.path.isdir(layers):
        os.makedirs(layers)
    dest = os.path.join(layers, name)
    if os.path.exists(dest) and not xbmcgui.Dialog().yesno(
            TITLE, "%s already exists. Replace it with a fresh copy of the "
                   "template?" % name):
        return "layers/" + name
    back = os.path.relpath(path, JSM_ROOT)
    with open(DESKTOP_TEMPLATE) as fh:
        body = fh.read()
    with open(dest, "w") as fh:
        fh.write(body.replace("@RETURN@", back))
    return "layers/" + name


def setting_spec(key):
    for _group, settings in SETTING_GROUPS:
        for row in settings:
            if row[0] == key:
                return row
    return None


def edit_config(path):
    if not os.path.exists(path):
        notify("No such config", error=True)
        return
    undo = path + ".kodi-undo"
    shutil.copy2(path, undo)
    heading = "Edit: %s" % os.path.basename(path)
    index = 0
    while True:
        cfg = Config(path)
        rows = editor_rows(cfg)
        index = choose(heading, rows, index)
        if index is None:
            return
        kind, key = rows[index][2]

        if kind == "nop":
            continue

        if kind == "base":
            options = ["(no base -- this file stands alone)"] + bases()
            chosen = pick("Base config", options, cfg.base_spec())
            if chosen is None:
                continue
            cfg.set_base(None if chosen.startswith("(") else chosen)
            cfg.save()
            continue

        if kind == "show":
            show_layout(path)
            continue

        if kind == "combos":
            combos_screen(path)
            continue

        if kind == "layers":
            layers_screen(path)
            continue

        if kind == "doubles":
            doubles_screen(path)
            continue

        if kind == "desktop":
            desktop_layer_screen(path)
            continue

        if kind == "undo":
            if xbmcgui.Dialog().yesno(
                    TITLE, "Throw away every change made to %s on this "
                           "screen?" % os.path.basename(path)):
                shutil.copy2(undo, path)
                notify("Reverted")
            continue

        if kind == "btn":
            current, _origin = cfg.effective(key)
            value = pick_action("%s  ->" % BUTTON_LABELS[key], current)
        else:
            spec = setting_spec(key)
            _key, label, mode, choices = spec
            current, _origin = cfg.effective(key)
            if mode == "button":
                value = pick_button(label, current)
            elif mode == "enum":
                value = pick_enum(label, choices, current)
            else:
                value = pick_number(label, choices, current)

        if value is None:
            continue
        if value == "":
            cfg.clear(key)
        else:
            cfg.set(key, value)
        cfg.save()


def show_layout(path):
    cfg = Config(path)
    out = [os.path.basename(path), ""]
    base = cfg.base_spec()
    out.append("base: %s" % (base or "none"))
    out.append("")
    off = cfg.effective("GYRO_OFF")[0]
    on = cfg.effective("GYRO_ON")[0]
    for group, pairs in BUTTON_GROUPS:
        out.append(group)
        for key, label in pairs:
            value, origin = cfg.effective(key)
            mark = "" if origin is None or value is None else "  (base)"
            if key == off and off != "NONE":
                mark += "  [gyro off]"
            if key == on and on != "NONE":
                mark += "  [gyro on]"
            out.append("   %-26s %-12s%s" % (label, value or "-", mark))
        out.append("")
    for group, settings in SETTING_GROUPS:
        shown = []
        for key, label, _kind, _choices in settings:
            value, origin = cfg.effective(key)
            if value is None:
                continue
            mark = "" if origin is None else "  (base)"
            shown.append("   %-34s %s%s" % (label, value, mark))
        if shown:
            out.append(group)
            out.extend(shown)
            out.append("")

    combos = cfg.effective_bindings("+")
    if combos:
        out.append("COMBOS  (both together)")
        for key, op_value, inherited in sorted(combos):
            first, op, second = split_combo(key)
            out.append("   %-26s %-12s%s"
                       % (combo_label(first, op, second), op_value,
                          "  (base)" if inherited else ""))
        out.append("")

    doubles = cfg.doubles()
    if doubles:
        out.append("DOUBLE PRESSES")
        for key, value in doubles:
            out.append("   %-26s %s"
                       % ("double tap " + blabel(split_combo(key)[0]), value))
        out.append("")

    for button in cfg.chord_buttons():
        out.append("HOLD LAYER  (while %s is held)" % blabel(button))
        for key, value in cfg.all_bindings(","):
            first, _op, second = split_combo(key)
            if first == button:
                out.append("   %-26s %s" % (blabel(second), value))
        for key, value in cfg.chord_settings(button):
            out.append("   %-26s %s"
                       % (SETTING_LABELS[split_combo(key)[2]], value))
        out.append("")

    target = cfg.own("-++")
    if target:
        out.append("DESKTOP LAYER")
        out.append("   - and + together     %s" % target.strip('"'))
        out.append("")

    xbmcgui.Dialog().textviewer(TITLE, "\n".join(out), usemono=True)


# ---------------------------------------------------------------------------
# Screens
# ---------------------------------------------------------------------------

def games_screen():
    index = 0
    while True:
        data = load_games()
        if data is None:
            notify("Could not read pcgames.json", error=True)
            return
        games = data.get("games", [])
        rows = []
        for game in games:
            config = game.get("jsm")
            rows.append((game.get("name", game.get("id", "?")),
                         os.path.basename(config) if config
                         else "no controller mapping",
                         game))
        if not rows:
            notify("No PC games are declared")
            return
        index = choose("Which game?", rows, index)
        if index is None:
            return
        game_screen(games[index].get("id"))


def game_screen(game_id):
    while True:
        data = load_games()
        game = None
        for candidate in data.get("games", []):
            if candidate.get("id") == game_id:
                game = candidate
                break
        if game is None:
            return
        config = game.get("jsm")
        name = game.get("name", game_id)
        rows = [("Config in use",
                 os.path.basename(config) if config else "none", ("pick",))]
        if config and os.path.exists(config):
            rows.append(("Edit %s" % os.path.basename(config), "", ("edit",)))
            rows.append(("Show the whole layout", "", ("show",)))
        rows.append(("Use a copy of this config, under a new name", "",
                     ("copy",)))
        if config:
            rows.append(("Remove the controller mapping from this game", "",
                         ("clear",)))
        index = choose(name, rows)
        if index is None:
            return
        action = rows[index][2][0]

        if action == "pick":
            options = list_configs()
            labels = [os.path.relpath(p, JSM_ROOT) for p in options]
            chosen = pick("Config for %s" % name, labels,
                          os.path.relpath(config, JSM_ROOT) if config else None)
            if chosen is None:
                continue
            game["jsm"] = os.path.join(JSM_ROOT, chosen)
            save_games(data)
            notify("%s uses %s" % (name, os.path.basename(chosen)))
        elif action == "edit":
            edit_config(config)
        elif action == "show":
            show_layout(config)
        elif action == "copy":
            source = config if config and os.path.exists(config) else None
            new = new_config(copy_of=source, suggest=game_id)
            if new:
                game["jsm"] = new
                save_games(data)
                notify("%s uses %s" % (name, os.path.basename(new)))
        elif action == "clear":
            if xbmcgui.Dialog().yesno(
                    TITLE, "Launch %s with no controller mapping?" % name):
                game.pop("jsm", None)
                save_games(data)
                notify("Mapping removed")


def new_config(copy_of=None, suggest=""):
    """Create a config, either as a copy or fresh on top of a base. Returns
    the new path, or None."""
    name = ask_text("Name for the new config", suggest)
    if not name:
        return None
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    if not name.endswith(".txt"):
        name += ".txt"
    path = os.path.join(GAMES_DIR, name)
    if os.path.exists(path):
        if not xbmcgui.Dialog().yesno(TITLE, "%s already exists. Overwrite it?"
                                      % name):
            return None
    if not os.path.isdir(GAMES_DIR):
        os.makedirs(GAMES_DIR)
    if copy_of:
        shutil.copy2(copy_of, path)
    else:
        options = bases()
        base = pick("Start from which base?", options) if options else None
        cfg = Config(path)
        cfg.lines = ["# %s -- created in Kodi." % name]
        if base:
            cfg.lines.append(base)
        cfg.save()
    return path


def configs_screen():
    index = 0
    while True:
        paths = list_configs()
        rows = [("New config...", "", None)]
        for path in paths:
            cfg = Config(path)
            base = cfg.base_spec()
            rows.append((os.path.basename(path),
                         "%s   -   base: %s" % (
                             os.path.dirname(os.path.relpath(path, JSM_ROOT)),
                             os.path.basename(base) if base else "none"),
                         None))
        index = choose("Configs", rows, index)
        if index is None:
            return
        if index == 0:
            created = new_config()
            if created:
                edit_config(created)
            continue
        edit_config(paths[index - 1])


def help_screen():
    text = """JoyShockMapper on this box

Configs live in
   ~/.config/JoyShockMapper/games/<id>.txt      one per game
   ~/.config/JoyShockMapper/GyroConfigs/        the shared bases

A game's file is a single include of a base plus the lines that differ from
it, so changing a base changes every game that includes it. This screen shows
each binding with the value it actually resolves to and where that value came
from; "Clear" removes the line here and lets the base value show through.

Face buttons are named by POSITION, not by the Nintendo label. JoyShockMapper
turns SDL's button-label translation off, so on a Switch Pro controller:

   N  is the TOP button       marked X
   E  is the RIGHT button     marked A
   S  is the BOTTOM button    marked B
   W  is the LEFT button      marked Y

Gyro is on all the time. "Gyro OFF while this button is held" names the button
that silences it; that button stays free for an ordinary binding as well.

COMBOS are two buttons pressed together within SIM_PRESS_WINDOW. While both
are down the individual bindings are ignored and the combo binding applies.
The house combos are - and D-pad Right to calibrate the gyro, - and D-pad Up
for the Super key, and - and D-pad Left for the on-screen keyboard.

HOLD LAYERS are chords. "While L is held, Y = 3" leaves Y alone the rest of
the time. Any number of buttons can be given a layer, and settings can change
inside one too, so a layer can slow the gyro down as well as remap buttons.

THE DESKTOP LAYER is a whole separate config file. Pressing - and + together
loads it over the current one; pressing + on its own loads the game config
back. There is no layer stack -- whichever file loaded last is what is live.

TAP AND HOLD puts two actions on one button: the first fires on a quick tap,
the second once you hold past HOLD_PRESS_TIME.

JoyShockMapper is not running now. pcgame_launch.py starts it once the game's
window is up and kills it when the game exits, so edits here take effect the
next time you launch the game."""
    xbmcgui.Dialog().textviewer(TITLE, text, usemono=True)


def main():
    if not os.path.isdir(JSM_ROOT):
        notify("No JoyShockMapper config directory", error=True)
        return
    index = 0
    while True:
        rows = [
            ("Games", "Choose which config each PC game uses", None),
            ("Configs", "Edit, copy or create a config", None),
            ("How this works", "Button names, bases, and where gyro lives",
             None),
        ]
        index = choose(TITLE, rows, index)
        if index is None:
            return
        if index == 0:
            games_screen()
        elif index == 1:
            configs_screen()
        else:
            help_screen()


if __name__ == "__main__":
    main()