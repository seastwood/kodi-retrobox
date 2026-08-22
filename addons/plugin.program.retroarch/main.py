import glob
import json
import os
import subprocess
import sys
from urllib.parse import parse_qsl, urlencode

import xbmc
import xbmcgui
import xbmcplugin

BASE = sys.argv[0]
HANDLE = int(sys.argv[1])

PLAYLIST_DIR = "/home/retro/.local/share/retroarch/plists"
THUMB_DIR = "/home/retro/.local/share/retroarch/thumbnails"
# Player-assignment screen; it execs RetroArch once pads are claimed.
PICKER = "/home/retro/.local/bin/ra_players.py"
# Native PC games (not RetroArch content) are described here.
PCGAMES = "/home/retro/.local/share/pcgames.json"
# Shown when a PC game has no artwork of its own.
PC_FALLBACK_ART = "/home/retro/.kodi/media/consoles/_pcgames.png"
# Wrapper that handles window focus and returning to Kodi afterwards.
PC_LAUNCHER = "/home/retro/.local/bin/pcgame_launch.py"
# How many players each game takes, written by sync_games.py from the libretro
# databases plus the hand-kept overrides beside it.
PLAYERS = "/home/retro/.local/share/gameplayers.json"
# Hand-kept counts. This is the file the Kodi editor writes and the one
# sync_games.py treats as beating the database.
PLAYERS_MANUAL = "/home/retro/.local/share/gameplayers.manual.json"
SYSTEM_DIR = "/home/retro/.local/share/retroarch/system"
# The last game started, so CONTINUE on the home screen has something to open.
LAST_GAME = "/home/retro/.local/state/retroarch/last-game.json"
# The last dozen games played, newest first, and the ones marked as keepers.
RECENT = "/home/retro/.local/state/retroarch/recent.json"
RECENT_MAX = 12
FAVOURITES = "/home/retro/.local/share/gamefavourites.json"
SHADER_DIR = "/home/retro/.local/share/retroarch/shaders"
# A CRT filter on a television console looks right; on a handheld it is simply
# wrong -- a Game Boy screen never had scanlines. Anything not listed gets the
# default, and "" means no filter at all.
CRT = os.path.join(SHADER_DIR, "crt", "crt-easymode.glslp")
SHADERS = {
    "Nintendo - Game Boy": "",
    "Nintendo - Game Boy Advance": "",
}
# Systems that cannot run a single game without a BIOS. The core's own .info
# marks all of its firmware "optional", which here does not mean the games run
# without it -- so that field cannot be used to work this out.
REQUIRED_BIOS = {
    "Sega - Mega-CD - Sega CD": ["bios_CD_U.bin", "bios_CD_E.bin", "bios_CD_J.bin"],
}
# Anything above four shares one bucket: the exact number stops mattering once
# it is more people than a sofa holds.
BUCKETS = [("1", "1 PLAYER"), ("2", "2 PLAYERS"), ("3", "3 PLAYERS"),
           ("4", "4 PLAYERS"), ("5+", "5+ PLAYERS")]

# RetroArch system names are long; these read better on a TV.
SHORT_NAMES = {
    "Nintendo - Super Nintendo Entertainment System": "Super Nintendo",
    "Nintendo - Nintendo 64": "Nintendo 64",
    "Nintendo - Game Boy Advance": "Game Boy Advance",
    "Nintendo - Game Boy": "Game Boy",
    "Sega - Mega-CD - Sega CD": "Sega CD",
    "Sega - Mega Drive - Genesis": "Genesis",
    "Nintendo - Nintendo Entertainment System": "NES",
}


def url(**kwargs):
    return BASE + "?" + urlencode(kwargs)


def short_name(system):
    if system in SHORT_NAMES:
        return SHORT_NAMES[system]
    for prefix in ("Nintendo - ", "Sega - ", "Sony - ", "Atari - "):
        if system.startswith(prefix):
            return system[len(prefix):]
    return system


def sanitize(name):
    """The thumbnail server's own file naming, which sync_games.py follows.

    Without this a label containing one of these characters -- "Sonic &
    Knuckles" -- looks for art under a name nothing on disk ever uses, and the
    game shows no box art at all despite the file sitting right there.
    """
    for ch in '&*/:`<>?\\|"':
        name = name.replace(ch, "_")
    return name


