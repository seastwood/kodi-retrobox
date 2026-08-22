#!/bin/bash
# Make Kodi look and behave like the console, rather than like Kodi.
#
# Three things a fresh install cannot do for itself:
#   1. fetch the skin and the menu add-on, which are not ours to vendor;
#   2. mark every add-on enabled, because Kodi otherwise asks the person at the
#      television to approve each one by hand;
#   3. select the skin and its 8-bit font.
#
# Kodi must have been started once and quit, because it creates its add-on
# database on first run and this edits that database. Run it with Kodi closed.
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
KODI="$HOME/.kodi"
ADDONS="$KODI/addons"
GUISETTINGS="$KODI/userdata/guisettings.xml"
MIRROR=https://mirrors.kodi.tv/addons/nexus
SKIN=skin.aeon.nox.silvo
FONT="8-Bit"

ok()   { printf '   ok    %s\n' "$*"; }
skip() { printf '   --    %s\n' "$*"; }
warn() { printf '   WARN  %s\n' "$*"; }
say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }

if pgrep -x kodi.bin >/dev/null 2>&1; then
  echo "Kodi is running. Quit it first: this edits the database it has open."
  exit 1
fi

# ------------------------------------------------------- third-party add-ons --
say "Add-ons this console's look needs"
mkdir -p "$ADDONS"
while read -r id; do
  case "$id" in ''|'#'*) continue ;; esac
  if [ -d "$ADDONS/$id" ]; then
    skip "$id already present"
    continue
  fi
  # The mirror lists every version; take the newest.
  file=$(curl -sfL "$MIRROR/$id/" | grep -oE "$id-[0-9][0-9a-zA-Z.+~-]*\.zip" \
         | sort -V | tail -1)
  if [ -z "$file" ]; then
    warn "could not find $id on the mirror; install it from Kodi's add-on browser"
    continue
  fi
  if curl -sfL -o /tmp/kodiaddon.zip "$MIRROR/$id/$file" &&
     unzip -qo /tmp/kodiaddon.zip -d "$ADDONS"; then
    ok "installed $file"
  else
    warn "could not install $id"
  fi
  rm -f /tmp/kodiaddon.zip
done < "$REPO/system/kodi-addons.txt"

# ------------------------------------------------------------- enable them ---
say "Enabling add-ons"
DB=$(ls -1 "$KODI/userdata/Database/"Addons*.db 2>/dev/null | sort | tail -1)
if [ -z "$DB" ]; then
  warn "Kodi has not run yet, so it has no add-on database."
  echo "         Start Kodi once, quit it, then run this again."
else
  python3 - "$DB" "$ADDONS" <<'PY'
import os, sqlite3, sys, time
db, addons_dir = sys.argv[1], sys.argv[2]
# ~/.kodi/addons also holds Kodi's own "packages" and "temp" working
# directories. An add-on is a directory with an addon.xml in it; anything else
# put in this database is a row Kodi will never understand.
ours = sorted(d for d in os.listdir(addons_dir)
              if os.path.isfile(os.path.join(addons_dir, d, "addon.xml")))
con = sqlite3.connect(db)
cur = con.cursor()
now = time.strftime("%Y-%m-%d %H:%M:%S")
changed = []
for addon in ours:
    row = cur.execute("select enabled from installed where addonID=?", (addon,)).fetchone()
    if row is None:
        cur.execute("insert into installed(addonID, enabled, installDate) values(?,1,?)",
                    (addon, now))
        changed.append(addon + " (added)")
    elif not row[0]:
        cur.execute("update installed set enabled=1, disabledReason=0 where addonID=?",
                    (addon,))
        changed.append(addon)
con.commit()
con.close()
print("   ok    %d add-ons already enabled, %d changed" % (len(ours) - len(changed), len(changed)))
for c in changed:
    print("           enabled %s" % c)
PY
fi

# ------------------------------------------------------------ the skin -------
say "The look"
if [ ! -d "$ADDONS/$SKIN" ]; then
  warn "$SKIN is not installed; leaving the skin alone"
elif [ ! -f "$GUISETTINGS" ]; then
  warn "no guisettings.xml yet; start Kodi once, quit, and run this again"
else
  python3 - "$GUISETTINGS" "$SKIN" "$FONT" <<'PY'
import re, sys
path, skin, font = sys.argv[1], sys.argv[2], sys.argv[3]
text = open(path, encoding="utf-8", errors="replace").read()
changed = []
for key, value in (("lookandfeel.skin", skin), ("lookandfeel.font", font)):
    pattern = r'(<setting id="%s"[^>]*>)([^<]*)(</setting>)' % re.escape(key)
    found = re.search(pattern, text)
    if found:
        if found.group(2) != value:
            # default="true" would make Kodi ignore what we set.
            head = found.group(1).replace(' default="true"', '')
            text = text[:found.start()] + head + value + found.group(3) + text[found.end():]
            changed.append(key)
    else:
        text = text.replace("</settings>",
                            '    <setting id="%s">%s</setting>\n</settings>' % (key, value))
        changed.append(key + " (added)")
open(path, "w", encoding="utf-8").write(text)
print("   ok    skin and font set" if changed else "   --    skin and font already set")
for c in changed:
    print("           %s" % c)
PY
fi

# ------------------------------------------------------- skin settings -------
say "Skin settings"
SKIN_CONF="$REPO/templates/skin-settings.conf"
SKIN_DATA="$KODI/userdata/addon_data/$SKIN"
if [ ! -f "$SKIN_CONF" ]; then
  skip "no skin settings template"
else
  mkdir -p "$SKIN_DATA"
  python3 - "$SKIN_DATA/settings.xml" "$SKIN_CONF" <<'PY'
import os, re, sys
path, conf = sys.argv[1], sys.argv[2]
try:
    text = open(path, encoding="utf-8", errors="replace").read()
except OSError:
    text = '<settings version="2">\n</settings>\n'
if "</settings>" not in text:
    text = '<settings version="2">\n</settings>\n'
changed = []
for line in open(conf, encoding="utf-8"):
    line = line.strip()
    if not line or line.startswith("#") or line.count("|") != 2:
        continue
    key, kind, value = line.split("|")
    pattern = r'<setting id="%s"[^>]*>[^<]*</setting>' % re.escape(key)
    new = '<setting id="%s" type="%s">%s</setting>' % (key, kind, value)
    if re.search(pattern, text):
        if new not in text:
            text = re.sub(pattern, new, text)
            changed.append(key)
    else:
        text = text.replace("</settings>", "    %s\n</settings>" % new)
        changed.append(key)
open(path, "w", encoding="utf-8").write(text)
print("   ok    %d skin settings applied" % len(changed) if changed
      else "   --    skin settings already applied")
for c in changed:
    print("           %s" % c)
PY
fi

say "Next"
cat <<'EOF2'
   Start Kodi. It should come up in the console skin with your games on the
   home menu. If the menu is empty, no ROMs have been found yet -- put some in
   ~/Games/emulation/ and run ~/.local/bin/sync_games.py.
EOF2
