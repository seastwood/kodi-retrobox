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

PLAYLIST_DIR = os.path.expanduser("~/.local/share/retroarch/plists")
THUMB_DIR = os.path.expanduser("~/.local/share/retroarch/thumbnails")
# Player-assignment screen; it execs RetroArch once pads are claimed.
PICKER = os.path.expanduser("~/.local/bin/ra_players.py")
# Native PC games (not RetroArch content) are described here.
PCGAMES = os.path.expanduser("~/.local/share/pcgames.json")
# Shown when a PC game has no artwork of its own.
PC_FALLBACK_ART = os.path.expanduser("~/.kodi/media/consoles/_pcgames.png")
# Wrapper that handles window focus and returning to Kodi afterwards.
PC_LAUNCHER = os.path.expanduser("~/.local/bin/pcgame_launch.py")
# How many players each game takes, written by sync_games.py from the libretro
# databases plus the hand-kept overrides beside it.
PLAYERS = os.path.expanduser("~/.local/share/gameplayers.json")
# Hand-kept counts. This is the file the Kodi editor writes and the one
# sync_games.py treats as beating the database.
PLAYERS_MANUAL = os.path.expanduser("~/.local/share/gameplayers.manual.json")
SYSTEM_DIR = os.path.expanduser("~/.local/share/retroarch/system")
# The last game started, so CONTINUE on the home screen has something to open.
LAST_GAME = os.path.expanduser("~/.local/state/retroarch/last-game.json")
# The last dozen games played, newest first, and the ones marked as keepers.
RECENT = os.path.expanduser("~/.local/state/retroarch/recent.json")
RECENT_MAX = 12
FAVOURITES = os.path.expanduser("~/.local/share/gamefavourites.json")
SHADER_DIR = os.path.expanduser("~/.local/share/retroarch/shaders")
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
    add_sync_item()
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


def game_installed(game):
    """Whether a declared game is actually on this machine.

    Wine games run through run-wine-game.sh, which always exists, so testing
    exec[0] would call every one of them present. The working directory is the
    honest test there, and exec[0] is the honest test for a native game -- so
    check whichever of the two is declared.
    """
    # An engine can be installed while the game it plays is not. Quake3e is
    # the case that matters: the binary is here, the commercial paks are the
    # user's to supply, and a tile that launches into an error is worse than
    # no tile. "requires" names the file that settles it.
    needs = game.get("requires")
    if needs and not os.path.exists(os.path.expanduser(needs)):
        return False
    cwd = game.get("cwd")
    if cwd and not os.path.isdir(os.path.expanduser(cwd)):
        return False
    argv = game.get("exec") or []
    if argv and not os.path.exists(os.path.expanduser(argv[0])):
        return False
    return bool(argv)


def pc_games(all_declared=False):
    """Declared games that are installed here. A declaration for a game you
    have not copied over yet is hidden rather than shown as a tile that fails,
    which is what lets the list be restored from a backup before the games
    are."""
    try:
        with open(PCGAMES) as fh:
            games = json.load(fh).get("games", [])
    except (OSError, ValueError):
        return []
    return games if all_declared else [g for g in games if game_installed(g)]


