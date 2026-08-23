#!/bin/bash
# Adapt the repository to this machine's home directory.
#
# The code was written on a machine whose user is `retro`, and absolute paths
# are baked in throughout -- 53 of them across 16 files. That is fine on the
# machine it grew up on and fatal anywhere else, so this rewrites them once,
# before install.sh runs.
#
#   install/adopt.sh            adopt to $HOME
#   install/adopt.sh /home/bob  adopt to a specific home
#   install/adopt.sh --check    report what would change and exit
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
NEW="${1:-$HOME}"
CHECK=0
[ "$NEW" = "--check" ] && { CHECK=1; NEW="$HOME"; }
NEW="${NEW%/}"

# system/home.txt says which home the code points at. Fall back to reading it
# out of the source only if that file is missing.
if [ -s "$REPO/system/home.txt" ]; then
  OLD=$(head -1 "$REPO/system/home.txt")
else
  OLD=$(grep -rhoE '/home/[a-z_][a-z0-9_-]*' "$REPO/bin" "$REPO/addons" 2>/dev/null \
        | sort | uniq -c | sort -rn | awk 'NR==1{print $2}')
fi
OLD="${OLD%/}"
if [ -z "$OLD" ]; then
  echo "no absolute home path found in the code; nothing to adopt"
  exit 0
fi
if [ "$OLD" = "$NEW" ]; then
  echo "nothing to adopt: this machine is $NEW, which is what the repository"
  echo "is written for"
  exit 0
fi

# Every text file that mentions the old home, found by content rather than by
# extension: jsm-hud and osk-toggle have no extension at all, and an
# extension list silently skipped them while still reporting success.
# -I skips binaries, so the font and the icons are left alone. system/home.txt
# is excluded on purpose: it records what the repository is written for.
# Every text file that mentions the old home, found by content rather than by
# extension: jsm-hud and osk-toggle have no extension at all, and an extension
# list silently skipped them while still reporting success. -I skips binaries,
# so the font and the icons are left alone, and system/home.txt is excluded
# because it records what the repository is written for.
#
# NUL-separated throughout: playlists are named "Sega - Mega-CD - Sega CD.lpl"
# and an unquoted list of those splits into fragments, one of which is "-" --
# which grep reads as "take input from stdin" and waits there for ever.
LIST=$(mktemp)
trap 'rm -f "$LIST"' EXIT
grep -rlIZE "$(printf '%s' "$OLD" | sed -e 's/[][\.*^$|&/]/\\&/g')([^A-Za-z0-9_.-]|\$)" "$REPO" \
     --exclude-dir=.git --exclude-dir=__pycache__ --exclude=home.txt \
     2>/dev/null > "$LIST" || true

count=$(tr -cd '\0' < "$LIST" | wc -c)
hits=$(xargs -0 -r grep -ohE "$(printf '%s' "$OLD" | sed -e 's/[][\.*^$|&/]/\\&/g')([^A-Za-z0-9_.-]|\$)" < "$LIST" 2>/dev/null | wc -l)

echo "baked-in home : $OLD"
echo "this machine  : $NEW"
echo "files         : $count"
echo "occurrences   : $hits"

if [ "$CHECK" = 1 ]; then
  xargs -0 -r -n1 echo < "$LIST" | sed 's|^|   |'
  exit 0
fi
[ "$count" -eq 0 ] && { echo "nothing to do"; exit 0; }

# The replacement has to stop at a path-name boundary. /home/retro is a
# prefix of /home/retro2, so a plain s|OLD|NEW|g rewrites an already-adopted
# path a second time and turns /home/retro2 into /home/retro22 -- and since
# install.sh adopts on every run, that compounds: retro222, retro2222. Match
# OLD only when what follows it cannot be part of a longer user name.
TAIL='[^A-Za-z0-9_.-]'
esc() { printf '%s' "$1" | sed -e 's/[][\.*^$|&/]/\\&/g'; }
OLD_RE=$(esc "$OLD")
NEW_RE=$(esc "$NEW")
xargs -0 -r sed -i -E "s|${OLD_RE}(${TAIL})|${NEW_RE}\1|g; s|${OLD_RE}\$|${NEW_RE}|g" < "$LIST"

# Count what is genuinely left, using the same boundary: bare "grep -o $OLD"
# would report every /home/retro2 as an unconverted /home/retro.
left=$(xargs -0 -r grep -ohE "${OLD_RE}(${TAIL}|\$)" < "$LIST" 2>/dev/null | wc -l)
# system/home.txt deliberately keeps saying which home the *repository* is
# written for. Rewriting it to this machine made adopt.sh a one-shot, so any
# file pulled in later kept the original paths and failed at run time with
# nothing to explain why.
echo "rewritten; $left occurrences left"

# A syntax check on everything touched, because a bad rewrite must not be
# discovered later by a game failing to launch.
bad=0
while IFS= read -r -d '' f; do
  case "$f" in
    *.py) python3 -m py_compile "$f" 2>/dev/null || { echo "   BROKEN $f"; bad=1; } ;;
    *.sh) bash -n "$f" 2>/dev/null || { echo "   BROKEN $f"; bad=1; } ;;
  esac
done < "$LIST"
[ "$bad" = 0 ] && echo "all rewritten files still parse" || echo "SOME FILES ARE BROKEN"
echo
echo "Now run install/install.sh, and commit the rewrite if it is a permanent move."
exit $bad
