"""Stop the HUDs belonging to one config, and their wrapper shells.

Kill targets are resolved by reading /proc and matching the config path the
HUD was started with -- never by picking the first hit of a name, which is how
a live JoyShockMapper got killed out from under a running game once.
"""
import os
import signal
import sys


def huds(config=None):
    """[(pid, ppid)] for running jsm-hud processes, optionally only those
    started with `config` in their arguments."""
    found = []
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            args = [a.decode() for a in
                    open("/proc/%s/cmdline" % pid, "rb").read().split(b"\0") if a]
            status = open("/proc/%s/status" % pid).read()
        except (OSError, UnicodeDecodeError):
            continue
        if not args:
            continue                     # kernel threads have no cmdline
        # Either launch form: `python3 .../jsm-hud ...` as the launcher starts
        # it, or `.../jsm-hud ...` straight off its shebang.
        script = None
        if args[0].endswith("jsm-hud"):
            script = args[0]
        elif len(args) > 1 and "python" in os.path.basename(args[0]) \
                and args[1].endswith("jsm-hud"):
            script = args[1]
        if script is None:
            continue
        if config is not None and config not in args:
            continue
        ppid = next((int(line.split()[1]) for line in status.splitlines()
                     if line.startswith("PPid:")), 0)
        found.append((int(pid), ppid))
    return sorted(found)


def stop(entries):
    for pid, ppid in entries:
        print("stopping HUD %d (wrapper %d)" % (pid, ppid))
        # The wrapper first, so it cannot restart the HUD as it dies.
        for target in (ppid, pid):
            if target <= 1:
                continue
            try:
                os.kill(target, signal.SIGTERM)
            except OSError:
                pass


if __name__ == "__main__":
    config = sys.argv[1] if len(sys.argv) > 1 else None
    entries = huds(config)
    if not entries:
        print("no HUD running for %s" % (config or "any config"))
    stop(entries)
