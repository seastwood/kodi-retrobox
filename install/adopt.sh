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

files=$(grep -rl "$OLD" "$REPO" \
        --include='*.py' --include='*.sh' --include='*.service' \
        --include='*.timer' --include='*.desktop' --include='*.md' \
        --include='*.json' --include='*.conf' --include='*.example' \
        --include='*.xml' 2>/dev/null \
        | grep -v '/\.git/')
count=$(printf '%s\n' $files | grep -c . || true)
hits=$(grep -rho "$OLD" $files 2>/dev/null | wc -l)

echo "baked-in home : $OLD"
echo "this machine  : $NEW"
echo "files         : $count"
echo "occurrences   : $hits"

if [ "$CHECK" = 1 ]; then
  printf '%s\n' $files | sed 's|^|   |'
  exit 0
fi
[ "$count" -eq 0 ] && { echo "nothing to do"; exit 0; }

# shellcheck disable=SC2086
sed -i "s|$OLD|$NEW|g" $files
# /home/retro2 contains /home/retro, so a plain count of the old path finds
# every new one too and reports a rewrite that worked as having failed.
left=$(grep -rho "$OLD" $files 2>/dev/null | wc -l)
case "$NEW" in
  "$OLD"*) left=$(( left - $(grep -rho "$NEW" $files 2>/dev/null | wc -l) )) ;;
esac
[ "$left" -lt 0 ] && left=0
# system/home.txt deliberately keeps saying which home the *repository* is
# written for. Rewriting it to this machine made adopt.sh a one-shot, so any
# file pulled in later kept the original paths and failed at run time with
# nothing to explain why.
echo "rewritten; $left occurrences left"

# A syntax check on everything touched, because a bad rewrite must not be
# discovered later by a game failing to launch.
bad=0
for f in $files; do
  case "$f" in
    *.py) python3 -m py_compile "$f" 2>/dev/null || { echo "   BROKEN $f"; bad=1; } ;;
    *.sh) bash -n "$f" 2>/dev/null || { echo "   BROKEN $f"; bad=1; } ;;
  esac
done
[ "$bad" = 0 ] && echo "all rewritten files still parse" || echo "SOME FILES ARE BROKEN"
echo
echo "Now run install/install.sh, and commit the rewrite if it is a permanent move."
exit $bad
