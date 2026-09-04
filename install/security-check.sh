#!/bin/bash
# What this machine is offering the network, and to whom.
#
# Written because the answer changes without anybody deciding it should: a
# setting enabled once from the sofa to try something, a service that starts
# listening after an update, a password chosen when the box lived behind one
# router and never revisited when it moved. None of that shows up in the
# repository, so none of it is caught by anything else here.
#
# It reports and does not change anything. Several of the things it can find
# are deliberate -- somebody may well want the Kodi web server on so a phone
# remote can reach it -- and a script that switched those off on its own would
# be worse than the exposure.
#
# Read it as: FAIL is worth fixing today, WARN is worth a decision.
set -u

say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok()   { printf '   ok    %s\n' "$*"; }
skip() { printf '   --    %s\n' "$*"; }
warn() { printf '   WARN  %s\n' "$*"; WARNED=$((WARNED+1)); }
bad()  { printf '   FAIL  %s\n' "$*"; FAILED=$((FAILED+1)); }
FAILED=0
WARNED=0

# sshd's effective configuration and /etc/sudoers.d are both root-only. Read
# without them, this script reports "nothing found" for checks that never
# ran, which is the most misleading thing a security check can do.
PRIVILEGED=0
if [ "$(id -u)" = 0 ] || sudo -n true 2>/dev/null; then
  PRIVILEGED=1
else
  printf '\n\033[1m== Note\033[0m\n'
  printf '   Not running as root, so the SSH and passwordless-sudo checks\n'
  printf '   cannot run. Re-run with: sudo %s\n' "$0"
fi

# The console's own user, not whoever invoked this. Half these checks read
# files under that account, and run through sudo they were reading root's
# empty home and reporting "Kodi has not written its settings yet" about a
# machine that plainly had.
WHO="${SUDO_USER:-$(id -un)}"
WHO_HOME=$(getent passwd "$WHO" | cut -d: -f6)
WHO_HOME="${WHO_HOME:-$HOME}"

KODI_SETTINGS="$WHO_HOME/.kodi/userdata/guisettings.xml"

kodi_setting() {  # kodi_setting <id> -- prints the value, empty if unset
  # Kodi writes both <setting id="x">v</setting> and
  # <setting id="x" default="true">v</setting>, so the attributes have to be
  # allowed for. Matching only the first form read every defaulted setting as
  # empty -- which reported a web server that has a password as having none.
  [ -f "$KODI_SETTINGS" ] || return 0
  sed -n "s|.*<setting id=\"$1\"[^>]*>\([^<]*\)</setting>.*|\1|p" \
    "$KODI_SETTINGS" 2>/dev/null | head -1
}

say "Who can log in over the network"
if command -v sshd >/dev/null 2>&1 && systemctl is-active --quiet ssh 2>/dev/null; then
  conf=$([ "$PRIVILEGED" = 1 ] && sudo -n sshd -T 2>/dev/null)
  if [ -z "$conf" ]; then
    warn "sshd is running and its settings could not be read without root."
    warn "  Re-run with sudo: this is the check most worth having."
  else
    if echo "$conf" | grep -qx "passwordauthentication yes"; then
      # The account password on these machines tends to be short, because it
      # is typed on a television with a controller. That is a fair trade for
      # a local login and a poor one for anything reachable from a network.
      bad "SSH accepts passwords. Anything that can reach port 22 can guess at"
      bad "  them. Fix: put your public key in ~/.ssh/authorized_keys, then set"
      bad "  PasswordAuthentication no in /etc/ssh/sshd_config.d/ and reload ssh."
    else
      ok "SSH accepts keys only"
    fi
    if echo "$conf" | grep -qx "permitrootlogin yes"; then
      bad "root can log in over SSH with a password"
    else
      ok "root cannot log in with a password"
    fi
  fi
else
  ok "no SSH server is running"
fi

say "What is listening beyond this machine"
# Anything not bound to a loopback address is reachable by the rest of the
# network -- and, if the router forwards it, by more than that.
listening=$(ss -tulnH 2>/dev/null | awk '{print $1, $5, $7}' \
  | grep -vE '(^| )127\.[0-9.]+(%[a-z0-9]+)?:|\[::1\]:|%lo:|\[fe80:|239\.' \
  | sort -u)
if [ -z "$listening" ]; then
  ok "nothing is listening outside this machine"
else
  printf '%s\n' "$listening" | while read -r proto addr rest; do
    port="${addr##*:}"
    case "$port" in
      22)    printf '   --    %s  ssh (see above)\n' "$addr" ;;
      8443)  printf '   ok    %s  fourth-player, over TLS with a PIN\n' "$addr" ;;
      8080)  printf '   --    %s  Kodi web server (see below)\n' "$addr" ;;
      1900|3702|5353|5355)
             printf '   --    %s  discovery (SSDP/mDNS)\n' "$addr" ;;
      47984|47989|48010|47998|47999|48000)
             printf '   --    %s  Sunshine, which pairs with its own PIN\n' "$addr" ;;
      47990) printf '   --    %s  Sunshine web interface, which has its own login\n' "$addr" ;;
      36666) printf '   --    %s  Kodi AirPlay (see below)\n' "$addr" ;;
      *)     printf '   WARN  %s  %s -- worth knowing what this is\n' "$addr" "$rest" ;;
    esac
  done
fi

