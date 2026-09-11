"""The settings the resume machinery needs are actually in the template.

ra_players.py carries a game across a restart -- ask RetroArch to save, close
it, start it again, load it back -- and every step of that leans on a setting
in retroarch.cfg. Nothing connected the two. The template set
savestate_auto_save and network_cmd_enable and stopped there, so the pieces it
did not know about were left at RetroArch's defaults.

One of those defaults is log_verbosity, which ships off. The picker waits for
RetroArch to print `bringing_up_command_interface` before it sends anything,
because asking a running game instead used to segfault it. With logging off
that line is never printed, the launch log stays empty, and after forty-five
seconds the picker decides the game never came up -- so it never sends the
LOAD_STATE. Repicking player slots restarted the game from the beginning every
single time, on a machine where everything else was configured correctly, and
the carried save sat on disk unread.

So the dependency is written down here instead of being implied.
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
TEMPLATE = os.path.join(REPO, "templates", "retroarch-settings.conf")
PICKER = os.path.join(REPO, "bin", "ra_players.py")

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


settings = {}
with open(TEMPLATE, encoding="utf-8") as handle:
    for line in handle:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        settings[key.strip()] = value.strip().strip('"')

picker = open(PICKER, encoding="utf-8").read()

print("what the picker reads out of the emulator's own log")
# If the marker ever changes, this says so rather than letting the setting
# that makes it printable quietly stop mattering.
found = re.search(r'UP_MARKER = "([^"]+)"', picker)
check(found is not None, "ra_players.py still waits for a marker in the log")
if found:
    check(found.group(1) == "bringing_up_command_interface",
          "and it is the one RetroArch prints at INFO: " + found.group(1))

print("\nso the template must make RetroArch print it")
check(settings.get("log_verbosity") == "true",
      "log_verbosity is on -- RetroArch ships it off and prints no INFO "
      "lines at all without it, which is an empty launch log and a resume "
      "that can never happen")
check(settings.get("log_to_file") == "false",
      "and the log goes to stdout, which is what the picker captures -- a "
      "RetroArch logging to its own file says nothing into it")
level = settings.get("frontend_log_level")
check(level is not None and int(level) <= 1,
      "at a level that includes INFO (0 debug, 1 info, 2 warning): %s" % level)

print("\nand the rest of what carrying a game across a restart needs")
check(settings.get("network_cmd_enable") == "true",
      "the command interface is on, or SAVE_STATE and LOAD_STATE go nowhere")
check(settings.get("savestate_auto_save") == "true",
      "closing a game writes where you got to")
check(settings.get("savestate_auto_load") == "true",
      "and opening it reads that back")
check(settings.get("config_save_on_exit") == "false",
      "a game cannot write its launch fragment back into retroarch.cfg, "
      "which is how one fresh start once disabled saving for every game after")

print("\nand a game that is killed rather than closed still keeps its cartridge")
interval = settings.get("autosave_interval")
check(interval is not None and 0 < int(interval) <= 60,
      "SRAM is flushed while the game runs, not only when it closes: %s"
      % interval)
check(settings.get("block_sram_overwrite") == "false",
      "and RetroArch is allowed to write it")

print()
if fails:
    print("FAILURES: %d" % len(fails))
    sys.exit(1)
print("test_resumecfg: all ok")
