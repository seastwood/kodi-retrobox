#!/bin/bash
# Build and install JoyShockMapper, which turns a controller into keyboard and
# mouse for PC games that have no pad support.
#
# Built from source rather than installed, because the Linux port needs
# patches: system/joyshockmapper/linux-fixes.patch against the upstream commit
# pinned beside it. Without them the Super key and action layers do not work.
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$HOME/.local/src/JoyShockMapper"
LIB="$HOME/.local/lib/joyshockmapper"
PATCH="$REPO/system/joyshockmapper/linux-fixes.patch"
PIN=$(cat "$REPO/system/joyshockmapper/upstream-commit.txt" 2>/dev/null)
UPSTREAM=https://github.com/JibbSmart/JoyShockMapper.git

ok()   { printf '   ok    %s\n' "$*"; }
skip() { printf '   --    %s\n' "$*"; }
warn() { printf '   WARN  %s\n' "$*"; }

if [ -x "$LIB/JoyShockMapper" ]; then
  skip "JoyShockMapper is already built"
else
  for tool in cmake g++ git pkg-config; do
    command -v "$tool" >/dev/null || { warn "$tool is missing; run install.sh --with-optional first"; exit 1; }
  done
  for mod in gtk+-3.0 ayatana-appindicator3-0.1 libevdev; do
    pkg-config --exists "$mod" || { warn "development files for $mod are missing"; exit 1; }
  done

  if [ ! -d "$SRC/.git" ]; then
    mkdir -p "$(dirname "$SRC")"
    git clone -q "$UPSTREAM" "$SRC" || { warn "could not clone JoyShockMapper"; exit 1; }
  fi
  cd "$SRC"
  git fetch -q --all 2>/dev/null || true
  if [ -n "$PIN" ]; then
    git checkout -q "$PIN" 2>/dev/null || warn "could not check out $PIN; building whatever is here"
  fi
  # Re-applying over an already-patched tree fails harmlessly; check first.
  if [ -f "$PATCH" ]; then
    if git apply --check "$PATCH" 2>/dev/null; then
      git apply "$PATCH" && ok "applied the Linux patches"
    else
      skip "patches already applied (or do not fit this revision)"
    fi
  fi
  cmake -S . -B build -DCMAKE_BUILD_TYPE=Release >/dev/null 2>&1 ||
    { warn "cmake failed"; exit 1; }
  cmake --build build -j"$(nproc)" >/dev/null 2>&1 ||
    { warn "the build failed; run it by hand in $SRC to see why"; exit 1; }
  BIN=$(find "$SRC/build" -name JoyShockMapper -type f -perm -u+x | head -1)
  [ -n "$BIN" ] || { warn "built, but no JoyShockMapper binary was produced"; exit 1; }
  mkdir -p "$LIB"
  cp "$BIN" "$LIB/JoyShockMapper"
  ok "built and installed $(du -h "$LIB/JoyShockMapper" | cut -f1)"
fi

# The launcher: JoyShockMapper looks for things relative to its own directory.
cat > "$HOME/.local/bin/joyshockmapper" <<'LAUNCH'
#!/bin/bash
# JoyShockMapper. Console app: type commands at its prompt, e.g. the full path
# of a config file to load it. Configs live in ~/.config/JoyShockMapper/
cd "$HOME/.local/lib/joyshockmapper" || exit 1
exec ./JoyShockMapper "$@"
LAUNCH
chmod +x "$HOME/.local/bin/joyshockmapper"

# The ready-made mappings.
if [ -d "$REPO/assets/joyshockmapper" ]; then
  mkdir -p "$HOME/.config/JoyShockMapper"
  cp -rn "$REPO/assets/joyshockmapper/." "$HOME/.config/JoyShockMapper/" 2>/dev/null
  ok "$(find "$HOME/.config/JoyShockMapper" -type f | wc -l) mapping files in ~/.config/JoyShockMapper"
fi
ok "the CONTROLLER entry on the Kodi home menu edits these with a controller"
