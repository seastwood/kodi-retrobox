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
  for tool in cmake clang++ git pkg-config; do
    command -v "$tool" >/dev/null || { warn "$tool is missing; run install.sh --with-optional first"; exit 1; }
  done
  for mod in gtk+-3.0 ayatana-appindicator3-0.1 libevdev hidapi-hidraw; do
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
  # Exactly what the original working build used: clang, RelWithDebInfo, and a
  # raised bracket depth (a clang-only flag) for the deeply nested macros.
  if ! cmake -S . -B build \
       -DCMAKE_BUILD_TYPE=RelWithDebInfo \
       -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++ \
       -DCMAKE_CXX_FLAGS=-fbracket-depth=2048 >/tmp/jsm-cmake.log 2>&1; then
    warn "cmake failed:"
    grep -iE "error|not found|required" /tmp/jsm-cmake.log | head -6 | sed 's/^/         /'
    echo "         full output in /tmp/jsm-cmake.log"
    exit 1
  fi
  if ! cmake --build build -j"$(nproc)" >/tmp/jsm-build.log 2>&1; then
    warn "the build failed:"
    grep -iE "error" /tmp/jsm-build.log | head -6 | sed 's/^/         /'
    echo "         full output in /tmp/jsm-build.log"
    exit 1
  fi
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

# --- permission to create a virtual keyboard and mouse ----------------------
# JoyShockMapper works by making a virtual input device, which needs write
# access to /dev/uinput. Without this it starts, prints "Failed to create
# virtual device: Permission denied", and then does nothing at all -- which
# looks like the controller not working rather than a permission problem.
RULE=/etc/udev/rules.d/50-joyshockmapper.rules
if [ ! -f "$RULE" ] && [ -f "$REPO/system/udev/50-joyshockmapper.rules" ]; then
  if sudo -n true 2>/dev/null || sudo -v; then
    sudo cp "$REPO/system/udev/50-joyshockmapper.rules" "$RULE"
    sudo udevadm control --reload-rules 2>/dev/null
    sudo udevadm trigger --subsystem-match=misc --sysname-match=uinput 2>/dev/null
    ok "installed the udev rule for /dev/uinput and controllers"
  else
    warn "could not install $RULE (needs sudo); JoyShockMapper will not be able"
    echo "         to create its virtual device until it is there"
  fi
fi
# uinput may be a module or built into the kernel, so ask whether the device
# exists rather than whether a module is loaded.
if [ ! -e /dev/uinput ]; then
  sudo modprobe uinput 2>/dev/null
  echo uinput | sudo tee /etc/modules-load.d/uinput.conf >/dev/null 2>&1
  [ -e /dev/uinput ] && ok "loaded uinput, and it will load at boot" ||
    warn "no /dev/uinput; JoyShockMapper cannot create its virtual device"
fi
# TAG+="uaccess" gives whoever is logged in at the seat access straight away;
# the group is the fallback for anything not running in that session.
if ! id -nG | tr " " "\n" | grep -qx input; then
  sudo usermod -aG input "$USER" 2>/dev/null &&
    ok "added you to the 'input' group (applies at next login; the udev rule"
  echo "         already grants access for this session)"
fi

# The ready-made mappings.
if [ -d "$REPO/assets/joyshockmapper" ]; then
  mkdir -p "$HOME/.config/JoyShockMapper"
  cp -rn "$REPO/assets/joyshockmapper/." "$HOME/.config/JoyShockMapper/" 2>/dev/null
  ok "$(find "$HOME/.config/JoyShockMapper" -type f | wc -l) mapping files in ~/.config/JoyShockMapper"
fi
ok "the CONTROLLER entry on the Kodi home menu edits these with a controller"