def list_pc_games():
    xbmcplugin.setPluginCategory(HANDLE, "PC Games")
    xbmcplugin.setContent(HANDLE, "games")
    # Sorted here rather than by Kodi, so the games stay alphabetical
    # while ADD GAME stays pinned at the end instead of sorting into
    # the middle of them.
    for game in sorted(pc_games(),
                       key=lambda g: g.get("name", g["id"]).lower()):
        exe = os.path.expanduser((game.get("exec") or [""])[0])
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
        # Adding a game from the television is no use without a way back out
        # of it: the menu button on the pad opens this.
        item.addContextMenuItems([
            ("Set picture", "RunPlugin(%s)" % url(artpcgame=game["id"])),
            ("Rename", "RunPlugin(%s)" % url(renamepcgame=game["id"])),
            ("Remove from PC Games",
             "RunPlugin(%s)" % url(removepcgame=game["id"])),
        ])
        target = url(pcgame=game["id"])
        xbmcplugin.addDirectoryItem(HANDLE, target, item, False)

    # Sorting is applied before this is added, so ADD GAME stays last instead
    # of sorting into the middle of the games under "A".
    xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_UNSORTED)
    add = xbmcgui.ListItem(label="[+]  ADD GAME")
    add.setInfo("game", {"title": "Add Game", "platform": "PC"})
    if os.path.exists(PC_FALLBACK_ART):
        add.setArt({"thumb": PC_FALLBACK_ART, "poster": PC_FALLBACK_ART,
                    "icon": PC_FALLBACK_ART})
    add.setProperty("IsPlayable", "false")
    xbmcplugin.addDirectoryItem(HANDLE, url(addpcgame=1), add, False)
    add_sync_item()
    xbmcplugin.endOfDirectory(HANDLE)


def add_sync_item():
    """A "look for new games now" tile.

    The sync runs on a timer every ten minutes, which is fine when you walk
    away and wrong when you are standing there having just copied something in.
    """
    item = xbmcgui.ListItem(label="[~]  SYNC GAMES")
    item.setInfo("game", {"title": "Sync Games", "platform": "PC"})
    if os.path.exists(PC_FALLBACK_ART):
        item.setArt({"thumb": PC_FALLBACK_ART, "poster": PC_FALLBACK_ART,
                     "icon": PC_FALLBACK_ART})
    item.setProperty("IsPlayable", "false")
    xbmcplugin.addDirectoryItem(HANDLE, url(syncgames=1), item, False)


# --------------------------------------------------------------- settings --
AUTOSTART = os.path.expanduser("~/.config/autostart/kodi.desktop")
AUTOSTART_SRC = os.path.expanduser("~/.local/share/retrobox/kodi.desktop.off")
NO_RESTART = os.path.expanduser("~/.config/retrobox-no-restart")


def autostart_on():
    return os.path.exists(AUTOSTART)


def set_autostart(on):
    """Kodi starting at login is just a .desktop file, so the toggle keeps a
    copy aside rather than trying to regenerate one it never wrote."""
    try:
        if on:
            if os.path.exists(AUTOSTART_SRC):
                os.makedirs(os.path.dirname(AUTOSTART), exist_ok=True)
                with open(AUTOSTART_SRC) as src, open(AUTOSTART, "w") as dst:
                    dst.write(src.read())
                return True
            return False
        if os.path.exists(AUTOSTART):
            os.makedirs(os.path.dirname(AUTOSTART_SRC), exist_ok=True)
            with open(AUTOSTART) as src, open(AUTOSTART_SRC, "w") as dst:
                dst.write(src.read())
            os.remove(AUTOSTART)
        return True
    except OSError:
        return False


# The add-on is symlinked into ~/.kodi/addons, so realpath -- abspath would
# put the repository somewhere inside .kodi.
REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.realpath(__file__))))
UPDATE_SH = os.path.join(REPO, "install", "update.sh")
BACKUP_SH = os.path.expanduser("~/.local/bin/retro_backup.sh")
BACKUP_CONF = os.path.join(REPO, "backup", "backup.conf")


def backup_configured():
    """Whether backup.conf names a destination, rather than only examples."""
    try:
        with open(BACKUP_CONF) as handle:
            for line in handle:
                line = line.strip()
                if line and not line.startswith("#") and line.split(":")[0] in (
                        "local", "ssh", "path"):
                    return True
    except OSError:
        pass
    return False


