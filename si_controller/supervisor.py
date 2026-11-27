"""The supervisor: start the sync server, watch it, restart it, stop it cleanly.

``Supervisor`` is a small state machine advanced by ``tick()`` (the controller
calls it a few times a second). Commands (``start`` / ``stop`` / ``restart``) only
change what is *wanted*; ``tick`` does the work. Starting a process, asking
``/health``, the service and port checks and the clock are all injectable, so the
rules are tested without a real server.

States::

    stopped ──start──► waiting ──SQL up, port free──► starting ──/health answers──► running
       ▲                                                 │ exits / never answers      │ exits / 3 missed checks
       │                                                 ▼                            ▼
       └──────────── stopping ◄──stop──              backoff ──delay──► starting   (same)
                                                         │ crash_limit failures in crash_window
                                                         ▼
                                                       failed   (left stopped until someone starts it)

*Alive* (``/health`` answers at all) decides restarts. *Healthy* (``ok`` /
``db_ok`` in its JSON) is reported but never causes a restart: restarting the
server does not bring SQL Server back.

Graceful stop: the server runs under ``launch/run_server.py``, which turns the word
``stop`` on its standard input into the same SIGINT handling as Ctrl+C, so
uvicorn finishes requests in flight. After ``stop_grace`` seconds it is killed.
(CTRL_BREAK_EVENT is not used: it needs a shared console, and sent to a process
group that is not on the caller's console Windows may deliver it to the caller.)
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from . import win
from .config import Config, Policy
from .logs import EventLog, OutputLog, now_iso
from .redaction import redact_line

STOPPED, WAITING, STARTING, RUNNING, STOPPING, BACKOFF, FAILED = (
    "stopped", "waiting", "starting", "running", "stopping", "backoff", "failed")

LAUNCHER = Path(__file__).resolve().parent / "launch" / "run_server.py"


@dataclass
class Health:
    alive: bool = False               # the server answered at all
    ok: bool = False                  # it says it is healthy (database reachable)
    detail: str = ""
    data: dict = field(default_factory=dict)
    checked_at: str = ""


class Process(Protocol):
    pid: int

    def poll(self) -> int | None: ...
    def request_stop(self) -> None: ...
    def kill(self) -> None: ...
    def usage(self) -> dict | None: ...
    def close(self) -> None: ...


# ---------------------------------------------------------------------------
# The real child process and the real checks
# ---------------------------------------------------------------------------
def _is_health_noise(line: str) -> bool:
    """The controller's own /health checks in uvicorn's access log."""
    return '"GET /health HTTP/1.1" 200' in line and "127.0.0.1:" in line


class ServerProcess:
    """A child process in a job object, its stdout and stderr captured by line."""

    def __init__(self, argv: list[str], cwd: str, output: OutputLog,
                 env: dict[str, str] | None = None):
        child_env = dict(os.environ if env is None else env)
        child_env["PYTHONUNBUFFERED"] = "1"      # lines arrive as they are printed
        child_env["PYTHONIOENCODING"] = "utf-8"
        flags = 0
        if win.IS_WINDOWS:
            flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        self._job = win.Job()
        self._output = output
        self._popen = subprocess.Popen(
            argv, cwd=cwd, env=child_env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, creationflags=flags)
        try:
            if win.IS_WINDOWS:
                self._job.assign(int(self._popen._handle))
        except OSError:
            self._popen.kill()
            self._job.close()
            raise
        self.pid = self._popen.pid
        self._readers = [
            threading.Thread(target=self._read, args=(self._popen.stdout, "stdout"),
                             name=f"server-stdout-{self.pid}", daemon=True),
            threading.Thread(target=self._read, args=(self._popen.stderr, "stderr"),
                             name=f"server-stderr-{self.pid}", daemon=True),
        ]
        for t in self._readers:
            t.start()

    def _read(self, pipe, stream: str) -> None:
        for raw in iter(pipe.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if _is_health_noise(line):
                continue
            self._output.add(stream, redact_line(line))

    def poll(self) -> int | None:
        return self._popen.poll()

    def request_stop(self) -> None:
        try:
            self._popen.stdin.write(b"stop\n")
            self._popen.stdin.flush()
            self._popen.stdin.close()
        except (OSError, ValueError):
            pass                          # already gone or pipe closed: kill follows

    def kill(self) -> None:
        self._job.terminate()
        try:
            self._popen.kill()
        except OSError:
            pass

    def usage(self) -> dict | None:
        if self._popen.poll() is not None:
            return None
        return win.process_usage(int(self._popen._handle)) if win.IS_WINDOWS else None

    def close(self) -> None:
        if self._popen.poll() is None:
            self.kill()
        try:
            self._popen.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        for t in self._readers:
            t.join(timeout=2)
        for stream in (self._popen.stdin, self._popen.stdout, self._popen.stderr):
            try:
                if stream:
                    stream.close()
            except OSError:
                pass
        self._job.close()


_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def http_health(port: int, timeout: float) -> Health:
    """Ask the server's ``GET /health`` on the loopback address."""
    request = urllib.request.Request(f"http://127.0.0.1:{port}/health",
                                     headers={"X-SI-Probe": "1"})
    at = now_iso()
    try:
        with _NO_PROXY.open(request, timeout=timeout) as resp:
            body = resp.read(65536)
    except urllib.error.HTTPError as exc:          # it answered, so it is alive
        return Health(alive=True, ok=False, detail=f"/health answered {exc.code}", checked_at=at)
    except (OSError, ValueError) as exc:           # refused, timed out, reset ...
        return Health(alive=False, ok=False, detail=f"no answer: {exc}", checked_at=at)
    try:
        data = json.loads(body)
        if not isinstance(data, dict):
            raise ValueError("not an object")
    except ValueError:
        return Health(alive=True, ok=False, detail="/health did not return JSON", checked_at=at)
    ok = bool(data.get("ok"))
    detail = "" if ok else (data.get("db_error") or "the server reports a problem")
    return Health(alive=True, ok=ok, detail=str(detail), data=data, checked_at=at)


