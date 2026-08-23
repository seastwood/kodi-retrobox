#!/usr/bin/env python3
"""Regenerate the Kodi home menu from the RetroArch playlists and reload the skin."""

import glob
import json
import os
import subprocess
from urllib.parse import urlencode
from xml.sax.saxutils import escape

PL = os.path.expanduser("~/.local/share/retroarch/plists")
ICON = os.path.expanduser("~/.kodi/media/consoles")
SKINICON = "special://skin/extras/icons/"
SS = os.path.expanduser("~/.kodi/userdata/addon_data/script.skinshortcuts")
PCGAMES = os.path.expanduser("~/.local/share/pcgames.json")
PLAYERS = os.path.expanduser("~/.local/share/gameplayers.json")
LASTGAME = os.path.expanduser("~/.local/state/retroarch/last-game.json")
RECENT = os.path.expanduser("~/.local/state/retroarch/recent.json")
FAVOURITES = os.path.expanduser("~/.local/share/gamefavourites.json")

SHORT = {
    "Nintendo - Super Nintendo Entertainment System": "SNES",
    "Nintendo - Nintendo 64": "N64",
    "Nintendo - Game Boy Advance": "GBA",
    "Nintendo - Game Boy": "GAMEBOY",
    "Sega - Mega-CD - Sega CD": "SEGA CD",
    "Sega - Mega Drive - Genesis": "GENESIS",
    "Nintendo - Nintendo Entertainment System": "NES",
    "Nintendo - GameCube": "GAMECUBE",
    "Sony - PlayStation": "PLAYSTATION",
}


def short(system):
    return SHORT.get(system, system.split(" - ")[-1].upper())


def sc(default_id, label, action, icon, label2="", props=None):
    out = ["\t<shortcut>\n",
           "\t\t<defaultID>%s</defaultID>\n" % default_id,
           "\t\t<label>%s</label>\n" % escape(label),
           "\t\t<label2>%s</label2>\n" % escape(label2),
           "\t\t<icon>%s</icon>\n" % escape(icon),
           "\t\t<thumb />\n",
           "\t\t<action>%s</action>\n" % escape(action)]
    for k, v in (props or {}).items():
        out.append('\t\t<property name="%s">%s</property>\n' % (k, escape(v)))
    out.append("\t</shortcut>\n")
    return "".join(out)