def run_backup():
    if not os.path.exists(BACKUP_SH):
        xbmcgui.Dialog().ok("Backup", "retro_backup.sh is not installed.")
        return False
    if not backup_configured():
        xbmcgui.Dialog().ok(
            "Backup",
            "No backup destination is set, so a backup would do nothing.\n\n"
            "Add one to backup/backup.conf first -- backup.conf.example "
            "explains the three kinds.")
        return False
    progress = xbmcgui.DialogProgressBG()
    progress.create("Backup", "Copying saves and settings")
    try:
        done = subprocess.run([BACKUP_SH], stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=3600)
    except (OSError, subprocess.SubprocessError) as err:
        progress.close()
        xbmcgui.Dialog().ok("Backup", "The backup did not run: %s" % err)
        return False
    progress.close()
    out = done.stdout.decode("utf-8", "replace")
    if done.returncode != 0:
        xbmcgui.Dialog().textviewer("Backup failed", out or "no output",
                                    usemono=True)
        return False
    tail = [l for l in out.splitlines() if l.strip()]
    xbmcgui.Dialog().notification("Backup", tail[-1] if tail else "done",
                                  xbmcgui.NOTIFICATION_INFO)
    return True


RESTORE_SH = os.path.join(REPO, "install", "restore.sh")
# kodi-autostart.sh looks for this after Kodi exits. A restore cannot run
# while Kodi is up -- Kodi rewrites its own userdata as it quits, straight
# over anything just put back -- so the request is left here and carried out
# in the gap between Kodi stopping and starting again.
RESTORE_REQUEST = os.path.expanduser("~/.local/state/restore-request")


def backup_generations():
    """Dated backup directories under the first local: destination."""
    root = ""
    try:
        with open(BACKUP_CONF) as handle:
            for line in handle:
                line = line.strip()
                if line.startswith("local:"):
                    root = os.path.expanduser(line.split(":", 1)[1].strip())
                    break
    except OSError:
        pass
    if not root or not os.path.isdir(root):
        return []
    out = []
    for name in sorted(os.listdir(root), reverse=True):
        path = os.path.join(root, name)
        if name == "latest" or not os.path.isdir(path):
            continue
        out.append((name, path))
    return out


def restore_backup():
    """Ask which backup, then have the supervisor apply it while Kodi is down."""
    if not os.path.exists(RESTORE_SH):
        xbmcgui.Dialog().ok("Restore", "restore.sh was not found at\n%s"
                            % RESTORE_SH)
        return
    gens = backup_generations()
    if not gens:
        xbmcgui.Dialog().ok(
            "Restore",
            "No backups found.\n\nBackups are switched off until a "
            "destination is set in backup/backup.conf.")
        return

    pick = xbmcgui.Dialog().select(
        "Restore which backup?", ["%s" % name for name, _ in gens])
    if pick < 0:
        return
    name, path = gens[pick]

    if not xbmcgui.Dialog().yesno(
            "Restore from %s" % name,
            "This replaces your saves, playlists and settings with the ones "
            "in that backup.\n\nWhatever is there now is kept in "
            "~/.local/state, and your games are not touched.\n\n"
            "Kodi will close, restore, and start again.",
            nolabel="Cancel", yeslabel="Restore"):
        return

    try:
        os.makedirs(os.path.dirname(RESTORE_REQUEST), exist_ok=True)
        with open(RESTORE_REQUEST, "w") as handle:
            handle.write(path + "\n")
    except OSError as err:
        xbmcgui.Dialog().ok("Restore", "Could not ask for the restore: %s" % err)
        return

    if not os.path.exists(os.path.expanduser("~/.local/bin/kodi-autostart.sh")):
        xbmcgui.Dialog().ok(
            "Restore",
            "Kodi is not being supervised, so nothing would bring it back "
            "afterwards.\n\nQuit Kodi and run install/restore.sh yourself.")
        try:
            os.remove(RESTORE_REQUEST)
        except OSError:
            pass
        return

    xbmcgui.Dialog().notification("Restoring", "Kodi will close and come back",
                                  xbmcgui.NOTIFICATION_INFO)
    xbmc.sleep(2500)
    xbmc.executebuiltin("Quit()")


