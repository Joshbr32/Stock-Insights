"""The controller process: the supervisor, its logs and the management API, together.

``Controller.run()`` is what the scheduled task runs (through
``python -m si_controller run``): it makes sure the token exists, binds the API
(a second controller fails here), starts the server if ``autostart`` is on, and
ticks the supervisor until ``shutdown()`` is called. On the way out it stops the
server gracefully, so ending the controller with Ctrl+C never leaves a server
behind (and if the controller is killed instead, the job object ends it).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

from . import CONTROLLER_VERSION
from .api import make_server
from .config import Config, ensure_token, logs_dir, read_token
from .logs import EventLog, OutputLog, now_iso
from .supervisor import Supervisor, machine_status

log = logging.getLogger("si_controller")


class Controller:
    def __init__(self, cfg: Config, root: Path, tick_interval: float = 0.5, **supervisor_kwargs):
        self.cfg = cfg
        self.root = Path(root)
        self.tick_interval = tick_interval
        logs = logs_dir(self.root)
        self.output = OutputLog(logs / "server.log")
        self.events = EventLog(logs / "events.jsonl")
        self.supervisor = Supervisor(cfg, self.events, self.output, **supervisor_kwargs)
        self._wake = threading.Event()
        self._stopping = threading.Event()
        self._api = None
        self._api_thread: threading.Thread | None = None
        self.started_wall = now_iso()
        self._started = time.monotonic()

    # ---------------------------------------------------------------- API side
    def status(self) -> dict:
        self.supervisor.refresh_usage()
        return {
            "controller": {"version": CONTROLLER_VERSION, "pid": os.getpid(),
                           "started_at": self.started_wall,
                           "uptime_seconds": int(time.monotonic() - self._started),
                           "api_port": self.cfg.api_port, "home": str(self.root),
                           "server_dir": self.cfg.server_dir},
            "server": self.supervisor.status(),
            "machine": machine_status(self.cfg),
            "time": now_iso(),
        }

    def wake(self) -> None:
        """Run the next tick now (a command just arrived)."""
        self._wake.set()

    def start_api(self) -> None:
        ensure_token(self.root)
        self._api = make_server(self, self.cfg.api_port, lambda: read_token(self.root))
        self._api_thread = threading.Thread(target=self._api.serve_forever, name="api",
                                            daemon=True)
        self._api_thread.start()

    # -------------------------------------------------------------- main loop
    def run(self) -> int:
        try:
            self.start_api()
        except OSError as exc:
            self.events.record("api_failed", f"The controller could not listen on "
                                             f"127.0.0.1:{self.cfg.api_port} ({exc}). Is another "
                                             "controller already running?")
            log.error("API port %s unavailable: %s", self.cfg.api_port, exc)
            self._close_logs()
            return 2
        self.events.record("controller_started",
                           f"The controller started (version {CONTROLLER_VERSION}, "
                           f"API on 127.0.0.1:{self.cfg.api_port}).", pid=os.getpid())
        if self.cfg.autostart:
            self.supervisor.start("autostart")
        try:
            while not self._stopping.is_set():
                try:
                    self.supervisor.tick()
                except Exception:  # noqa: BLE001 - log it and keep watching the server
                    log.exception("supervisor tick failed")
                self._wake.wait(self.tick_interval)
                self._wake.clear()
        finally:
            self._shutdown_server()
        return 0

    def shutdown(self) -> None:
        self._stopping.set()
        self._wake.set()

    def _shutdown_server(self) -> None:
        sup = self.supervisor
        running = sup.process is not None
        self.events.record("controller_stopping", "The controller is shutting down"
                           + (" and stops the server first." if running else "."))
        sup.stop("controller")
        sup.wait_stopped(sup.policy.stop_grace + 12)
        if self._api:
            self._api.shutdown()
            self._api.server_close()
        self._close_logs()

    def _close_logs(self) -> None:
        self.output.close()
        self.events.close()