def art_for(system, label):
    art = {}
    for kind, keys in (("Named_Boxarts", ("thumb", "poster", "icon")),
                       ("Named_Snaps", ("fanart",)),
                       ("Named_Titles", ("banner",))):
        for name in (sanitize(label), label):
            path = os.path.join(THUMB_DIR, system, kind, name + ".png")
            if os.path.exists(path):
                for key in keys:
                    art[key] = path
                break
    return art


def read_games(path):
    try:
        with open(path) as handle:
            return json.load(handle).get("games", [])
    except (OSError, ValueError):
        return []


def stored(system, entry, players=""):
    """A game recorded in the shape the playlists use, so the same row builder
    draws it wherever it is listed."""
    return {"system": system, "label": entry.get("label", ""),
            "path": entry.get("path", ""),
            "core_path": entry.get("core_path", ""),
            "maxplayers": str(players or "")}


def is_favourite(system, label):
    return any(g["system"] == system and g["label"] == label
               for g in read_games(FAVOURITES))


def player_counts():
    try:
        with open(PLAYERS) as handle:
            return json.load(handle).get("counts", {})
    except (OSError, ValueError):
        return {}


def bucket_of(users):
    return "5+" if users >= 5 else str(users)


def players_label(users):
    return "1 PLAYER" if users == 1 else "%d PLAYERS" % users


def game_item(system, entry, users, second_line):
    """One game row, built the same way wherever it is listed."""
    label = entry.get("label", "")
    # The count goes in the label as well as label2 because label2 is only
    # drawn in some of the skin's views, and this is worth seeing in all of
    # them. Suffix, not prefix, so sorting by name is unaffected.
    shown = "%s  [%dP]" % (label, users) if users else label
    item = xbmcgui.ListItem(label=shown)
    item.setLabel2(second_line)
    info = {"title": shown, "platform": short_name(system)}
    if users:
        info["overview"] = "%s  -  %s" % (players_label(users), short_name(system))
    item.setInfo("game", info)
    item.setArt(art_for(system, label))
    item.setProperty("IsPlayable", "false")
    starred = is_favourite(system, label)
    item.addContextMenuItems([
        ("Remove from favourites" if starred else "Add to favourites",
         "RunPlugin(%s)" % url(fav="1", system=system, label=label)),
        ("Set player count",
         "RunPlugin(%s)" % url(setplayers="1", system=system, label=label)),
    ])
    return item


def playlists():
    for path in sorted(glob.glob(os.path.join(PLAYLIST_DIR, "*.lpl"))):
        try:
            with open(path) as handle:
                yield os.path.basename(path)[:-4], json.load(handle)
        except (ValueError, OSError):
            continue


def list_systems():
    xbmcplugin.setPluginCategory(HANDLE, "Consoles")
    xbmcplugin.setContent(HANDLE, "games")
    for system, data in playlists():
        items = data.get("items", [])
        if not items:
            continue
        item = xbmcgui.ListItem(label=short_name(system))
        item.setInfo("game", {"title": short_name(system),
                              "platform": short_name(system)})
        # Use the first game's box art so each console tile has an image.
        cover = art_for(system, items[0].get("label", ""))
        if cover:
            item.setArt({"icon": cover.get("thumb", ""),
                         "thumb": cover.get("thumb", "")})
        item.setLabel2("%d games" % len(items))
        xbmcplugin.addDirectoryItem(HANDLE, url(system=system), item, True)
    xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_LABEL)
    xbmcplugin.endOfDirectory(HANDLE)


def list_games(system):
    xbmcplugin.setPluginCategory(HANDLE, short_name(system))
    xbmcplugin.setContent(HANDLE, "games")
    counts = player_counts().get(system, {})
    for name, data in playlists():
        if name != system:
            continue
        for entry in data.get("items", []):
            label = entry.get("label", "")
            users = counts.get(label)
            item = game_item(system, entry, users,
                             players_label(users) if users else "")
            target = url(play="1", system=system, maxplayers=str(users or ""),
                         core=entry.get("core_path", ""),
                         rom=entry.get("path", ""))
            xbmcplugin.addDirectoryItem(HANDLE, target, item, False)
        break
    xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_LABEL)
    xbmcplugin.endOfDirectory(HANDLE)


