#!/bin/bash
# Install the two open-source engines, and declare them as PC games.
#
# Neither is a game, and they differ in a way that matters:
#
#   Quake3e     an engine for Quake III Arena, whose data is commercial. The
#               engine is installed; you supply pak0.pk3 from your own copy.
#               Until you do, the entry stays hidden rather than failing.
#
#   ET Legacy   an engine for Wolfenstein: Enemy Territory, which Splash
#               Damage released as freeware in 2003 and ET Legacy mirrors.
#               So the data is fetched too and it simply works.
#
# Idempotent: an engine already present is left alone, and the ~218 MB of ET
# data is only fetched once.
set -u

REPO="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
LIB="$HOME/.local/lib"
PCGAMES="$HOME/.local/share/pcgames.json"

ok()   { printf '   ok    %s\n' "$*"; }
skip() { printf '   --    %s\n' "$*"; }
warn() { printf '   WARN  %s\n' "$*"; }

need() { command -v "$1" >/dev/null || { warn "$1 is needed and missing"; return 1; }; }
need curl || exit 0
need unzip || exit 0

# --------------------------------------------------------------- Quake3e ---
Q3DIR="$LIB/quake3e"
if [ -x "$Q3DIR/quake3e.x64" ]; then
  skip "Quake3e already installed"
else
  # ec-/Quake3e publishes a rolling "latest" release with Linux binaries, so
  # there is nothing to compile and nothing to pin by hand.
  url=$(curl -sfL https://api.github.com/repos/ec-/Quake3e/releases/latest |
        grep -oE 'https://[^"]*quake3e-linux-x86_64\.zip' | head -1)
  if [ -z "$url" ]; then
    warn "could not find the Quake3e download"
  else
    mkdir -p "$Q3DIR"
    if curl -sfL -o /tmp/quake3e.zip "$url" &&
       unzip -qo /tmp/quake3e.zip -d "$Q3DIR"; then
      # The zip may put the binaries in a subdirectory; flatten it.
      find "$Q3DIR" -mindepth 2 -name 'quake3e*' -exec mv -f {} "$Q3DIR/" \; 2>/dev/null
      chmod +x "$Q3DIR"/quake3e* 2>/dev/null
      ok "Quake3e installed to $Q3DIR"
    else
      warn "could not download Quake3e"
    fi
    rm -f /tmp/quake3e.zip
  fi
fi

# Quake III's data is the one thing here a user has to supply, so say where it
# goes in the place they will look: the folder itself, created and waiting.
if [ -x "$Q3DIR/quake3e.x64" ]; then
  mkdir -p "$HOME/.q3a/baseq3"
  if [ ! -f "$HOME/.q3a/baseq3/README.txt" ]; then
    cat > "$HOME/.q3a/baseq3/README.txt" <<'EOF'
Quake III Arena game data goes in this folder.

    ~/.q3a/baseq3/pak0.pk3      <- from your own copy of the game
    ~/.q3a/baseq3/pak1.pk3 ... pak8.pk3   (the 1.32 point release)

The engine (Quake3e) is already installed. Only the data is missing, and it
is commercial -- it is not downloaded for you and is not in the repository.
Copy the pk3 files from your Quake III CD, your GOG install or your Steam
install (steamapps/common/Quake 3 Arena/baseq3) into this folder.

pak0.pk3 is about 458 MB and is the one that matters; the rest are the point
release. QUAKE III stays hidden on the Kodi menu until pak0.pk3 is here, and
appears on its own once it is -- within ten minutes, or immediately if you
run ~/.local/bin/sync_games.py.
EOF
    ok "wrote $HOME/.q3a/baseq3/README.txt (where your Quake III paks go)"
  fi
  if [ ! -f "$HOME/.q3a/baseq3/pak0.pk3" ]; then
    printf '   --    QUAKE III is hidden until you copy your paks into %s\n' \
           "$HOME/.q3a/baseq3"
  fi
fi

# ------------------------------------------------------------- ET Legacy ---
ETDIR="$LIB/etlegacy"
if [ -x "$ETDIR/etl.x86_64" ]; then
  skip "ET Legacy already installed"
