# -*- coding: utf-8 -*-
"""Keeps the chosen USB/IP devices attached.

Runs for as long as Kodi does. Every pass it compares what should be attached
(the "auto" list, set from the USB over IP screen) against what actually is,
and reattaches anything missing.

This is the "make auto-connect more automatic" item from the original app's
To-Do list. The important differences from doing it on a timer:

  * it backs off per host, so a Pi that is switched off is retried every few
    minutes rather than every few seconds;
  * it never retries a device that is already attached, so a working setup
    costs one cheap "usbip port" call per pass;
  * it gives up on a device that fails repeatedly until something changes,
    rather than logging forever.
"""

import os
import sys
import time

import xbmc

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import usbip_core as U

POLL = 15                  # seconds between passes when all is well
BACKOFF_START = 30         # first retry delay for a host that failed
BACKOFF_MAX = 600          # never wait longer than this before trying again
TAG = "script.usbip: "


def log(message, level=xbmc.LOGINFO):
    xbmc.log(TAG + message, level)


class Reattacher(object):
    def __init__(self):
        self.next_try = {}      # host ip -> monotonic deadline
        self.delay = {}         # host ip -> current backoff
        self.warned = set()     # host ips we have already logged a failure for

    def ready(self, host, now):
        return now >= self.next_try.get(host, 0)

    def succeeded(self, host):
        self.delay.pop(host, None)
        self.next_try.pop(host, None)
        self.warned.discard(host)

    def failed(self, host, now, message):
        delay = min(self.delay.get(host, BACKOFF_START) * 2, BACKOFF_MAX)
        self.delay[host] = delay
        self.next_try[host] = now + delay
        # Log the first failure per host at warning level and stay quiet after,
        # otherwise an unplugged Pi fills kodi.log all evening.
        if host not in self.warned:
            self.warned.add(host)
            log("%s: %s -- retrying, backing off to %ds"
                % (host, message, delay), xbmc.LOGWARNING)

    def pass_once(self, now):
        config = U.load_config()
        wanted = config.get("auto") or []
        if not wanted:
            return

        here, error = U.attached()
        if error:
            # Local usbip is broken; nothing to do until it is fixed.
            if "local" not in self.warned:
                self.warned.add("local")
                log("cannot read attached devices: %s" % error, xbmc.LOGWARNING)
            return
        self.warned.discard("local")

        attached = set(U.auto_key(d["host"], d["busid"]) for d in here)

        for entry in wanted:
            host = entry.get("ip")
            busid = entry.get("busid")
            user = entry.get("user")
            if not (host and busid and user):
                continue
            if U.auto_key(host, busid) in attached:
                continue
            if not self.ready(host, now):
                continue
            name = entry.get("name") or busid
            error = U.attach(host, user, busid)
            if error:
                self.failed(host, now, error)
            else:
                self.succeeded(host)
                log("reattached %s from %s" % (name, host))


def main():
    monitor = xbmc.Monitor()
    reattacher = Reattacher()
    log("reattach service started")
    # Kodi starts services before the network is necessarily up; the backoff
    # handles that on its own, so just start polling.
    while not monitor.abortRequested():
        try:
            # monotonic, so a clock adjustment cannot strand a backoff in the
            # future -- this box has no RTC battery and does correct its time
            # after boot.
            reattacher.pass_once(time.monotonic())
        except Exception as exc:                    # never kill the service
            log("pass failed: %s" % exc, xbmc.LOGERROR)
        if monitor.waitForAbort(POLL):
            break
    log("reattach service stopped")


if __name__ == "__main__":
    main()
