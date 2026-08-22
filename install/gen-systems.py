"""Generate system/systems.tsv: every system RetroArch can both identify and run."""
import glob, os, re, collections, sys

INFO = "/usr/share/libretro/info"
RDB = "/usr/share/libretro/database/rdb"

# Folder names already in use on the original machine, which must not change,
# plus short names for the systems people actually ask for by name. Anything
# not listed gets a slug generated from the system name.
NAMES = {
    "Nintendo - Nintendo Entertainment System": "nes",
    "Nintendo - Super Nintendo Entertainment System": "snes",
    "Nintendo - Nintendo 64": "n64",
    "Nintendo - Game Boy": "gb",
    "Nintendo - Game Boy Color": "gbc",
    "Nintendo - Game Boy Advance": "gba",
    "Nintendo - GameCube": "gamecube",
    "Nintendo - Wii": "wii",
    "Nintendo - Nintendo DS": "nds",
    "Nintendo - Virtual Boy": "virtualboy",
    "Nintendo - Pokemon Mini": "pokemon-mini",
    "Nintendo - Family Computer Disk System": "famicom-disk",
    "Sega - Mega Drive - Genesis": "sega-genesis",
    "Sega - Mega-CD - Sega CD": "sega-cd",
    "Sega - Master System - Mark III": "master-system",
    "Sega - Game Gear": "game-gear",
    "Sega - Saturn": "saturn",
    "Sega - Dreamcast": "dreamcast",
    "Sega - 32X": "sega-32x",
    "Sega - SG-1000": "sg-1000",
    "Sony - PlayStation": "playstation",
    "Sony - PlayStation 2": "playstation-2",
    "Sony - PlayStation Portable": "psp",
    "Microsoft - Xbox": "xbox",
    "Atari - 2600": "atari-2600",
    "Atari - 5200": "atari-5200",
    "Atari - 7800": "atari-7800",
    "Atari - Jaguar": "jaguar",
    "Atari - Lynx": "lynx",
    "NEC - PC Engine - TurboGrafx 16": "pc-engine",
    "NEC - PC Engine CD - TurboGrafx-CD": "pc-engine-cd",
    "SNK - Neo Geo Pocket": "neogeo-pocket",
    "SNK - Neo Geo Pocket Color": "neogeo-pocket-color",
    "The 3DO Company - 3DO": "3do",
    "Bandai - WonderSwan": "wonderswan",
    "Bandai - WonderSwan Color": "wonderswan-color",
    "Coleco - ColecoVision": "colecovision",
    "GCE - Vectrex": "vectrex",
    "Magnavox - Odyssey2": "odyssey2",
    "Commodore - Amiga": "amiga",
    "Commodore - 64": "c64",
    "Sinclair - ZX Spectrum": "zx-spectrum",
    "Amstrad - CPC": "amstrad-cpc",
    "Mattel - Intellivision": "intellivision",
    "Fairchild - Channel F": "channel-f",
    "Sharp - X68000": "x68000",
    "MAME": "mame",
    "FBNeo - Arcade Games": "arcade",
    "DOS": "dos",
}

# Cores this console has deliberately chosen, which must not drift: these are
# exactly what the original machine runs, including the ones picked for a
# reason (snes9x because supafaust cannot do achievements, genesis_plus_gx_wide
# because clownmdemu was swapped out).
CHOSEN = {
    "Nintendo - Nintendo Entertainment System": "fceumm_libretro",
    "Nintendo - Super Nintendo Entertainment System": "snes9x_libretro",
    "Nintendo - Nintendo 64": "mupen64plus_next_libretro",
    "Nintendo - Game Boy": "DoubleCherryGB_libretro",
    "Nintendo - Game Boy Advance": "skyemu_libretro",
    "Nintendo - GameCube": "dolphin_libretro",
    "Sega - Mega Drive - Genesis": "genesis_plus_gx_wide_libretro",
    "Sega - Mega-CD - Sega CD": "genesis_plus_gx_wide_libretro",
    "Sony - PlayStation": "mednafen_psx_hw_libretro",
}

# For every other system, the first of these that claims it.
PREFERRED = [
    "genesis_plus_gx_wide", "snes9x", "mupen64plus_next", "mednafen_psx_hw",
    "dolphin", "skyemu", "DoubleCherryGB", "fceumm", "mgba", "gambatte",
    "stella", "handy", "mednafen_pce", "flycast", "picodrive", "prosystem",
    "mednafen_wswan", "mednafen_ngp", "mednafen_vb", "opera", "blueMSX",
    "fbneo", "mame2003_plus", "vice_x64", "puae", "fuse", "cap32",
    "beetle_saturn", "yabause", "desmume", "ppsspp", "freeintv", "o2em",
    "vecx", "virtualjaguar", "hatari", "px68k", "dosbox_pure",
]


def slug(name):
    base = re.sub(r"^[^-]+ - ", "", name)          # drop the manufacturer
    base = base.lower()
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return base or re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def main():
    sys2cores = collections.defaultdict(list)
    for f in glob.glob(os.path.join(INFO, "*.info")):
        core = os.path.basename(f)[:-5]
        try:
            text = open(f, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        m = re.search(r'^database = "([^"]*)"', text, re.M)
        if not m:
            continue
        for db in m.group(1).split("|"):
            db = db.strip()
            if db:
                sys2cores[db].append(core)

    rdbs = {os.path.basename(p)[:-4] for p in glob.glob(os.path.join(RDB, "*.rdb"))}
    rows = []
    for system in sorted(set(sys2cores) & rdbs):
        cores = sorted(set(sys2cores[system]))
        best = CHOSEN.get(system)
        if best and best not in cores:
            best = None
        for want in PREFERRED:
            for c in cores:
                if c == want + "_libretro":
                    best = c
                    break
            if best:
                break
        if not best:
            best = cores[0]
        rows.append((NAMES.get(system, slug(system)), system, best))

    seen = {}
    for folder, system, _core in rows:
        seen.setdefault(folder, []).append(system)
    clashes = {f: s for f, s in seen.items() if len(s) > 1}

    out = ["# Every system RetroArch can both identify and run on this machine.",
           "# folder<TAB>system name<TAB>default core",
           "#",
           "# install.sh makes an empty folder per line under ~/Games/emulation.",
           "# The folder name is for you, not for RetroArch: games are identified",
           "# by hashing them, so one in the wrong folder is still filed correctly."]
    for folder, system, core in rows:
        out.append("%s\t%s\t%s" % (folder, system, core))
    print("\n".join(out))
    print("# systems: %d, name clashes: %d" % (len(rows), len(clashes)), file=sys.stderr)
    for f, s in clashes.items():
        print("#   clash %s: %s" % (f, s), file=sys.stderr)


main()