def build():
    out = ['<?xml version="1.0" encoding="UTF-8"?>\n<shortcuts>\n']
    out.append(sc("movies", "MOVIES",
                  "ActivateWindow(Videos,videodb://movies/titles/,return)",
                  SKINICON + "DefaultMovies.png",
                  props={"widgetPath": "videodb://recentlyaddedmovies/",
                         "widgetName": "RECENTLY ADDED", "widgetTitle": "RECENTLY ADDED",
                         "widgetType": "movies", "widgetArt": "Poster",
                         "widgetStyle": "Panel", "widgetTarget": "videos",
                         "widgetLimit": "20"}))
    out.append(sc("tvshows", "TV",
                  "ActivateWindow(Videos,videodb://tvshows/titles/,return)",
                  SKINICON + "DefaultTVShows.png",
                  props={"widgetPath": "videodb://recentlyaddedepisodes/",
                         "widgetName": "RECENTLY ADDED", "widgetTitle": "RECENTLY ADDED",
                         "widgetType": "episodes", "widgetArt": "Thumb",
                         "widgetStyle": "Panel", "widgetTarget": "videos",
                         "widgetLimit": "20"}))
    out.append(sc("youtube", "YOUTUBE",
                  "ActivateWindow(Videos,plugin://plugin.video.youtube/,return)",
                  SKINICON + "YouTube.png"))

    # Straight back into whatever was last played. The label stays generic
    # on purpose: this menu is only rebuilt when the game list changes, so a
    # game name here would go stale while the action behind it never does.
    if os.path.exists(LASTGAME):
        icon = os.path.join(ICON, "_continue.png")
        if not os.path.exists(icon):
            icon = SKINICON + "DefaultAddonGame.png"
        out.append(sc("continue", "CONTINUE",
                      "RunPlugin(plugin://plugin.program.retroarch/?resume=1)",
                      icon, "LAST PLAYED"))

    # Favourites and recently played, each only once there is something in it
    # -- an empty row on the home screen is worse than no row.
    for store, ident, label, icon_name in (
            (FAVOURITES, "favourites", "FAVOURITES", "_favourites.png"),
            (RECENT, "recent", "RECENT", "_recent.png")):
        try:
            with open(store) as fh:
                games = json.load(fh).get("games", [])
        except (OSError, ValueError):
            games = []
        games = [g for g in games if os.path.exists(g.get("path", ""))]
        if not games:
            continue
        icon = os.path.join(ICON, icon_name)
        if not os.path.exists(icon):
            icon = SKINICON + "DefaultAddonGame.png"
        url = "plugin://plugin.program.retroarch/?" + urlencode({ident: "1"})
        out.append(sc(ident, label, "ActivateWindow(Games,%s,return)" % url,
                      icon, "%d GAMES" % len(games)))

    n = 0
    for pl in sorted(glob.glob(os.path.join(PL, "*.lpl"))):
        system = os.path.basename(pl)[:-4]
        try:
            items = json.load(open(pl)).get("items", [])
        except ValueError:
            continue
        if not items:
            continue
        url = "plugin://plugin.program.retroarch/?" + urlencode({"system": system})
        icon = os.path.join(ICON, system + ".png")
        if not os.path.exists(icon):
            icon = SKINICON + "DefaultAddonGame.png"
        out.append(sc("games-%d" % n, short(system),
                      "ActivateWindow(Games,%s,return)" % url, icon,
                      "%d GAMES" % len(items)))
        n += 1

    # Every game that has a player count, browsable by how many people can
    # play it -- across all the consoles at once, which is the question being
    # asked when several people are deciding what to put on.
    try:
        with open(PLAYERS) as fh:
            counts = json.load(fh).get("counts", {})
    except (OSError, ValueError):
        counts = {}
    known = sum(len(g) for g in counts.values())
    if known:
        icon = os.path.join(ICON, "_multiplayer.png")
        if not os.path.exists(icon):
            icon = SKINICON + "DefaultAddonGame.png"
        url = "plugin://plugin.program.retroarch/?" + urlencode({"multiplayer": "1"})
        out.append(sc("multiplayer", "MULTIPLAYER",
                      "ActivateWindow(Games,%s,return)" % url, icon,
                      "%d GAMES" % known))

    # Native PC games are grouped behind one entry rather than listed individually.
    try:
        with open(PCGAMES) as fh:
            # A Wine game's exec[0] is run-wine-game.sh, which is always
            # there, so its working directory is what says whether the game
            # itself is. Same rule as the add-on's game_installed().
            pcs = [g for g in json.load(fh).get("games", [])
                   if (g.get("exec") or [""])[0]
                   and os.path.exists(os.path.expanduser(g["exec"][0]))
                   and (not g.get("cwd")
                        or os.path.isdir(os.path.expanduser(g["cwd"])))
                   and (not g.get("requires")
                        or os.path.exists(os.path.expanduser(g["requires"])))]
    except (OSError, ValueError):
        pcs = []
    if pcs:
        icon = os.path.join(ICON, "_pcgames.png")
        if not os.path.exists(icon):
            icon = SKINICON + "DefaultAddonGame.png"
        url = "plugin://plugin.program.retroarch/?" + urlencode({"pcgames": "1"})
        out.append(sc("pcgames", "PC GAMES",
                      "ActivateWindow(Games,%s,return)" % url, icon,
                      "%d GAMES" % len(pcs)))

    # Controller mapping editor for the PC games (script.joyshock). Sits next
    # to PC GAMES because that is the only thing it configures.
    out.append(sc("controller", "CONTROLLER",
                  "RunScript(script.joyshock)",
                  SKINICON + "DefaultAddonPeripheral.png",
                  "BUTTON MAPPING"))

    # Bluetooth pairing (script.bluetooth), beside the other two ways a
    # controller can arrive here.
    icon = os.path.join(ICON, "_bluetooth.png")
    if not os.path.exists(icon):
        icon = SKINICON + "DefaultAddonPeripheral.png"
    out.append(sc("bluetooth", "BLUETOOTH",
                  "RunScript(script.bluetooth)", icon, "PAIR A DEVICE"))

    # USB/IP client (script.usbip): attach a controller shared by another box.
    out.append(sc("usbdevices", "USB DEVICES",
                  "RunScript(script.usbip)",
                  SKINICON + "DefaultAddonPeripheral.png",
                  "OVER THE NETWORK"))

    out.append(sc("retroarch", "RETROARCH",
                  "RunPlugin(plugin://plugin.program.retroarch/?open=1)",
                  SKINICON + "DefaultAddonGame.png"))

    # Settings belongs on the home menu, not behind PC GAMES: none of what it
    # controls is about PC games.
    icon = os.path.join(ICON, "_settings.png")
    if not os.path.exists(icon):
        icon = SKINICON + "DefaultAddonProgram.png"
    out.append(sc("settings", "SETTINGS",
                  "RunPlugin(plugin://plugin.program.retroarch/?%s)" % urlencode({"settings": "1"}),
                  icon, "console options"))
    out.append("</shortcuts>\n")
    return "".join(out), n


def main():
    xml, consoles = build()
    dest = os.path.join(SS, "mainmenu.DATA.xml")
    old = open(dest).read() if os.path.exists(dest) else ""
    if old == xml:
        print("menu unchanged (%d consoles)" % consoles)
        return
    os.makedirs(SS, exist_ok=True)
    open(dest, "w").write(xml)
    for h in glob.glob(os.path.join(SS, "*.hash")):
        os.unlink(h)
    print("menu rebuilt: %d consoles" % consoles)
    send = "/usr/bin/kodi-send"
    if os.path.exists(send):
        subprocess.run([send, "--host=127.0.0.1",
                        "--action=RunScript(script.skinshortcuts,type=buildxml&"
                        "mainmenuID=9000&levels=2&options=noGroups)"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        import time
        time.sleep(26)
        subprocess.run([send, "--host=127.0.0.1", "--action=ReloadSkin()"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


if __name__ == "__main__":
    main()
