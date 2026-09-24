"""The password in front of Kodi's web server.

Kodi binds that listener to every interface and offers no setting to bind it
to one, so on a machine with the web server on, the password is the whole of
the distance between the network and full control of Kodi. The console's was
four characters -- chosen from the sofa with a controller, which is how they
get chosen.

Switching the server off is not available: pcgame_launch.py, script.joyshock
and the Steam and Moonlight add-ons all drive Kodi through JSON-RPC on it. But
none of them needs telling when the password changes, because every one of
them reads it out of guisettings.xml at the moment it calls -- and that is
worth a check of its own, because a hard-coded copy anywhere would turn this
fix into four broken add-ons.
"""
import importlib.machinery
import importlib.util
import os
import re
import stat
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
loader = importlib.machinery.SourceFileLoader(
    "ks", os.path.join(REPO, "install", "kodi-services.py"))
ks = importlib.util.module_from_spec(
    importlib.util.spec_from_loader("ks", loader))
loader.exec_module(ks)

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


def guisettings(**settings):
    body = "".join('    <setting id="%s">%s</setting>\n' % (k.replace("__", "."), v)
                   for k, v in settings.items())
    return '<settings version="2">\n%s</settings>\n' % body


print("a short password is replaced")
before = guisettings(services__webserver="true",
                     services__webserverauthentication="true",
                     services__webserverusername="retro",
                     services__webserverpassword="1234")
after, changed = ks.secure(before)
now = ks.read(after, "services.webserverpassword")
check(len(now) >= 24, "the new one is %d characters" % len(now))
check(now != "1234", "and is not the old one")
check(re.fullmatch(r"[A-Za-z0-9_-]+", now or ""),
      "made only of characters that need no escaping in HTTP Basic, in XML "
      "or on a phone keyboard, got %r" % now)
check(ks.read(after, "services.webserverusername") == "retro",
      "the username somebody chose is left alone")
check(len(changed) == 1, "and that is the only change, got %s" % changed)

print("\ntwo runs do not give the same answer")
one = ks.read(ks.secure(before)[0], "services.webserverpassword")
two = ks.read(ks.secure(before)[0], "services.webserverpassword")
check(one != two, "each machine gets its own, not one baked into the repository")

print("\na password that is already long is not touched")
kept = "a" * 40
after, changed = ks.secure(guisettings(services__webserver="true",
                                       services__webserverauthentication="true",
                                       services__webserverusername="kodi",
                                       services__webserverpassword=kept))
check(ks.read(after, "services.webserverpassword") == kept,
      "it stays, so running the install twice does not lock out a phone "
      "remote that was paired after the first")
check(changed == [], "and nothing is reported, got %s" % changed)

print("\nno password at all, and no authentication at all")
after, changed = ks.secure(guisettings(services__webserver="true",
                                       services__webserverauthentication="false"))
check(ks.read(after, "services.webserverauthentication") == "true",
      "authentication is switched on")
check(len(ks.read(after, "services.webserverpassword")) >= 24,
      "and there is something to authenticate with")
check(ks.read(after, "services.webserverusername") == "kodi",
      "with a username, since Kodi will not authenticate without one")

print("\na web server that is off is left entirely alone")
off = guisettings(services__webserver="false", services__webserverpassword="")
after, changed = ks.secure(off)
check(after == off and changed == [],
      "nothing is generated for a listener that does not exist")

print("\ndefault=\"true\" is taken off whatever is set")
# Kodi treats a setting still carrying that attribute as untouched and writes
# its own default straight back over it, so a password set without removing it
# is a password that silently is not there.
marked = ('<settings version="2">\n'
          '    <setting id="services.webserver">true</setting>\n'
          '    <setting id="services.webserverauthentication">true</setting>\n'
          '    <setting id="services.webserverusername">kodi</setting>\n'
          '    <setting id="services.webserverpassword" default="true"></setting>\n'
          '</settings>\n')
after, changed = ks.secure(marked)
line = [l for l in after.splitlines() if "webserverpassword" in l][0]
check('default="true"' not in line,
      "the attribute is gone, or Kodi would put its own default back: %s"
      % line.strip())
check(len(ks.read(after, "services.webserverpassword")) >= 24,
      "and the password is really in there")

print("\nthe file is written, once, and only when something changed")
tmp = tempfile.mkdtemp(prefix="kodiweb-")
path = os.path.join(tmp, "guisettings.xml")
open(path, "w").write(before)
check(ks.main([path, "24"]) == 0, "the script runs")
first = open(path).read()
check(len(ks.read(first, "services.webserverpassword")) >= 24,
      "and the file on disk has the long password")
ks.main([path, "24"])
check(open(path).read() == first,
      "a second run changes nothing, so the password is stable across "
      "installs")
