"""Plain-sentence wording of the controller's status, shared by the CLI and the manager.

Pure functions over the ``GET /status`` JSON; no I/O, so they are easy to test.
Tones: ``good`` (all is well), ``warn`` (works, but look), ``bad`` (not serving),
``busy`` (changing state), ``idle`` (no colour; nothing is known or nothing to say).
"""
from __future__ import annotations

STATE_WORDS = {
    "running": "Running",
    "starting": "Starting",
    "stopping": "Stopping",
    "stopped": "Stopped",
    "waiting": "Waiting",
    "backoff": "Restarting soon",
    "failed": "Failed",
}

SERVICE_WORDS = {
    "running": "Running", "stopped": "Stopped", "starting": "Starting", "stopping": "Stopping",
    "paused": "Paused", "pausing": "Pausing", "continuing": "Resuming",
    "missing": "Not installed", "unknown": "Unknown",
}


def duration(seconds: float | None) -> str:
    """``42 s``, ``5 min``, ``3 h 12 min``, ``2 days 4 h``."""
    if seconds is None:
        return ""
    s = int(seconds)
    if s < 60:
        return f"{s} s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m} min"
    h, m = divmod(m, 60)
    if h < 24:
        return f"{h} h {m} min" if m else f"{h} h"
    d, h = divmod(h, 24)
    return f"{d} day{'s' if d != 1 else ''} {h} h" if h else f"{d} day{'s' if d != 1 else ''}"


def state_tone(state: str, health_ok: bool = True) -> str:
    if state == "running":
        return "good" if health_ok else "warn"
    if state in ("starting", "stopping"):
        return "busy"
    if state in ("waiting", "backoff"):
        return "warn"
    return "bad"            # stopped, failed


def verdict(status: dict | None) -> tuple[str, str]:
    """The one-line answer for the top of the manager and ``status`` on the CLI."""
    if not status:
        return "bad", "Can't reach the controller, so the server's state is unknown."
    srv = status.get("server", {})
    state = srv.get("state", "stopped")
    health = srv.get("health") or {}
    if state == "running":
        if health.get("ok"):
            return "good", "The server is running and healthy."
        detail = (health.get("detail") or "").rstrip(".")
        if not health.get("alive"):
            return "warn", "The server is running but did not answer its last health check."
        return "warn", f"The server is running, but it reports a problem: {detail}."
    if state == "starting":
        return "busy", "The server is starting."
    if state == "stopping":
        return "busy", "The server is stopping."
    if state == "waiting":
        reason = (srv.get("message") or "").rstrip(".")
        return "warn", f"The server is waiting to start: {reason}."
    if state == "backoff":
        wait = duration(srv.get("retry_in_seconds"))
        return "warn", (f"The server stopped unexpectedly and restarts in {wait}."
                        if wait else "The server stopped unexpectedly and restarts shortly.")
    if state == "failed":
        return "bad", ("The server kept failing and was left stopped. "
                       "Check the server output, then start it.")
    cmd = srv.get("last_command") or {}
    if cmd.get("action") == "stop" and cmd.get("who") not in (None, "controller"):
        return "bad", f"The server is not running. {cmd['who']} stopped it."
    return "bad", "The server is not running."


def service_line(label: str, svc: dict | None) -> tuple[str, str]:
    """(tone, sentence) for a Windows service row such as SQL Server or the tunnel."""
    state = (svc or {}).get("state", "unknown")
    name = (svc or {}).get("name", "")
    word = SERVICE_WORDS.get(state, state.capitalize())
    tone = {"running": "good", "missing": "idle", "unknown": "idle"}.get(
        state, "busy" if state.endswith("ing") else "bad")
    return tone, f"{label} ({name}): {word.lower()}" if name else f"{label}: {word.lower()}"