say "The firewall"
if command -v ufw >/dev/null 2>&1; then
  # `systemctl is-active ufw` says "active" for the unit even when the
  # firewall itself is switched off, which reads as protection that is not
  # there. Ask ufw, not systemd.
  if sudo -n ufw status 2>/dev/null | grep -qi "^Status: active"; then
    ok "ufw is on"
  elif ufw status 2>/dev/null | grep -qi "^Status: active"; then
    ok "ufw is on"
  else
    warn "no firewall. On a machine that only ever sits behind a home router"
    warn "  that may be fine; on a laptop that joins other networks it is not."
    warn "  Fix: sudo ufw default deny incoming, allow the ports listed above"
    warn "  that you actually use, then sudo ufw enable."
  fi
else
  warn "ufw is not installed, so nothing is filtering incoming connections"
fi

say "Kodi's own services"
if [ ! -f "$KODI_SETTINGS" ]; then
  skip "Kodi has not written its settings yet"
else
  if [ "$(kodi_setting services.webserver)" = "true" ]; then
    pass=$(kodi_setting services.webserverpassword)
    auth=$(kodi_setting services.webserverauthentication)
    port=$(kodi_setting services.webserverport)
    if [ "$auth" != "true" ]; then
      bad "the Kodi web server is on with no password at all (port ${port:-8080})"
    elif [ "${#pass}" -lt 12 ]; then
      # It listens on every interface and Kodi offers no way to bind it to
      # one, so the password is the whole of the protection.
      bad "the Kodi web server's password is ${#pass} characters (port ${port:-8080})."
      bad "  It listens on every interface and cannot be told not to, so that"
      bad "  password is all that stands in front of full control of Kodi."
      bad "  Fix: Settings > Services > Control, set a long one."
    else
      ok "the Kodi web server has a password of ${#pass} characters"
    fi
  else
    ok "the Kodi web server is off"
  fi

  if [ "$(kodi_setting services.airplay)" = "true" ] \
     && [ "$(kodi_setting services.useairplaypassword)" != "true" ]; then
    warn "AirPlay is on with no password: anyone on this network can put"
    warn "  something on the television. Fix: Settings > Services > AirPlay."
  else
    ok "AirPlay is off, or has a password"
  fi

  if [ "$(kodi_setting services.esenabled)" = "true" ]; then
    # The event server takes button presses and keystrokes with no
    # authentication of any kind, which is why where it listens is the whole
    # question. kodi-send needs it, so switching it off is not the answer.
    if ss -ulnH 2>/dev/null | grep -qE '(^|[^0-9])127\.0\.0\.1:9777'; then
      ok "the remote-control service listens only to this machine"
    elif ss -ulnH 2>/dev/null | grep -qE ':9777'; then
      bad "the remote-control service is reachable from the network, and it"
      bad "  authenticates nothing. Fix: Settings > Services > Control, turn"
      bad "  off 'Allow remote control from applications on other systems'."
    else
      ok "the remote-control service is not listening"
    fi
  fi
fi

say "Files that hold credentials"
for f in "$WHO_HOME/.local/state/fourth-player/cert/server.key" \
         "$WHO_HOME/.config/sunshine/credentials/cakey.pem" \
         "$WHO_HOME/retro-console/secrets/values.txt"; do
  [ -e "$f" ] || continue
  mode=$(stat -c %a "$f")
  case "$mode" in
    600|400) ok "${f#$WHO_HOME/} is $mode" ;;
    *) bad "${f#$WHO_HOME/} is $mode -- it should be 600. Fix: chmod 600 '$f'" ;;
  esac
done
if [ -f "$KODI_SETTINGS" ]; then
  # Kodi stores the web server password here in the clear; that is Kodi's
  # design and cannot be changed, so the file's mode is what matters.
  mode=$(stat -c %a "$KODI_SETTINGS")
  case "$mode" in
    6??|4??) ok "guisettings.xml is $mode" ;;
    *) warn "guisettings.xml is $mode and holds the web server password in clear" ;;
  esac
fi

say "Passwordless root"
# A NOPASSWD rule is only as good as the file it names: if the user can edit
# the script, the rule hands them root outright.
found=0
for f in /etc/sudoers.d/*; do
  [ -e "$f" ] || continue
  [ "$PRIVILEGED" = 1 ] || continue
  rules=$(sudo -n cat "$f" 2>/dev/null | grep -E "NOPASSWD" | grep -v "^#")
  [ -z "$rules" ] && continue
  found=1
  printf '%s\n' "$rules" | grep -oE '/[^ ,]+' | sort -u | while read -r target; do
    [ -e "$target" ] || continue
    # Not `test -w`: run through sudo that is asked of root, who can write
    # anything, and every rule here came back as a way to become root. The
    # bits give the same answer whoever is asking.
    owner=$(stat -c %U "$target")
    perms=$(stat -c %A "$target")
    group_w=$(printf '%s' "$perms" | cut -c6)
    other_w=$(printf '%s' "$perms" | cut -c9)
    if [ "$owner" != "root" ]; then
      bad "$(basename "$f"): $target runs as root but is owned by $owner,"
      bad "  so $owner can replace it and become root"
    elif [ "$other_w" = "w" ] || [ "$group_w" = "w" ]; then
      bad "$(basename "$f"): $target runs as root and is $perms -- writable by"
      bad "  more than root, which is root for the asking"
    else
      ok "$(basename "$f"): $target is root-owned, $perms"
    fi
  done
done
if [ "$found" = 0 ]; then
  if [ "$PRIVILEGED" = 1 ]; then
    ok "no passwordless sudo rules"
  else
    warn "could not read /etc/sudoers.d without root, so this was not checked"
  fi
fi

say "Result"
if [ "$FAILED" -gt 0 ]; then
  printf '   %d to fix, %d to decide about\n' "$FAILED" "$WARNED"
  exit 1
fi
if [ "$WARNED" -gt 0 ]; then
  printf '   nothing broken; %d thing(s) worth a decision\n' "$WARNED"
  exit 0
fi
printf '   nothing to report\n'