def list_buckets():
    """One row per player count, each opening every game that takes it."""
    xbmcplugin.setPluginCategory(HANDLE, "Multiplayer")
    xbmcplugin.setContent(HANDLE, "games")
    counts = player_counts()
    tally = {}
    for system, games in counts.items():
        for users in games.values():
            tally[bucket_of(users)] = tally.get(bucket_of(users), 0) + 1
    for key, title in BUCKETS:
        if not tally.get(key):
            continue                      # no games take this many
        item = xbmcgui.ListItem(label=title)
        item.setInfo("game", {"title": title})
        item.setLabel2("%d games" % tally[key])
        art = os.path.join(os.path.dirname(PC_FALLBACK_ART), "_multiplayer.png")
        if os.path.exists(art):
            item.setArt({"icon": art, "thumb": art, "poster": art})
        xbmcplugin.addDirectoryItem(HANDLE, url(players=key), item, True)
    xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_UNSORTED)
    xbmcplugin.endOfDirectory(HANDLE)


def list_by_players(key):
    """Every game across every console that takes this many players."""
    title = dict(BUCKETS).get(key, key)
    xbmcplugin.setPluginCategory(HANDLE, title)
    xbmcplugin.setContent(HANDLE, "games")
    counts = player_counts()
    for system, data in playlists():
        games = counts.get(system, {})
        for entry in data.get("items", []):
            label = entry.get("label", "")
            users = games.get(label)
            if not users or bucket_of(users) != key:
                continue
            # The console matters here in a way it does not inside one
            # console's own list, so it takes the second line.
            item = game_item(system, entry, users, short_name(system))
            target = url(play="1", system=system, maxplayers=str(users or ""),
                         core=entry.get("core_path", ""),
                         rom=entry.get("path", ""))
            xbmcplugin.addDirectoryItem(HANDLE, target, item, False)
    xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_LABEL)
    xbmcplugin.endOfDirectory(HANDLE)


def write_json(path, data):
    """Write via a temporary file: the sync timer reads these too, and a
    half-written file would look like no counts at all."""
    tmp = path + ".tmp"
    with open(tmp, "w") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
    os.replace(tmp, path)


def set_players(system, label):
    """Ask how many players a game takes, and remember the answer.

    The libretro databases are the source for these numbers and some of them
    are wrong -- Micro Machines V3 is listed as 4 when it plays 8 -- so the
    answer goes into the hand-kept file, which sync_games.py always prefers
    over the database and never overwrites.
    """
    counts = player_counts()
    current = counts.get(system, {}).get(label)
    choices = [players_label(n) for n in range(1, 9)]
    choices.append("Use the database's own count")
    picked = xbmcgui.Dialog().select(
        "Players - %s" % label, choices,
        preselect=(current - 1) if current and current <= 8 else -1)
    if picked < 0:
        return                            # cancelled
    try:
        with open(PLAYERS_MANUAL) as handle:
            manual = json.load(handle)
    except (OSError, ValueError):
        manual = {}
    games = manual.setdefault(system, {})
    if picked == len(choices) - 1:
        games.pop(label, None)
        if not games:
            manual.pop(system, None)
        # Handing a game back to the database means this count has to be
        # worked out again, which only sync_games.py can do; drop it here so
        # nothing stale is shown until it does.
        counts.get(system, {}).pop(label, None)
    else:
        games[label] = picked + 1
        # Apply it to the generated file too, so the change shows immediately
        # rather than at the next ten-minute sync.
        counts.setdefault(system, {})[label] = picked + 1

    # Generated file first, hand-kept file last. sync_games.py regenerates
    # only when the hand-kept file is newer than the generated one, so writing
    # them the other way round makes an edit look already applied and a reset
    # would never be worked out again.
    write_json(PLAYERS, {"counts": counts})
    write_json(PLAYERS_MANUAL, manual)
    xbmc.executebuiltin("Container.Refresh")


def preflight(core, rom, system):
    """Why this game cannot start, checked before anything is launched.

    Every one of these used to present as the screen going black and coming
    straight back with nothing said -- the plugin sends RetroArch's output to
    /dev/null, so there was no other clue anywhere.
    """
    if not (core and rom):
        return "No core or ROM was given"
    if not os.path.exists(rom):
        return "The game file is missing: %s" % os.path.basename(rom)
    if not os.path.exists(core):
        return "The emulator core is missing: %s" % os.path.basename(core)
    wanted = REQUIRED_BIOS.get(system)
    if wanted and not any(os.path.exists(os.path.join(SYSTEM_DIR, b))
                          for b in wanted):
        return "%s needs a BIOS: %s" % (short_name(system), wanted[0])
    return None


