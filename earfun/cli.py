"""`earfun` command line.  Exit codes: 0 ok, 1 error/refused, 2 daemon not running."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

from . import protocol as P
from .client import DaemonDown, request, watch

DOWN = {"daemon": False}


def _err(msg, code=1):
    print("earfun: %s" % msg, file=sys.stderr)
    return code


def _req(a, req):
    try:
        return request(req, a.socket)
    except DaemonDown as e:
        raise SystemExit(_err("daemon not running (%s); start it with `earfun daemon`" % e, 2))


def _ago(ts):
    if not ts:
        return ""
    d = max(0, time.time() - ts)
    return ", %s ago" % ("%dm" % (d // 60) if d < 3600 else "%dh" % (d // 3600) if d < 172800
                         else "%dd" % (d // 86400))


def _human(st):
    if not st.get("daemon"):
        return "daemon not running"
    b = st["battery"]
    pc = lambda v: "--" if v is None else "%d%%" % v
    lines = ["%s  [%s%s]" % (st.get("name") or "EarFun", st["channel"],
                              ", fake" if st.get("source") == "fake" else "")]
    if st.get("error"):
        lines.append("error:    %s" % st["error"])
    mode = st.get("mode") or "?"
    if st.get("pending_mode"):
        mode += " -> %s (pending)" % st["pending_mode"]
    lines.append("mode:     %s" % mode)
    lines.append("anc:      %s   transparency: %s" % (st.get("anc_style"), st.get("transparency_style")))
    case = pc(b["case"])
    if b["case"] is None and b.get("case_last") is not None:
        case = "-- (last %d%%%s)" % (b["case_last"], _ago(b.get("case_seen")))
    lines.append("battery:  L %s  R %s  case %s" % (pc(b["left"]), pc(b["right"]), case))
    lines.append("firmware: %s" % st.get("firmware"))
    return "\n".join(lines)


def cmd_status(a):
    r = _req(a, {"cmd": "status"}) if not a.json else None
    if a.json:
        try:
            r = request({"cmd": "status"}, a.socket)
        except DaemonDown:
            print(json.dumps(DOWN))
            return 2
        print(json.dumps(r["state"], sort_keys=True))
        return 0
    print(_human(r["state"]))
    return 0


def _set(a, key, value):
    r = _req(a, {"cmd": "set", "key": key, "value": value, "wait": a.wait})
    if not r.get("ok"):
        return _err(r.get("error", "failed"))
    if a.wait and r.get("confirmed") is False:
        return _err("%s: sent %s, buds still report %s" % (key, r.get("value"), r.get("reported")))
    v = r.get("value")
    tail = " (confirmed)" if r.get("confirmed") else (" (pending)" if r.get("pending") else "")
    print("%s = %s%s" % (key, json.dumps(v) if not isinstance(v, str) else v, tail))
    return 0


def cmd_mode(a):
    return _set(a, "mode", a.value)


def cmd_set(a):
    return _set(a, a.key, a.value)


def cmd_get(a):
    if a.key not in P.SETTINGS:
        return _err("unknown key %r (try: earfun keys)" % a.key)
    r = _req(a, {"cmd": "get", "key": a.key, "refresh": not a.cached})
    if not r.get("ok"):
        return _err(r.get("error", "failed"))
    v = r.get("value")
    print(v if isinstance(v, str) else json.dumps(v))
    return 0


def cmd_keys(a):
    rows = [s.info() for s in P.iter_table()]
    if a.json:
        print(json.dumps(rows, indent=1))
        return 0
    for r in rows:
        print("%-24s %-9s get:%-5s set:%-5s %s%s" % (
            r["key"], r["kind"], r["get"] or "-", r["set"] or "-", r["values"],
            "  [live: %s]" % "+".join(x for x, y in (("get", r["verified_get"]), ("set", r["verified_set"])) if y)
            if (r["verified_get"] or r["verified_set"]) else ""))
    return 0


def _die_with_parent():
    # qs starts `earfun watch` as a child; without this it outlives a qs restart
    try:
        import ctypes, signal
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG
    except Exception:
        pass
    if os.getppid() == 1:
        sys.exit(0)


def cmd_watch(a):
    _die_with_parent()
    down_printed = False
    while True:
        try:
            for st in watch(a.socket):
                down_printed = False
                print(json.dumps(st, sort_keys=True), flush=True)
        except DaemonDown:
            pass
        except KeyboardInterrupt:
            return 0
        if not down_printed:
            print(json.dumps(DOWN), flush=True)
            down_printed = True
        try:
            time.sleep(3)
        except KeyboardInterrupt:
            return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="earfun", description="EarFun Air Pro 4 controller")
    ap.add_argument("--socket", help="daemon socket (default $XDG_RUNTIME_DIR/earfun.sock)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("status"); p.add_argument("--json", action="store_true"); p.set_defaults(fn=cmd_status)
    p = sub.add_parser("mode"); p.add_argument("value", choices=["off", "anc", "ambient", "cycle"])
    p.add_argument("--wait", action="store_true", help="wait until the buds report it"); p.set_defaults(fn=cmd_mode)
    p = sub.add_parser("get"); p.add_argument("key"); p.add_argument("--cached", action="store_true")
    p.set_defaults(fn=cmd_get)
    p = sub.add_parser("set"); p.add_argument("key"); p.add_argument("value")
    p.add_argument("--wait", action="store_true"); p.set_defaults(fn=cmd_set)
    p = sub.add_parser("keys"); p.add_argument("--json", action="store_true"); p.set_defaults(fn=cmd_keys)
    p = sub.add_parser("watch"); p.set_defaults(fn=cmd_watch)
    p = sub.add_parser("daemon", add_help=False); p.set_defaults(fn=None)
    if argv is None:
        argv = sys.argv[1:]
    # `earfun [--socket X] daemon ...`: hand the rest to the daemon's own parser
    i = 2 if argv[:1] == ["--socket"] else 0
    if argv[i:i + 1] == ["daemon"]:
        from .daemon import main as dmain
        return dmain(argv[:i] + argv[i + 1:])
    a = ap.parse_args(argv)
    return a.fn(a)
