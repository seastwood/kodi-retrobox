#!/usr/bin/env python3
"""Give Kodi's web server a password worth having.

    install/kodi-services.py <guisettings.xml> [minimum length]

Run with Kodi closed: it rewrites the file Kodi has open, and Kodi writes that
file back out from memory when it quits.

The web server is not optional on this console. pcgame_launch.py,
script.joyshock and the Steam and Moonlight add-ons all drive Kodi through
JSON-RPC on it, so switching it off is not the fix -- and it needs no telling
when the password changes, because every one of them reads the password out of
guisettings.xml at the moment it calls.

What the password has to be is long. Kodi binds this listener to every
interface and offers no setting to bind it to one, so on a machine with the
web server on, that password is the whole of the distance between the network
and full control of Kodi: playing anything, reading the library, running any
add-on. The console had a four-character one, chosen from the sofa with a
controller, which is how they get chosen and why this does not leave it to a
person.

Generated rather than carried in the repository: a password in the repository
is a password every machine installed from it shares. install/capture.sh
already redacts this from the published copy and writes the real one to
secrets/values.txt, which is git-ignored and carried by the backup.
"""
import re
import secrets
import sys

# Long enough that guessing it over the network is not a plan. 24 bytes of
# urlsafe base64 is 32 characters.
DEFAULT_MINIMUM = 24


def read(text, key):
    """One setting's value, or "" if the file does not mention it."""
    found = re.search(r'<setting id="%s"[^>]*>([^<]*)</setting>' % re.escape(key),
                      text)
    return found.group(1) if found else ""


def write(text, key, value):
    """Set one setting and return the new document.

    default="true" is dropped from the tag: Kodi treats a setting still
    carrying it as untouched and writes its own default straight back over
    whatever is between the tags.
    """
    pattern = r'(<setting id="%s"[^>]*>)([^<]*)(</setting>)' % re.escape(key)
    found = re.search(pattern, text)
    if found:
        head = found.group(1).replace(' default="true"', '')
        return text[:found.start()] + head + value + found.group(3) + text[found.end():]
    return text.replace("</settings>",
                        '    <setting id="%s">%s</setting>\n</settings>'
                        % (key, value))


def secure(text, least=DEFAULT_MINIMUM, make=secrets.token_urlsafe):
    """Return (new document, what changed) for the web server's settings.

    `make` is an argument so a test can watch what gets generated rather than
    guess at it.
    """
    if read(text, "services.webserver") != "true":
        return text, []
    changed = []
    if read(text, "services.webserverauthentication") != "true":
        text = write(text, "services.webserverauthentication", "true")
        changed.append("authentication switched on")
    if not read(text, "services.webserverusername"):
        text = write(text, "services.webserverusername", "kodi")
        changed.append("username set")
    current = read(text, "services.webserverpassword")
    if len(current) < least:
        # token_urlsafe is A-Za-z0-9_- : safe in HTTP Basic, safe between XML
        # tags without escaping, and safe to type into a phone remote.
        text = write(text, "services.webserverpassword", make(least))
        changed.append("a %d-character password generated (it was %d)"
                       % (len(read(text, "services.webserverpassword")),
                          len(current)))
    return text, changed


def main(argv):
    if not argv:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    path = argv[0]
    least = int(argv[1]) if len(argv) > 1 else DEFAULT_MINIMUM
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError as err:
        print("   WARN  could not read %s: %s" % (path, err))
        return 1
    new, changed = secure(text, least)
    if read(text, "services.webserver") != "true":
        print("   --    the web server is off, so it has nothing to guard")
        return 0
    if not changed:
        print("   --    the web server already has a password of at least "
              "%d characters" % least)
        return 0
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(new)
    print("   ok    web server secured")
    for line in changed:
        print("           %s" % line)
    print("           install/capture.sh writes it to secrets/values.txt")
    print("           (git-ignored, mode 600) if you need to read it")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