def update_system():
    """Pull the latest version and re-run the install.

    The warning is not ceremony. An update replaces every script this console
    runs, and while your games and saves live outside the repository and are
    not touched, a bad update is much easier to sit out if there is a backup
    of the settings and playlists to go back to.
    """
    if not os.path.exists(UPDATE_SH):
        xbmcgui.Dialog().ok("Update", "update.sh was not found at\n%s"
                            % UPDATE_SH)
        return

    have = backup_configured()
    choice = xbmcgui.Dialog().select(
        "Update this console", [
            "Back up first, then update" + ("" if have else "  (not configured)"),
            "Update without backing up",
            "Cancel",
        ])
    if choice in (-1, 2):
        return
    if choice == 0 and not run_backup():
        if not xbmcgui.Dialog().yesno(
                "Update", "The backup did not happen.\n\nUpdate anyway?",
                nolabel="Stop", yeslabel="Update"):
            return

    if not xbmcgui.Dialog().yesno(
            "Update this console",
            "This replaces the code with the latest version from GitHub.\n\n"
            "Your games, saves and settings are outside the repository and "
            "are not touched.\n\nKodi should be restarted afterwards.",
            nolabel="Cancel", yeslabel="Update"):
        return

    progress = xbmcgui.DialogProgressBG()
    progress.create("Update", "Fetching and installing")
    try:
        done = subprocess.run([UPDATE_SH, "--yes"], stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=3600)
    except (OSError, subprocess.SubprocessError) as err:
        progress.close()
        xbmcgui.Dialog().ok("Update", "The update did not run: %s" % err)
        return
    progress.close()
    out = done.stdout.decode("utf-8", "replace")
    if done.returncode != 0:
        xbmcgui.Dialog().textviewer("Update finished with problems", out,
                                    usemono=True)
        return
    now = ""
    for line in out.splitlines():
        if "now at" in line:
            now = line.strip()
    xbmcgui.Dialog().ok(
        "Update done", "%s\n\nRestart Kodi to pick up the new version."
        % (now or "Updated."))


STUCK = ["JoyShockMapper", "jsm-hud", "Baldur.exe", "BF2.exe", "bf1942.exe",
         "iw3sp.exe", "iw3mp.exe", "quake3e.x64", "etl.x86_64",
         "openjk.x86_64", "openjk_sp.x86_64"]