def launch(core, rom, system="", players=""):
    problem = preflight(core, rom, system)
    if problem:
        xbmc.log("plugin.program.retroarch: refusing to launch: %s" % problem,
                 xbmc.LOGERROR)
        xbmcgui.Dialog().ok("Cannot start this game", problem)
        return
    try:
        os.makedirs(os.path.dirname(LAST_GAME), exist_ok=True)
        write_json(LAST_GAME, {"core": core, "rom": rom,
                               "system": system, "maxplayers": players})
        label = ""
        for name, data in playlists():
            if name != system:
                continue
            for entry in data.get("items", []):
                if entry.get("path") == rom:
                    label = entry.get("label", "")
                    break
        row = stored(system, {"label": label or os.path.basename(rom),
                              "path": rom, "core_path": core}, players)
        games = [g for g in read_games(RECENT) if g.get("path") != rom]
        write_json(RECENT, {"games": ([row] + games)[:RECENT_MAX]})
    except OSError:
        pass                              # remembering is a nicety, not the job                              # remembering is a nicety, not the job
    argv = [PICKER]
    # A one-player game with one controller has nothing to ask, and the picker
    # sizes its board to the game rather than always offering four.
    if players.isdigit():
        argv += ["--max-players", players]
    shader = SHADERS.get(system, CRT)
    if not shader or os.path.exists(shader):
        argv += ["--shader", shader or "none"]
    run(argv + ["-f", "-L", core, rom], os.path.basename(rom))


def list_stored(path, heading, empty):
    """Recent and Favourites are the same listing over a different file."""
    xbmcplugin.setPluginCategory(HANDLE, heading)
    xbmcplugin.setContent(HANDLE, "games")
    games = [g for g in read_games(path) if os.path.exists(g.get("path", ""))]
    if not games:
        xbmcgui.Dialog().notification(heading, empty, xbmcgui.NOTIFICATION_INFO)
    counts = player_counts()
    for game in games:
        system = game.get("system", "")
        users = counts.get(system, {}).get(game.get("label", ""))
        item = game_item(system, game, users, short_name(system))
        target = url(play="1", system=system,
                     maxplayers=game.get("maxplayers", "") or str(users or ""),
                     core=game.get("core_path", ""), rom=game.get("path", ""))
        xbmcplugin.addDirectoryItem(HANDLE, target, item, False)
    # Recent is already in the order that matters, so it must not be re-sorted.
    xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_UNSORTED)
    xbmcplugin.endOfDirectory(HANDLE)


def toggle_favourite(system, label):
    games = read_games(FAVOURITES)
    kept = [g for g in games if not (g["system"] == system and g["label"] == label)]
    if len(kept) == len(games):
        found = None
        for name, data in playlists():
            if name != system:
                continue
            for entry in data.get("items", []):
                if entry.get("label") == label:
                    found = entry
                    break
        if found is None:
            xbmcgui.Dialog().notification("Favourites", "Could not find that game",
                                          xbmcgui.NOTIFICATION_ERROR)
            return
        kept.append(stored(system, found,
                           player_counts().get(system, {}).get(label)))
        message = "Added to favourites"
    else:
        message = "Removed from favourites"
    write_json(FAVOURITES, {"games": kept})
    xbmcgui.Dialog().notification("Favourites", message, xbmcgui.NOTIFICATION_INFO,
                                  2500)
    xbmc.executebuiltin("Container.Refresh")


def resume():
    """Start the last game again.

    RetroArch has no suspend-to-front-end: holding Start quits it. But with
    savestates auto-saved on exit and auto-loaded on start, quitting and
    coming back here lands on the same frame -- so one press is the whole of
    "carry on where I was".
    """
    try:
        with open(LAST_GAME) as handle:
            last = json.load(handle)
    except (OSError, ValueError):
        xbmcgui.Dialog().notification("Continue", "No game has been played yet",
                                      xbmcgui.NOTIFICATION_INFO)
        return
    launch(last.get("core", ""), last.get("rom", ""),
           last.get("system", ""), last.get("maxplayers", ""))


