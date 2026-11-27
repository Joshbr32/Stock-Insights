"""The management API from the caller's side: the CLI and the desktop manager use it.

Standard library only. It reads the token on every call (the controller creates
it at its first start), talks to 127.0.0.1 only and never through a proxy.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from .config import home, load_config, read_token

_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class ControllerError(Exception):
    """The controller could not be reached, or refused the request."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def windows_user() -> str:
    return "\\".join(x for x in (os.environ.get("USERDOMAIN"),
                                 os.environ.get("USERNAME")) if x) or "Someone"


class Client:
    def __init__(self, root: Path | None = None, port: int | None = None, timeout: float = 10.0):
        self.root = Path(root) if root else home()
        self.port = port or load_config(self.root).api_port
        self.timeout = timeout
        self.who = windows_user()

    def _token(self) -> str:
        token = read_token(self.root)
        if not token:
            raise ControllerError(
                f"No controller token can be read at {self.root}. Is the controller installed, "
                "and are you signed in as the account that installed it?")
        return token

    def call(self, method: str, path: str, timeout: float | None = None) -> dict:
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", method=method,
            data=b"" if method == "POST" else None,
            headers={"Authorization": f"Bearer {self._token()}", "X-Windows-User": self.who})
        try:
            with _NO_PROXY.open(req, timeout=timeout or self.timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read()).get("error", "")
            except (ValueError, OSError, AttributeError):
                detail = ""
            raise ControllerError(f"The controller refused the request ({exc.code}): "
                                  f"{detail or exc.reason}.", exc.code) from None
        except (urllib.error.URLError, OSError, ValueError) as exc:
            reason = getattr(exc, "reason", exc)
            raise ControllerError(f"The controller is not answering on 127.0.0.1:{self.port} "
                                  f"({reason}).") from None

    def status(self) -> dict:
        return self.call("GET", "/status", timeout=5)

    def command(self, action: str) -> dict:
        if action not in ("start", "stop", "restart"):
            raise ValueError(action)
        return self.call("POST", f"/{action}")

    def logs(self, since: int = 0, limit: int = 500) -> dict:
        return self.call("GET", f"/logs?since={int(since)}&limit={int(limit)}")

    def events(self, limit: int = 200) -> list[dict]:
        return self.call("GET", f"/events?limit={int(limit)}")["events"]
