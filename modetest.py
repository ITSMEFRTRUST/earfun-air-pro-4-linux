#!/usr/bin/env python3
"""Mode test: opens SPP via BlueZ Profile1 and CHANGES the noise mode (anc, ambient, off), reading it
back after each.  Leaves the buds on off.

Usage: modetest.py AA:BB:CC:DD:EE:FF   (the buds must be connected, on adapter hci0, with the daemon stopped)
"""
import re, sys, time, socket

if len(sys.argv) != 2 or not re.fullmatch(r"([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", sys.argv[1]):
    sys.exit(__doc__.strip().splitlines()[-1])

import dbus, dbus.service, dbus.mainloop.glib
from gi.repository import GLib

ADDR = sys.argv[1].upper()
UUID = "00001101-0000-1000-8000-00805f9b34fb"
PATH = "/org/earfun_linux/probe"
GETS = [(0x0015 | 0x0300, "mode (0 off,1 anc,2 ambient)"), (0x033B, "anc style"),
        (0x033D, "transparency style"), (0x0306, "battery L"), (0x0307, "battery R"),
        (0x0317, "battery case"), (0x0309, "firmware"), (0x0300, "gaia api")]

def frame(cmd):
    return bytes([0xFF, 0x04, 0x00, 0x00, 0x00, 0x0A]) + cmd.to_bytes(2, "big")

class Profile(dbus.service.Object):
    @dbus.service.method("org.bluez.Profile1", in_signature="oha{sv}")
    def NewConnection(self, dev, fd, props):
        s = socket.socket(fileno=fd.take())
        s.settimeout(1.0)
        seq = [(frame(0x0315), "get", 0.8)]
        for v, n in [(1, "set anc"), (2, "set ambient"), (0, "set off")]:
            seq += [(bytes([0xFF,4,0,1,0,0x0A,0x03,0x14,v]), n, 2.5), (frame(0x0315), "get", 0.8)]
        for f, name, wait in seq:
            s.send(f)
            print(f"{time.strftime('%X')} TX {f.hex(' ')}   {name}")
            end = time.time() + wait
            while time.time() < end:
                try:
                    data = s.recv(1024)
                except socket.timeout:
                    break
                print(f"RX {data.hex(' ')}")
                if data[8:].isascii() and len(data) > 12:
                    print(f"   text: {data[10:].decode(errors='replace')}")
        s.close()
        loop.quit()

    @dbus.service.method("org.bluez.Profile1")
    def Release(self): pass

    @dbus.service.method("org.bluez.Profile1", in_signature="o")
    def RequestDisconnection(self, dev): pass

dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
bus = dbus.SystemBus()
Profile(bus, PATH)
mgr = dbus.Interface(bus.get_object("org.bluez", "/org/bluez"), "org.bluez.ProfileManager1")
mgr.RegisterProfile(PATH, UUID, {"Name": "earfun-probe", "Role": "client",
                                 "AutoConnect": dbus.Boolean(False)})
dev = dbus.Interface(bus.get_object("org.bluez", "/org/bluez/hci0/dev_" + ADDR.replace(":", "_")),
                     "org.bluez.Device1")
dev.ConnectProfile(UUID, reply_handler=lambda: None,
                   error_handler=lambda e: (print("connect failed:", e), loop.quit()))
loop = GLib.MainLoop()
GLib.timeout_add_seconds(20, lambda: (print("timeout"), loop.quit()))
loop.run()
mgr.UnregisterProfile(PATH)
