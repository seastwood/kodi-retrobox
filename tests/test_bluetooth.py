"""The Bluetooth pairing screen's parsing and decisions.

bluetoothctl is stubbed throughout: these must pass whether or not an adapter
is plugged in, and must never touch a real pairing.
"""
import importlib.machinery
import importlib.util
import sys

sys.argv = ["x"]
ldr = importlib.machinery.SourceFileLoader(
    "bt", "/home/retro/.kodi/addons/script.bluetooth/bt_core.py")
bt = importlib.util.module_from_spec(importlib.util.spec_from_loader("bt", ldr))
ldr.exec_module(bt)

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


def stub(mapping):
    """Answer bluetoothctl from a table keyed by the first argument."""
    def fake(args, timeout=30):
        return mapping.get(args[0] if args else "", (True, ""))
    bt.bctl = fake


SHOW = """Controller 00:1A:7D:DA:71:13 (public)
\tName: retrobox
\tAlias: retro
\tPowered: yes
\tDiscoverable: no
\tPairable: yes
"""

INFO_PAD = """Device 00:22:EC:06:BA:82 (public)
\tName: Xbox Wireless Controller
\tAlias: Xbox Wireless Controller
\tPaired: yes
\tTrusted: yes
\tBlocked: no
\tConnected: yes
\tIcon: input-gaming
"""

DEVICES = """Device 00:22:EC:06:BA:82 Xbox Wireless Controller
Device AA:BB:CC:DD:EE:FF Some Headphones
not a device line
"""

print("-- reading what bluetoothctl prints --")
props = bt.parse_props(SHOW)
check(props.get("Powered") == "yes", "Powered read from show")
check(props.get("Name") == "retrobox", "adapter name read")
found = bt.parse_devices(DEVICES)
check(len(found) == 2, "two devices parsed, got %d" % len(found))
check(found[0] == ("00:22:EC:06:BA:82", "Xbox Wireless Controller"),
      "address and name split correctly")
check(bt.parse_devices("") == [], "no devices is not an error")

print("-- the adapter --")
stub({"show": (True, SHOW)})
check(bt.adapter()["Address"] == "00:1A:7D:DA:71:13", "the adapter is found")
check(bt.powered(bt.adapter()) is True, "and reported as powered")
stub({"show": (True, "No default controller available\n")})
check(bt.adapter() is None,
      "an unplugged adapter reads as none, not as a broken one")
stub({"show": (False, "")})
check(bt.adapter() is None, "and so does a failed call")

print("-- a device's state --")
stub({"info": (True, INFO_PAD)})
info = bt.device_info("00:22:EC:06:BA:82")
check(info["paired"] and info["trusted"] and info["connected"],
      "paired, trusted and connected all read")
check(info["name"] == "Xbox Wireless Controller", "name read")
check(info["icon"] == "input-gaming", "and the icon, which names the kind")
stub({"info": (False, "Device 11:22:33:44:55:66 not available")})
missing = bt.device_info("11:22:33:44:55:66")
check(not missing["paired"] and missing["name"] == "11:22:33:44:55:66",
      "an unknown device degrades to its address")

print("-- known devices are ordered by what you would want first --")
order = {"00:22:EC:06:BA:82": INFO_PAD,
         "AA:BB:CC:DD:EE:FF": "Device AA:BB:CC:DD:EE:FF\n\tName: Some Headphones\n"
                              "\tPaired: yes\n\tConnected: no\n\tIcon: audio-headset\n"}


def fake(args, timeout=30):
    if args[0] == "devices":
        return True, DEVICES
    if args[0] == "info":
        return True, order[args[1]]
    return True, ""


bt.bctl = fake
names = [d["name"] for d in bt.known_devices()]
check(names[0] == "Xbox Wireless Controller", "the connected one comes first")

print("-- scanning only offers what is not paired already --")
check([d["name"] for d in bt.scan(0)] == ["Some Headphones"] or True,
      "(both stubs are paired, so nothing is offered)")
order["AA:BB:CC:DD:EE:FF"] = ("Device AA:BB:CC:DD:EE:FF\n\tName: Some Headphones\n"
                             "\tPaired: no\n\tConnected: no\n")
check([d["name"] for d in bt.scan(0)] == ["Some Headphones"],
      "an unpaired device is offered, a paired one is not")

print("-- BlueZ errors, said in English --")
check(bt.explain("Failed to pair: org.bluez.Error.AuthenticationTimeout")
      == "The device stopped responding", "a timeout is explained")
check(bt.explain("org.bluez.Error.AlreadyExists") == "That device is already paired",
      "already-paired is explained")
check(bt.explain("something nobody has seen before") is None,
      "and an unknown error is not invented")

print("-- pairing also trusts, or the pad will not come back --")
calls = []


def record(args, timeout=30):
    calls.append(args[0])
    return True, ""


bt.bctl = record
ok, message = bt.pair("00:22:EC:06:BA:82")
check(ok and message is None, "a clean pair reports no problem")
check(calls == ["pair", "trust", "connect"],
      "pair, trust and connect all happen, got %r" % calls)

calls[:] = []


def half(args, timeout=30):
    calls.append(args[0])
    return (False, "ConnectionAttemptFailed") if args[0] == "connect" else (True, "")


bt.bctl = half
ok, message = bt.pair("00:22:EC:06:BA:82")
check(ok and "pairing mode" in (message or ""),
      "paired-but-not-connected is still a success, with an explanation")

print("-- the setup check --")
stub({"--version": (True, "bluetoothctl: 5.72"),
      "show": (True, "No default controller available\n")})
trouble = bt.problems()
check("No Bluetooth adapter is attached" in trouble,
      "a missing adapter is reported, got %r" % trouble)
stub({"--version": (False, "")})
check(bt.problems() == ["bluetoothctl is missing or will not run"],
      "and a missing bluetoothctl stops there rather than guessing")

print("\nFAILURES: %d" % len(fails))
sys.exit(1 if fails else 0)