else
  # The site serves downloads under opaque numeric ids that change with every
  # release, so ask each one what its filename is rather than pinning a number.
  url=""
  for id in $(curl -sfL -A Mozilla/5.0 https://www.etlegacy.com/download |
              grep -oE 'download/file/[0-9]+' | grep -oE '[0-9]+$' | sort -u); do
    # tr -d '\r' matters: HTTP headers end CRLF, so without it the name ends
    # in a carriage return and no glob below can ever match it.
    name=$(curl -sIL -A Mozilla/5.0 "https://www.etlegacy.com/download/file/$id" |
           grep -i '^content-disposition' | tr -d '\r' |
           sed -E 's/.*filename="?([^";]+).*/\1/' | tail -1)
    case "$name" in
      *x86_64.tar.gz) url="https://www.etlegacy.com/download/file/$id"; break ;;
    esac
  done
  if [ -z "$url" ]; then
    warn "could not find the ET Legacy download"
  else
    mkdir -p "$ETDIR"
    if curl -sfL -A Mozilla/5.0 -o /tmp/etl.tar.gz "$url" &&
       tar xzf /tmp/etl.tar.gz -C "$ETDIR" --strip-components=1; then
      chmod +x "$ETDIR"/etl*.x86_64 2>/dev/null
      ok "ET Legacy installed to $ETDIR"
    else
      warn "could not download ET Legacy"
    fi
    rm -f /tmp/etl.tar.gz
  fi
fi

# Enemy Territory itself is freeware and mirrored by the project, so unlike
# Quake III this can be fetched rather than asked for.
if [ -d "$ETDIR" ] && [ ! -f "$ETDIR/etmain/pak0.pk3" ]; then
  mkdir -p "$ETDIR/etmain"
  got=1
  for p in pak0 pak1 pak2; do
    [ -f "$ETDIR/etmain/$p.pk3" ] && continue
    curl -sfL -A Mozilla/5.0 -o "$ETDIR/etmain/$p.pk3" \
      "https://mirror.etlegacy.com/etmain/$p.pk3" || got=0
  done
  if [ "$got" = 1 ] && [ -s "$ETDIR/etmain/pak0.pk3" ]; then
    ok "Enemy Territory game data fetched (freeware)"
  else
    warn "could not fetch the ET game data; put pak0-2.pk3 in $ETDIR/etmain"
    rm -f "$ETDIR/etmain/pak0.pk3"
  fi
elif [ -f "$ETDIR/etmain/pak0.pk3" ]; then
  skip "Enemy Territory game data already there"
fi

# ------------------------------------------------- declare them as games ---
# Adding the entries is what makes them appear in Kodi. "requires" keeps an
# entry hidden until its data is present, which is how Quake III can be
# declared before you have copied your paks over.
python3 - "$PCGAMES" "$Q3DIR" "$ETDIR" <<'PY'
import json, os, sys

path, q3dir, etdir = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    with open(path) as fh:
        doc = json.load(fh)
except (OSError, ValueError):
    doc = {"games": []}
doc.setdefault("games", [])
have = {g.get("id") for g in doc["games"]}

wanted = []
if os.path.exists(os.path.join(q3dir, "quake3e.x64")):
    wanted.append({
        "id": "quake3", "name": "QUAKE III",
        "exec": [os.path.join(q3dir, "quake3e.x64"),
                 "+set", "r_mode", "-1", "+set", "r_fullscreen", "1"],
        "cwd": q3dir, "window": "Quake", "stop_kodi": True,
        # Commercial data: supply your own. Hidden until it is here.
        "requires": "~/.q3a/baseq3/pak0.pk3",
    })
if os.path.exists(os.path.join(etdir, "etl.x86_64")):
    wanted.append({
        "id": "etlegacy", "name": "WOLFENSTEIN ET",
        "exec": [os.path.join(etdir, "etl.x86_64")],
        "cwd": etdir, "window": "ET Legacy", "stop_kodi": True,
        "requires": os.path.join(etdir, "etmain", "pak0.pk3"),
    })

added = [g for g in wanted if g["id"] not in have]
doc["games"].extend(added)
if added:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(doc, fh, indent=2)
    print("   ok    declared: %s" % ", ".join(g["id"] for g in added))
else:
    print("   --    both already declared in pcgames.json")
PY