def run(argv, what, cwd=None):
    # Debian/Ubuntu Kodi builds strip the System.Exec builtins, so spawn directly.
    env = dict(os.environ)
    env.setdefault("DISPLAY", ":0")
    try:
        subprocess.Popen(argv, env=env, cwd=cwd,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except OSError as exc:
        xbmc.log("plugin.program.retroarch: launch failed: %s" % exc, xbmc.LOGERROR)
        xbmcgui.Dialog().notification("RetroArch", "Could not start RetroArch",
                                      xbmcgui.NOTIFICATION_ERROR)
        return
    xbmc.log("plugin.program.retroarch: launched %s" % " ".join(argv), xbmc.LOGINFO)
    xbmcgui.Dialog().notification("RetroArch", what, xbmcgui.NOTIFICATION_INFO, 3000)


def reap():
    # Popen children stay as zombies under kodi.bin until reaped; clear any
    # finished RetroArch processes each time the plugin is invoked.
    try:
        while os.waitpid(-1, os.WNOHANG)[0] != 0:
            pass
    except (ChildProcessError, OSError):
        pass


def pc_games():
    try:
        with open(PCGAMES) as fh:
            return json.load(fh).get("games", [])
    except (OSError, ValueError):
        return []


def list_pc_games():
    xbmcplugin.setPluginCategory(HANDLE, "PC Games")
    xbmcplugin.setContent(HANDLE, "games")
    for game in pc_games():
        exe = (game.get("exec") or [""])[0]
        if not exe or not os.path.exists(exe):
            continue
        item = xbmcgui.ListItem(label=game.get("name", game["id"]))
        item.setInfo("game", {"title": game.get("name", game["id"]),
                              "platform": "PC"})
        art = game.get("art") or game.get("icon")
        if not (art and os.path.exists(art)) and os.path.exists(PC_FALLBACK_ART):
            art = PC_FALLBACK_ART
        if art and os.path.exists(art):
            item.setArt({"thumb": art, "poster": art, "icon": art})
        item.setProperty("IsPlayable", "false")
        target = url(pcgame=game["id"])
        xbmcplugin.addDirectoryItem(HANDLE, target, item, False)
    xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_LABEL)
    xbmcplugin.endOfDirectory(HANDLE)


def launch_pc(game_id):
    for game in pc_games():
        if game.get("id") == game_id:
            argv = game.get("exec") or []
            if not argv or not os.path.exists(argv[0]):
                xbmcgui.Dialog().notification("PC Game", "Executable not found",
                                              xbmcgui.NOTIFICATION_ERROR)
                return
            wrapped = [PC_LAUNCHER,
                       "--match", game.get("window") or game.get("name", game_id)]
            if game.get("stop_kodi"):
                wrapped += ["--stop-kodi"]
            if game.get("jsm"):
                wrapped += ["--jsm", game["jsm"]]
            for key, value in sorted((game.get("env") or {}).items()):
                wrapped += ["--env", "%s=%s" % (key, value)]
            if game.get("cwd"):
                wrapped += ["--cwd", game["cwd"]]
            wrapped += ["--"] + argv
            if not os.path.exists(PC_LAUNCHER):
                wrapped = argv          # fall back to a plain launch
            run(wrapped, game.get("name", game_id), cwd=game.get("cwd"))
            return
    xbmcgui.Dialog().notification("PC Game", "Unknown game: %s" % game_id,
                                  xbmcgui.NOTIFICATION_ERROR)


def main():
    reap()
    args = dict(parse_qsl(sys.argv[2][1:]))
    if args.get("fav"):
        toggle_favourite(args.get("system", ""), args.get("label", ""))
    elif args.get("recent"):
        list_stored(RECENT, "Recently played", "Nothing has been played yet")
    elif args.get("favourites"):
        list_stored(FAVOURITES, "Favourites", "No favourites yet")
    elif args.get("resume"):
        resume()
    elif args.get("play"):
        launch(args.get("core", ""), args.get("rom", ""),
               args.get("system", ""), args.get("maxplayers", ""))
    elif args.get("setplayers"):
        set_players(args.get("system", ""), args.get("label", ""))
    elif args.get("multiplayer"):
        list_buckets()
    elif args.get("players"):
        list_by_players(args["players"])
    elif args.get("pcgames"):
        list_pc_games()
    elif args.get("pcgame"):
        launch_pc(args["pcgame"])
    elif args.get("open"):
        run([PICKER, "-f"], "RetroArch")
    elif args.get("system"):
        list_games(args["system"])
    else:
        list_systems()


if __name__ == "__main__":
    main()
