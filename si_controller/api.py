"""The management API: how ``python -m si_controller`` and the manager talk to the controller.

* Listens on **127.0.0.1 only** (default port 8746); nothing on the network reaches it.
* Every request needs ``Authorization: Bearer <token>``; the token is the file
  ``<home>\\token``, readable only by the accounts the installer allows.
* The ``Host`` header must be the loopback address and any browser ``Origin`` is
  refused, so a web page open on this PC cannot drive it (DNS rebinding, CSRF).
* ``X-Windows-User`` names who asked; it is recorded in the events, the token is
  the proof.

    GET  /status                       server, health, usage, SQL Server, tunnel, disk
    POST /start | /stop | /restart     {"ok": true, "state": ...}
    GET  /logs?since=SEQ&limit=N       server output after line SEQ (redacted)
    GET  /events?limit=N               controller events, newest last
"""
from __future__ import annotations

import hmac
import json
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import parse_qs, urlparse


def _int(query: dict, name: str, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(query.get(name, [default])[0])))
    except (TypeError, ValueError):
        return default


class _LoopbackServer(ThreadingHTTPServer):
    # HTTPServer turns on SO_REUSEADDR, which on Windows lets a second program
    # bind the same port. Ask for the port exclusively instead, so a second
    # controller fails loudly rather than sharing it.
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def make_server(controller, port: int, token_reader: Callable[[], str | None]) -> ThreadingHTTPServer:
    """Bind the API (raises OSError if the port is taken). Call ``serve_forever`` on it."""
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        server_version = "SIController"
        sys_version = ""
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args):   # the event log is the record; no stderr chatter
            pass

        def _send(self, code: int, payload) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _authorised(self) -> bool:
            if self.headers.get("Host", "") not in allowed_hosts:
                return False
            if self.headers.get("Origin"):
                return False
            auth = self.headers.get("Authorization", "")
            if not auth.startswith("Bearer "):
                return False
            token = token_reader()
            return bool(token) and hmac.compare_digest(auth[7:].strip().encode(), token.encode())

        def _who(self) -> str:
            return (self.headers.get("X-Windows-User") or "Someone").strip()[:120] or "Someone"

        def do_GET(self):  # noqa: N802
            if not self._authorised():
                return self._send(401, {"error": "not authorised"})
            url = urlparse(self.path)
            query = parse_qs(url.query)
            if url.path == "/status":
                return self._send(200, controller.status())
            if url.path == "/logs":
                return self._send(200, controller.output.since(
                    _int(query, "since", 0, 0, 2 ** 62), _int(query, "limit", 500, 1, 5000)))
            if url.path == "/events":
                return self._send(200, {"events": controller.events.recent(
                    _int(query, "limit", 200, 1, 1000))})
            return self._send(404, {"error": "no such route"})

        def do_POST(self):  # noqa: N802
            # Drain any body so the connection stays usable; commands take none.
            length = _int({"n": [self.headers.get("Content-Length", "0")]}, "n", 0, 0, 65536)
            if length:
                self.rfile.read(length)
            if not self._authorised():
                return self._send(401, {"error": "not authorised"})
            action = urlparse(self.path).path.strip("/")
            if action not in ("start", "stop", "restart"):
                return self._send(404, {"error": "no such route"})
            getattr(controller.supervisor, action)(self._who())
            controller.wake()
            return self._send(200, {"ok": True, "state": controller.supervisor.state})

    return _LoopbackServer(("127.0.0.1", port), Handler)