def port_in_use(port: int) -> bool:
    """True when another program already holds the TCP port.

    Binding (exclusively, on all addresses) answers at once; connecting to a
    closed port on Windows waits about two seconds for retries.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            s.bind(("0.0.0.0", port))
        except OSError:
            return True
        return False


# ---------------------------------------------------------------------------
# The state machine
# ---------------------------------------------------------------------------
class Supervisor:
    def __init__(self, cfg: Config, events: EventLog, output: OutputLog,
                 spawn: Callable[[], Process] | None = None,
                 probe: Callable[[], Health] | None = None,
                 service_state: Callable[[str], str] = win.service_state,
                 port_check: Callable[[int], bool] = port_in_use,
                 clock: Callable[[], float] = time.monotonic):
        self.cfg = cfg
        self.policy: Policy = cfg.policy
        self.events = events
        self.output = output
        self._spawn = spawn or self._spawn_real
        self._probe = probe or (lambda: http_health(cfg.port, self.policy.health_timeout))
        self._service_state = service_state
        self._port_check = port_check
        self._clock = clock

        self._lock = threading.RLock()
        self.state = STOPPED
        self.desired = STOPPED
        self.message = ""                 # why it is waiting / in backoff / failed
        self.process: Process | None = None
        self.health = Health()
        self.started_at: float | None = None
        self.started_wall = ""
        self.restarts = 0                 # automatic restarts since the controller started
        self.last_exit: dict | None = None
        self.last_command: dict | None = None
        self._crashes: deque[float] = deque()
        self._deadline = 0.0
        self._retry_at = 0.0
        self._next_probe = 0.0
        self._spawned_at = 0.0
        self._misses = 0
        self._restart_after_stop = False
        self._generation = 0              # changes whenever the process changes
        self._cpu_sample: tuple[float, float] | None = None
        self._usage: dict | None = None

    def _spawn_real(self) -> Process:
        return ServerProcess(self.cfg.server_argv(LAUNCHER), self.cfg.server_dir, self.output)

    # ------------------------------------------------------------- commands
    def _command(self, action: str, who: str) -> None:
        self.last_command = {"action": action, "who": who, "at": now_iso()}
        if who == "controller":
            return                        # the controller records its own shutdown event
        if who == "autostart":
            message = "The controller is starting the server (autostart is on)."
        else:
            message = f"{who} asked to {action} the server."
        self.events.record(f"{action}_requested", message, who=who)

    def start(self, who: str = "unknown") -> None:
        with self._lock:
            self._command("start", who)
            self.desired = RUNNING
            if self.state in (FAILED, BACKOFF):       # someone is trying again now
                self._crashes.clear()
                self._set(STOPPED, "")

    def stop(self, who: str = "unknown") -> None:
        with self._lock:
            self._command("stop", who)
            self.desired = STOPPED
            self._restart_after_stop = False

    def restart(self, who: str = "unknown") -> None:
        with self._lock:
            self._command("restart", who)
            if self.state in (STARTING, RUNNING):
                self.desired = RUNNING
                self._restart_after_stop = True
                self._begin_stop(self._clock())
            else:
                self.desired = RUNNING
                if self.state in (FAILED, BACKOFF):
                    self._crashes.clear()
                    self._set(STOPPED, "")

    # ----------------------------------------------------------------- tick
    def tick(self) -> None:
        """Advance the state machine once. Call a few times a second."""
        probe_generation = None
        with self._lock:
            now = self._clock()
            s = self.state
            if s == STOPPED:
                if self.desired == RUNNING:
                    self._try_start(now)
            elif s in (WAITING, BACKOFF):
                if self.desired != RUNNING:
                    self._set(STOPPED, "")
                elif now >= self._retry_at:
                    self._try_start(now)
            elif s in (STARTING, RUNNING):
                rc = self.process.poll() if self.process else 1
                if self.desired != RUNNING:
                    self._begin_stop(now)
                elif rc is not None:
                    self._crashed(now, "exited", f"The server process exited with code {rc}.", rc)
                elif now >= self._next_probe:
                    self._next_probe = now + (1.0 if s == STARTING else self.policy.health_interval)
                    probe_generation = self._generation
            elif s == STOPPING:
                rc = self.process.poll() if self.process else 0
                if rc is not None:
                    self._finish_stop(rc)
                elif now >= self._deadline:
                    self.events.record(
                        "killed", f"The server did not stop within {self.policy.stop_grace:.0f} s "
                                  "and was ended by force.", pid=self.process.pid)
                    self._kill()
                    self._deadline = now + 10.0
            # FAILED: nothing happens until start() or restart()

        if probe_generation is not None:
            health = self._probe()            # outside the lock: it can take seconds
            with self._lock:
                if probe_generation == self._generation and self.state in (STARTING, RUNNING):
                    self._apply_health(self._clock(), health)

    # ------------------------------------------------------------ internals
    def _set(self, state: str, message: str) -> None:
        self.state = state
        self.message = message

    def _wait(self, now: float, reason: str, delay: float) -> None:
        if self.state != WAITING or self.message != reason:
            self.events.record("waiting", f"The server is waiting to start: {reason}")
        self._set(WAITING, reason)
        self._retry_at = now + delay

    def _try_start(self, now: float) -> None:
        if self.cfg.wait_for_sql and self.cfg.sql_service:
            sql = self._service_state(self.cfg.sql_service)
            # 'missing' / 'unknown': a remote or renamed SQL Server; don't wait forever
            if sql not in ("running", "missing", "unknown"):
                self._wait(now, f"SQL Server ({self.cfg.sql_service}) is {sql}.", 3.0)
                return
        if self._port_check(self.cfg.port):
            self._wait(now, f"port {self.cfg.port} is already in use by another program "
                            "(is the server already running in a window?).",
                       self.policy.port_wait)
            return
        try:
            self.process = self._spawn()
        except Exception as exc:  # noqa: BLE001 - a bad path or Python must not kill the loop
            self.process = None
            self._crashed(now, "spawn_failed", f"The server could not be started: {exc}.", None)
            return
        self._generation += 1
        self.health = Health()
        self._misses = 0
        self._cpu_sample = None
        self._usage = None
        self._deadline = now + self.policy.start_timeout
        self._next_probe = now + 0.5
        self._spawned_at = now
        self._set(STARTING, "")
        self.events.record("spawned", f"The server process started (process {self.process.pid}).",
                           pid=self.process.pid)

    def _apply_health(self, now: float, health: Health) -> None:
        self.health = health
        self._sample_usage(now)
        if self.state == STARTING:
            if health.alive:
                self.started_at = now
                self.started_wall = now_iso()
                self._set(RUNNING, "")
                took = now - self._spawned_at
                extra = "" if health.ok else f" It reports a problem: {health.detail}."
                self.events.record("running", f"The server answered its health check after "
                                              f"{took:.0f} s and is running.{extra}",
                                   version=health.data.get("server_version"))
            elif now >= self._deadline:
                self._kill()
                self._crashed(now, "start_timeout",
                              f"The server did not answer its health check within "
                              f"{self.policy.start_timeout:.0f} s of starting, so it was ended.",
                              None)
            return
        if health.alive:
            self._misses = 0
            return
        self._misses += 1
        if self._misses >= self.policy.unhealthy_after:
            self._kill()
            self._crashed(now, "hung", f"The server stopped answering its health check "
                                       f"({self._misses} checks missed), so it was ended.", None)

    def _begin_stop(self, now: float) -> None:
        if self.process is None:
            self._set(STOPPED, "")
            return
        self._deadline = now + self.policy.stop_grace
        self._set(STOPPING, "")
        try:
            self.process.request_stop()
        except Exception:  # noqa: BLE001 - the kill after stop_grace covers it
            pass

    def _finish_stop(self, rc: int | None) -> None:
        self.last_exit = {"at": now_iso(), "reason": "stopped on request", "code": rc}
        self._release_process()
        self._set(STOPPED, "")
        self.events.record("stopped", f"The server stopped (exit code {rc}).", code=rc)
        if self._restart_after_stop:
            self._restart_after_stop = False
            self.desired = RUNNING

    def _crashed(self, now: float, kind: str, sentence: str, rc: int | None) -> None:
        tail = self.output.tail(20)
        self.last_exit = {"at": now_iso(), "reason": sentence, "code": rc}
        self._release_process()
        self._crashes.append(now)
        while self._crashes and now - self._crashes[0] > self.policy.crash_window:
            self._crashes.popleft()
        n = len(self._crashes)
        if n >= self.policy.crash_limit:
            minutes = self.policy.crash_window / 60
            self.events.record(kind, sentence, code=rc, console=tail)
            self._set(FAILED, f"{n} failures in {minutes:.0f} minutes; last: {sentence}")
            self.events.record("failed", f"The server failed {n} times in {minutes:.0f} minutes, "
                                         "so it was left stopped until someone starts it.")
            return
        delay = self.policy.backoff[min(n - 1, len(self.policy.backoff) - 1)]
        self.restarts += 1
        self._retry_at = now + delay
        self._set(BACKOFF, sentence)
        self.events.record(kind, f"{sentence} Restarting in {delay:.0f} s.",
                           code=rc, delay=delay, console=tail)

    def _kill(self) -> None:
        if self.process:
            try:
                self.process.kill()
            except Exception:  # noqa: BLE001
                pass

    def _release_process(self) -> None:
        if self.process:
            try:
                self.process.close()
            except Exception:  # noqa: BLE001
                pass
        self.process = None
        self.started_at = None
        self._generation += 1
        self._usage = None
        self.health = Health()

    def _sample_usage(self, now: float) -> None:
        usage = self.process.usage() if self.process else None
        if not usage:
            return
        cpu = usage.get("cpu_seconds")
        if cpu is not None and self._cpu_sample and now > self._cpu_sample[0]:
            usage["cpu_percent"] = round(
                100.0 * (cpu - self._cpu_sample[1]) / (now - self._cpu_sample[0])
                / (os.cpu_count() or 1), 1)
        if cpu is not None:
            self._cpu_sample = (now, cpu)
        self._usage = usage

    def refresh_usage(self) -> None:
        """Re-read memory and CPU (the status call does this; probes are 15 s apart)."""
        with self._lock:
            if self.process and self.state in (STARTING, RUNNING, STOPPING):
                self._sample_usage(self._clock())

    # --------------------------------------------------------------- status
    def status(self) -> dict:
        with self._lock:
            now = self._clock()
            h = self.health
            return {
                "state": self.state,
                "desired": self.desired,
                "message": self.message,
                "pid": self.process.pid if self.process else None,
                "port": self.cfg.port,
                "started_at": self.started_wall if self.started_at is not None else None,
                "uptime_seconds": (int(now - self.started_at)
                                   if self.started_at is not None else None),
                "restarts": self.restarts,
                "failures_in_window": len(self._crashes),
                "retry_in_seconds": (max(0, round(self._retry_at - now))
                                     if self.state in (BACKOFF, WAITING) else None),
                "last_exit": self.last_exit,
                "last_command": self.last_command,
                "health": {"alive": h.alive, "ok": h.ok, "detail": h.detail,
                           "checked_at": h.checked_at or None, "data": h.data},
                "usage": self._usage,
            }

    def wait_stopped(self, timeout: float, step: float = 0.1) -> bool:
        """Drive ``tick`` until the server is down (used at controller shutdown)."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.tick()
            if self.state in (STOPPED, FAILED) and self.process is None:
                return True
            time.sleep(step)
        return False


def machine_status(cfg: Config) -> dict:
    """The PC around the server: SQL Server, the tunnel, disk space."""
    disk = None
    try:
        du = shutil.disk_usage(cfg.server_dir)
        disk = {"path": str(Path(cfg.server_dir).anchor or cfg.server_dir),
                "free_gb": round(du.free / 1024 ** 3, 1), "total_gb": round(du.total / 1024 ** 3, 1)}
    except OSError:
        pass
    return {
        "sql": {"name": cfg.sql_service, "state": win.service_state(cfg.sql_service)},
        "tunnel": {"name": cfg.tunnel_service, "state": win.service_state(cfg.tunnel_service)},
        "disk": disk,
    }
