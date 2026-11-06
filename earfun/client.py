"""Tiny JSON-lines client for the earfun daemon socket (stdlib only)."""

from __future__ import annotations

import json
import socket

from .daemon import default_socket_path


class DaemonDown(Exception):
    pass


def _connect(path=None, timeout=None):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(path or default_socket_path())
    except OSError as e:
        s.close()
        raise DaemonDown(str(e)) from None
    return s


def request(req: dict, path=None, timeout=15.0) -> dict:
    s = _connect(path, timeout)
    try:
        s.sendall((json.dumps(req) + "\n").encode())
        f = s.makefile("rb")
        line = f.readline()
        if not line:
            raise DaemonDown("daemon closed the connection")
        return json.loads(line)
    except socket.timeout:
        raise DaemonDown("daemon did not answer") from None
    finally:
        s.close()


def watch(path=None):
    """Yields state dicts until the daemon goes away (then raises DaemonDown)."""
    s = _connect(path, None)
    try:
        s.sendall(b'{"cmd":"watch"}\n')
        f = s.makefile("rb")
        for line in f:
            if line.strip():
                yield json.loads(line)
        raise DaemonDown("daemon closed the connection")
    except OSError as e:
        raise DaemonDown(str(e)) from None
    finally:
        s.close()
