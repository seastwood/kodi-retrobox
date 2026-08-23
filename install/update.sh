#!/bin/bash
# Update this console from GitHub and re-run the install.
#
#   install/update.sh [install.sh flags...]
#
# Your games, saves and settings are not in here -- they live in ~/Games,
# ~/.local/share/retroarch and ~/.kodi -- so an update only ever touches the
# definition.
#
# The one thing that needs care is a working tree that is not clean. An
# install from before the code stopped baking in a home directory left
# adopt.sh's rewrites in every tracked file, and those are not your edits: git
# will refuse to pull and blame you for changes you did not make. Rather than
# guess which is which, anything uncommitted is stashed -- nothing is lost,
# and the stash is named and reported so you can look at it or drop it.
set -u

REPO="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
cd "$REPO" || exit 1

say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok()   { printf '   ok    %s\n' "$*"; }
warn() { printf '   WARN  %s\n' "$*"; }

say "Where this is"
echo "   $REPO"
if ! git rev-parse --git-dir >/dev/null 2>&1; then
  warn "not a git clone; nothing to update from"
  exit 1
fi
echo "   at $(git log --oneline -1 2>/dev/null)"

say "Local changes"
STASHED=0
if [ -n "$(git status --porcelain)" ]; then
  STAMP="retrobox-update-$(date +%Y-%m-%d_%H%M%S)"
  if git stash push -u -q -m "$STAMP"; then
    STASHED=1
    ok "stashed as \"$STAMP\" (git stash list, git stash pop to bring back)"
  else
    warn "could not stash; fix the working tree and run this again"
    exit 1
  fi
else
  ok "working tree is clean"
fi

say "Fetching"
if git pull --ff-only 2>&1 | sed 's/^/   /'; then
  ok "now at $(git log --oneline -1)"
else
  warn "pull failed"
  [ "$STASHED" = 1 ] && warn "your changes are still in the stash"
  exit 1
fi

say "Installing"
exec "$REPO/install/install.sh" "$@"