check(ks.main([os.path.join(tmp, "not-here.xml"), "24"]) == 1,
      "a missing file is reported, not a traceback")

print("\nnothing that talks to the web server has the password written down")
# Changing the password is only safe because nothing carries a copy of it.
# Two quite different things drive Kodi through JSON-RPC here and only one of
# them is affected at all:
#
#   script.joyshock runs *inside* Kodi and calls xbmc.executeJSONRPC, which
#   never goes near the socket and needs no password -- so a copy of the
#   password in there would be a bug in itself.
#
#   pcgame_launch.py runs outside Kodi and has to go over HTTP, so it reads
#   the username and password out of guisettings.xml at the moment it calls.
#
# (The Steam and Moonlight add-ons live in their own repositories and read it
# the same way as pcgame_launch does; they cannot be checked from here.)
literal = re.compile(r'password["\']?\s*[:=]\s*["\'][^"\']{3,}["\']')

inside = os.path.join(REPO, "addons", "script.joyshock", "service.py")
if os.path.exists(inside):
    source = open(inside).read()
    check("xbmc.executeJSONRPC" in source,
          "script.joyshock calls Kodi from inside it, so the web server's "
          "password is nothing to do with it")
    check("webserverpassword" not in source,
          "and it does not read one")

outside = os.path.join(REPO, "bin", "pcgame_launch.py")
if os.path.exists(outside):
    source = open(outside).read()
    check("services.webserverpassword" in source,
          "pcgame_launch.py looks the password up by name, every time it "
          "calls, so a new one needs it told nothing")
    check(not literal.search(source),
          "and has no literal password in it")

print("\nthe Kodi settings a controller made obvious")
conf = os.path.join(REPO, "templates", "kodi-settings.conf")
check(os.path.exists(conf), "there is a template for them")
body = open(conf).read()
for key, why in (
        ("filelists.showparentdiritems",
         "the '..' row Kodi focuses on entry, so the first press of A goes "
         "back out instead of opening anything"),
        ("filelists.showaddsourcebuttons",
         "the 'Add games...' row, which opens a file dialog: a dead end from "
         "a sofa and one wrong press away")):
    check(key in body, "%s is set -- %s" % (key, why))
check(body.count("#") > 8,
      "and each one says why, because none of them is self-evident")

before = ('<settings version="2">\n'
          '    <setting id="filelists.showparentdiritems" default="true">true</setting>\n'
          '    <setting id="filelists.showextensions" default="true">true</setting>\n'
          '    <setting id="lookandfeel.skin">skin.aeon.nox.silvo</setting>\n'
          '</settings>\n')
after, changed = ks.apply_conf(before, conf)
check(ks.read(after, "filelists.showparentdiritems") == "false",
      "the parent-folder row is switched off")
check(ks.read(after, "filelists.showaddsourcebuttons") == "false",
      "and so is the add-source row, which was not in the file at all and "
      "had to be added")
check(ks.read(after, "lookandfeel.skin") == "skin.aeon.nox.silvo",
      "and nothing else in the file was touched")
line = [l for l in after.splitlines() if "showparentdiritems" in l][0]
check('default="true"' not in line,
      "default=\"true\" is gone, or Kodi writes its own default back over it")
check(len(changed) == 3, "three changes reported, got %s" % changed)

again, changed = ks.apply_conf(after, conf)
check(changed == [], "a second pass changes nothing, got %s" % changed)
check(again == after, "and rewrites nothing")

print("\nand the check that should have caught the file's mode")
sec = open(os.path.join(REPO, "install", "security-check.sh")).read()
check("6??|4??" not in sec,
      "664 is no longer accepted: Kodi writes guisettings.xml world-readable "
      "with the password in clear, and a pattern matching on the owner's "
      "digit passed exactly the file it existed to catch")
check("?00)" in sec, "only the owner may read it")
setup = open(os.path.join(REPO, "install", "kodi-setup.sh")).read()
check("chmod 600" in setup and "kodi-services.py" in setup,
      "and the install both sets the password and tightens the file")

print("\n(this machine's own Kodi, if it has one)")
mine = os.path.expanduser("~/.kodi/userdata/guisettings.xml")
if not os.path.exists(mine):
    print("  --   no Kodi here")
else:
    mode = stat.S_IMODE(os.stat(mine).st_mode)
    check(not mode & 0o077,
          "guisettings.xml is %o -- nobody else can read the password" % mode)

import shutil                                               # noqa: E402
shutil.rmtree(tmp, ignore_errors=True)

print()
if fails:
    print("FAILED: %d" % len(fails))
    for line in fails:
        print("  " + line)
    sys.exit(1)
print("test_kodiweb: all ok")