def stop_stuck_game():
    """Stop a game, and anything it left behind, without a keyboard.

    A game that has stopped responding cannot be closed from its own menu, and
    a JoyShockMapper that outlives one types into Kodi. Exact process names
    only -- a -f pattern would match this add-on.
    """
    found = []
    for name in STUCK:
        if subprocess.run(["pgrep", "-x", name], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, check=False).returncode == 0:
            found.append(name)
    if not found:
        xbmcgui.Dialog().ok("Settings", "Nothing is running that needs stopping.")
        return
    if not xbmcgui.Dialog().yesno(
            "Stop a game", "Still running:\n\n[B]%s[/B]\n\nStop them?"
            % ", ".join(found), nolabel="Leave", yeslabel="Stop"):
        return
    for name in found:
        subprocess.run(["pkill", "-x", name], check=False)
    xbmc.sleep(3000)
    for name in found:
        subprocess.run(["pkill", "-9", "-x", name], check=False)
    subprocess.run(["wineserver", "-k"], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        os.remove(os.path.expanduser("~/.local/state/kodi-hold"))
    except OSError:
        pass
    xbmcgui.Dialog().notification("Stopped", ", ".join(found),
                                  xbmcgui.NOTIFICATION_INFO)


def settings_screen():
    """The handful of things about this console worth changing from the sofa.

    Everything here is a file on disk rather than a setting inside Kodi,
    because what it controls happens outside Kodi -- before it starts, and
    while it is not running.
    """
    while True:
        restart = not os.path.exists(NO_RESTART)
        rows = [
            "Start Kodi at login:  %s" % ("ON" if autostart_on() else "off"),
            "Restart Kodi if it crashes:  %s" % ("ON" if restart else "off"),
            "Run the game sync now",
            "Stop a game that will not close",
            "Update this console",
            "Restore from a backup",
            "Kodi's own settings",
            "Close",
        ]
        pick = xbmcgui.Dialog().select("Settings", rows)
        if pick in (-1, 7):
            return
        if pick == 0:
            wanted = not autostart_on()
            if not set_autostart(wanted):
                xbmcgui.Dialog().ok(
                    "Settings",
                    "Could not change that.\n\nThere is no saved copy of the "
                    "autostart entry to put back; run install.sh again to "
                    "restore it.")
        elif pick == 1:
            try:
                if restart:
                    with open(NO_RESTART, "w") as handle:
                        handle.write(
                            "kodi-autostart.sh checks for this file.\n")
                elif os.path.exists(NO_RESTART):
                    os.remove(NO_RESTART)
            except OSError:
                pass
        elif pick == 2:
            sync_games_now()
            return
        elif pick == 3:
            stop_stuck_game()
        elif pick == 4:
            update_system()
            return
        elif pick == 5:
            restore_backup()
            return
        elif pick == 6:
            # Otherwise the only way in is the S key, which a console with no
            # keyboard does not have.
            xbmc.executebuiltin("ActivateWindow(Settings)")
            return


def write_pc_games(games):
    try:
        with open(PCGAMES, "w") as fh:
            json.dump({"games": games}, fh, indent=2)
    except OSError as err:
        xbmcgui.Dialog().ok("PC Games", "Could not save: %s" % err)
        return False
    try:
        subprocess.call([os.path.expanduser("~/.local/bin/kodi_menu.py")])
    except OSError:
        pass
    return True


def remove_pc_game(game_id):
    games = pc_games(all_declared=True)
    game = next((g for g in games if g.get("id") == game_id), None)
    if not game:
        return
    name = game.get("name", game_id)
    if not xbmcgui.Dialog().yesno(
            "Remove from PC Games",
            "Remove [B]%s[/B] from the menu?\n\n"
            "Only this entry goes. The game itself is left on disk." % name,
            nolabel="Keep", yeslabel="Remove"):
        return
    if write_pc_games([g for g in games if g.get("id") != game_id]):
        xbmcgui.Dialog().notification("Removed", name,
                                      xbmcgui.NOTIFICATION_INFO)
        xbmc.executebuiltin("Container.Refresh")


PC_ART_DIR = os.path.expanduser("~/.kodi/media/pcgames")


def set_pc_art(game_id):
    """Give a PC game a picture, chosen with the controller.

    The file is copied into ~/.kodi/media/pcgames rather than linked, so the
    tile does not go blank later because the picture was on a stick, or inside
    a game folder that was moved.
    """
    games = pc_games(all_declared=True)
    game = next((g for g in games if g.get("id") == game_id), None)
    if not game:
        return
    name = game.get("name", game_id)

    start = game.get("cwd") or PC_ROOT
    if not os.path.isdir(os.path.expanduser(start)):
        start = os.path.expanduser("~")
    chosen = xbmcgui.Dialog().browse(
        2, "Picture for %s" % name, "files", ".jpg|.jpeg|.png",
        True, False, os.path.expanduser(start))
    if not chosen or not os.path.isfile(chosen):
        return

    ext = os.path.splitext(chosen)[1].lower() or ".jpg"
    dest = os.path.join(PC_ART_DIR, "%s%s" % (game_id, ext))
    try:
        os.makedirs(PC_ART_DIR, exist_ok=True)
        with open(chosen, "rb") as src, open(dest, "wb") as out:
            out.write(src.read())
    except OSError as err:
        xbmcgui.Dialog().ok("Set picture", "Could not copy it: %s" % err)
        return

    # An older picture in the other format would otherwise sit there unused.
    for other in (".jpg", ".jpeg", ".png"):
        stale = os.path.join(PC_ART_DIR, "%s%s" % (game_id, other))
        if other != ext and os.path.exists(stale):
            try:
                os.remove(stale)
            except OSError:
                pass

    game["art"] = dest
    if write_pc_games(games):
        xbmcgui.Dialog().notification("Picture set", name,
                                      xbmcgui.NOTIFICATION_INFO)
        xbmc.executebuiltin("Container.Refresh")


def rename_pc_game(game_id):
    games = pc_games(all_declared=True)
    game = next((g for g in games if g.get("id") == game_id), None)
    if not game:
        return
    new = xbmcgui.Dialog().input("Name for the menu", game.get("name", game_id))
    if not new or new == game.get("name"):
        return
    # The id stays put: it is what finds the controller mapping, and changing
    # it would silently drop the game back to the default pad layout.
    game["name"] = new
    if write_pc_games(games):
        xbmcgui.Dialog().notification("Renamed", new, xbmcgui.NOTIFICATION_INFO)
        xbmc.executebuiltin("Container.Refresh")


def sync_games_now():
    """Run the sync the timer would have run, and say what it found."""
    sync = os.path.expanduser("~/.local/bin/sync_games.py")
    if not os.path.exists(sync):
        xbmcgui.Dialog().ok("Sync Games", "sync_games.py is not installed.")
        return
    progress = xbmcgui.DialogProgressBG()
    progress.create("Games", "Looking for new games")
    try:
        done = subprocess.run([sync], stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=900)
        out = done.stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError) as err:
        progress.close()
        xbmcgui.Dialog().ok("Sync Games", "The sync did not run: %s" % err)
        return
    progress.close()
    # Its last useful line is the summary; a failure is worth showing in full.
    lines = [l for l in out.splitlines() if l.strip()]
    if done.returncode != 0:
        xbmcgui.Dialog().textviewer("Sync Games", out or "no output",
                                    usemono=True)
    else:
        summary = next((l for l in reversed(lines)
                        if l.startswith("menu ")), lines[-1] if lines else "done")
        xbmcgui.Dialog().notification("Sync", summary,
                                      xbmcgui.NOTIFICATION_INFO)
    xbmc.executebuiltin("Container.Refresh")


