"""Detaching a USB/IP device must not take it away from everyone else.

ssh and the local usbip call are both stubbed: these record the exact command
sequence, which is the whole of what was wrong before.
"""
import importlib.machinery
import importlib.util
import sys
import os

sys.argv = ["x"]
ldr = importlib.machinery.SourceFileLoader(
    "u", os.path.expanduser("~/.kodi/addons/script.usbip/usbip_core.py"))
U = importlib.util.module_from_spec(importlib.util.spec_from_loader("u", ldr))
ldr.exec_module(U)

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


calls = []


def wire(ssh_result=(0, "", ""), local_result=(0, "", "")):
    calls[:] = []

    def fake_ssh(host, user, command):
        calls.append("ssh:" + command.replace("sudo -n usbip ", ""))
        return ssh_result(command) if callable(ssh_result) else ssh_result

    def fake_local(*args):
        calls.append("local:" + " ".join(args))
        return local_result

    U.ssh = fake_ssh
    U.sudo_usbip = fake_local


print("-- detaching leaves the device shared --")
wire()
check(U.detach(0, "192.0.2.10", "piuser", "1-1.3") is None,
      "a clean detach reports no problem")
check(calls == ["local:detach -p 0", "ssh:unbind -b 1-1.3", "ssh:bind -b 1-1.3"],
      "it detaches, then re-exports, got %r" % calls)
check(calls[-1].endswith("bind -b 1-1.3") and "unbind" not in calls[-1],
      "and the LAST thing it does is bind, not unbind -- "
      "otherwise nobody else can attach it")

print("-- a detach that cannot re-share says so --")


def bind_fails(command):
    return (0, "", "") if "unbind" in command else (1, "", "device busy")


wire(ssh_result=bind_fails)
error = U.detach(0, "192.0.2.10", "piuser", "1-1.3")
check(error and "could not share it again" in error,
      "the partial success is reported, got %r" % error)

print("-- an already-bound device is not an error --")


def already(command):
    return (0, "", "") if "unbind" in command else (1, "", "device already bound")


wire(ssh_result=already)
check(U.detach(0, "192.0.2.10", "piuser", "1-1.3") is None,
      "already bound means it is shared, which is what was wanted")

print("-- without server details it just detaches locally --")
wire()
check(U.detach(2) is None, "a bare detach works")
check(calls == ["local:detach -p 2"], "and touches the server not at all, got %r" % calls)

print("-- a failed local detach never touches the server --")
wire(local_result=(1, "", "port not attached"))
error = U.detach(0, "192.0.2.10", "piuser", "1-1.3")
check(error and "detach failed" in error, "the failure is reported")
check(calls == ["local:detach -p 0"],
      "and nothing was unbound on the server, got %r" % calls)

print("-- stopping sharing on purpose is a separate thing --")
wire()
check(U.unexport("192.0.2.10", "piuser", "1-1.3") is None, "unexport works")
check(calls == ["ssh:unbind -b 1-1.3"], "and only unbinds, got %r" % calls)
wire(ssh_result=(1, "", "device is not bound"))
check(U.unexport("192.0.2.10", "piuser", "1-1.3") is None,
      "a device that was not shared anyway is not an error")
wire(ssh_result=(1, "", "no such device"))
check(U.unexport("192.0.2.10", "piuser", "1-1.3") is not None,
      "but a real failure is reported")

print("\n-- usbip that exists but cannot run is not a sudo problem --")
# /usr/bin/usbip is only a wrapper script from linux-tools-common. Without the
# tools for the running kernel it prints a warning and exits 2 -- so it passes
# every "is it installed" test and still does nothing. That used to surface as
# "sudo usbip needs a password", sending people to fix the wrong thing.
real_run, real_exists = U.run, U.os.path.exists


def fake_env(present=True, version_rc=0, sudo_rc=0, key=True):
    U.os.path.exists = lambda path: (
        present if path == U.USBIP else key if path == U.SSH_KEY else False)

    def fake_run(cmd, timeout=None):
        if cmd[:2] == [U.USBIP, "version"]:
            return (version_rc, "", "")
        return (sudo_rc, "", "")

    U.run = fake_run


try:
    fake_env(version_rc=2)
    usable, problem = U.usbip_usable()
    check(not usable, "a wrapper that exits 2 counts as unusable")
    check("kernel" in problem,
          "and the kernel is named as the reason, got %r" % problem)
    check(not any("password" in p for p in U.check_client()),
          "sudo is not blamed for it, got %r" % U.check_client())

    fake_env(present=False)
    usable, problem = U.usbip_usable()
    check(not usable and "not installed" in problem,
          "a missing usbip still reads as missing, got %r" % problem)

    fake_env()
    check(U.usbip_usable() == (True, None), "a working usbip is usable")
    check(U.check_client() == [], "and a working client reports nothing")

    fake_env(sudo_rc=1)
    check(any("password" in p for p in U.check_client()),
          "a genuine sudo failure is still reported")
finally:
    U.run, U.os.path.exists = real_run, real_exists

print("\nFAILURES: %d" % len(fails))
sys.exit(1 if fails else 0)
