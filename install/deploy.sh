#!/bin/bash
# Put this repository's code where the system expects to find it.
#
# Idempotent, and safe to run on a machine that already has an older copy: an
# existing real file is moved aside with a .replaced suffix rather than being
# destroyed, so a botched deploy can always be undone by hand.
set -u
R="$(cd "$(dirname "$0")/.." && pwd)"

link() {   # link <repo path> <live path>
  local src="$1" dst="$2"
  [ -e "$src" ] || return 0
  mkdir -p "$(dirname "$dst")"
  if [ -L "$dst" ]; then
    [ "$(readlink -f "$dst")" = "$(readlink -f "$src")" ] && return 0
    rm -f "$dst"
  elif [ -e "$dst" ]; then
    mv "$dst" "$dst.replaced.$(date +%s)"
    echo "  kept the old $dst as $dst.replaced.*"
  fi
  ln -s "$src" "$dst"
  echo "  linked $dst"
}

for f in "$R"/bin/*; do
  # adopt.sh byte-compiles what it rewrites, which leaves a __pycache__ behind.
  case "$(basename "$f")" in __pycache__|*.pyc) continue ;; esac
  link "$f" "$HOME/.local/bin/$(basename "$f")"
done
for a in "$R"/addons/*; do
  link "$a" "$HOME/.kodi/addons/$(basename "$a")"
done
for l in "$R"/lib/*; do
  # Shared python the HUD and the Kodi controller editor both import.
  [ -e "$l" ] && link "$l" "$HOME/.local/lib/$(basename "$l")"
done
link "$R/tests" "$HOME/.local/share/gametests"
mkdir -p "$HOME/.config/systemd/user"
for u in "$R"/system/systemd/*; do
  [ -e "$u" ] && install -m644 "$u" "$HOME/.config/systemd/user/$(basename "$u")" \
    && echo "  installed $(basename "$u")"
done
echo "deployed from $R"