PC_ROOT = os.path.expanduser("~/Games/pc")
WINE_RUNNER = os.path.expanduser("~/.local/bin/run-wine-game.sh")


def wine_prefixes():
    """Every Wine prefix on this machine, newest-looking first.

    A Wine game lives under <prefix>/drive_c, and the usual prefix is ~/.wine
    -- a dotfolder Kodi's browser will not show. Offering the prefixes as
    starting points means never having to navigate into a hidden directory.
    """
    found = []
    for path in [os.path.expanduser("~/.wine")] + sorted(
            glob.glob(os.path.expanduser("~/.local/share/wine/*"))):
        drive = os.path.join(path, "drive_c")
        if os.path.isdir(drive):
            found.append((os.path.basename(path.rstrip("/")), path, drive))
    return found


def prefix_of(path):
    """The Wine prefix a path sits in, or None. Set as WINEPREFIX on the entry
    so the game runs in the prefix it was installed into rather than the
    default one."""
    marker = os.sep + "drive_c" + os.sep
    if marker in path:
        return path[:path.index(marker)]
    return None


def _slug(text, taken):
    """A short id from the game's name, unique among the ones already used."""
    base = "".join(c.lower() if c.isalnum() else "-" for c in text)
    base = "-".join(part for part in base.split("-") if part)[:24] or "game"
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = "%s-%d" % (base, n), n + 1
    return candidate


def add_pc_game():
    """Add a PC game from the television, with a controller.

    Everything here is answerable with a pad: Kodi's file browser navigates
    with the d-pad and its keyboard is on-screen. The point is that adding a
    game never requires going and editing pcgames.json by hand.
    """
    dialog = xbmcgui.Dialog()
    places = []
    if os.path.isdir(PC_ROOT):
        places.append(("Games folder", PC_ROOT))
    for name, _prefix, drive in wine_prefixes():
        places.append(("Wine: %s" % name, drive))
    places.append(("Home folder", os.path.expanduser("~")))

    if len(places) > 1:
        pick = dialog.select("Where is the game?", [p[0] for p in places])
        if pick < 0:
            return
        start = places[pick][1]
    else:
        start = places[0][1]

    chosen = dialog.browse(1, "Choose the game's program file", "files",
                           "", False, False, start)
    if not chosen or not os.path.isfile(chosen):
        return
    folder = os.path.dirname(chosen)

    suggested = os.path.splitext(os.path.basename(chosen))[0]
    if suggested.lower() in ("game", "start", "launch", "run", "bin"):
        suggested = os.path.basename(folder)      # a generic name says nothing
    name = dialog.input("Name for the menu", suggested.replace("_", " ").upper())
    if not name:
        return

    games = pc_games(all_declared=True)
    entry = {"id": _slug(name, {g.get("id") for g in games}),
             "name": name, "cwd": folder, "window": name.split()[0]}

    if chosen.lower().endswith(".exe"):
        # Windows games go through the Wine runner, which takes the folder and
        # the executable separately.
        if not os.path.exists(WINE_RUNNER):
            dialog.ok("Add Game", "This is a Windows program, but Wine support "
                                  "is not installed.\n\nRe-run install.sh "
                                  "with --with-optional.")
            return
        entry["exec"] = [WINE_RUNNER, folder, os.path.basename(chosen)]
        # run-wine-game.sh otherwise falls back to its own default prefix,
        # which would be the wrong one for a game installed elsewhere.
        prefix = prefix_of(chosen)
        if prefix:
            entry["env"] = {"WINEPREFIX": prefix}
    else:
        if not os.access(chosen, os.X_OK):
            try:
                os.chmod(chosen, os.stat(chosen).st_mode | 0o111)
            except OSError:
                dialog.ok("Add Game", "That file is not executable and could "
                                      "not be made executable.")
                return
        entry["exec"] = [chosen]

    entry["stop_kodi"] = bool(dialog.yesno(
        "Add Game", "Close Kodi while [B]%s[/B] runs?\n\n"
                    "Choose Yes unless the game is happy to share the screen."
        % name, nolabel="No", yeslabel="Yes"))

    games.append(entry)
    if not write_pc_games(games):
        return

    if dialog.yesno("Add Game", "Give [B]%s[/B] a picture now?" % name,
                    nolabel="Later", yeslabel="Choose one"):
        set_pc_art(entry["id"])

    mapping = os.path.expanduser(
        "~/.config/JoyShockMapper/games/%s.txt" % entry["id"])
    dialog.notification("Added", "%s%s" % (
        name, "" if os.path.exists(mapping) else " (default pad mapping)"),
        xbmcgui.NOTIFICATION_INFO)
    xbmc.executebuiltin("Container.Refresh")


def launch_pc(game_id):
    for game in pc_games():
        if game.get("id") == game_id:
            argv = [os.path.expanduser(a) for a in (game.get("exec") or [])]
            if not argv or not os.path.exists(argv[0]):
                xbmcgui.Dialog().notification("PC Game", "Executable not found",
                                              xbmcgui.NOTIFICATION_ERROR)
                return
            wrapped = [PC_LAUNCHER,
                       "--match", game.get("window") or game.get("name", game_id)]
            if game.get("stop_kodi"):
                wrapped += ["--stop-kodi"]
            wrapped += ["--id", game_id]
            if game.get("jsm"):
                wrapped += ["--jsm", os.path.expanduser(game["jsm"])]
            for key, value in sorted((game.get("env") or {}).items()):
                wrapped += ["--env", "%s=%s" % (key, value)]
            if game.get("cwd"):
                wrapped += ["--cwd", os.path.expanduser(game["cwd"])]
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
    elif args.get("addpcgame"):
        add_pc_game()
    elif args.get("removepcgame"):
        remove_pc_game(args["removepcgame"])
    elif args.get("renamepcgame"):
        rename_pc_game(args["renamepcgame"])
    elif args.get("artpcgame"):
        set_pc_art(args["artpcgame"])
    elif args.get("syncgames"):
        sync_games_now()
    elif args.get("settings"):
        settings_screen()
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
