"""Tests for si_controller: the supervisor with a real (fake) child process, the
management API and its token rules, redaction, and the shared wording.

The child is a 30-line stand-in for server/server.py written to a temp folder:
it serves /health on the port it is given and exits, crashes or hangs on demand.
Nothing here touches the real server, SQL Server, services or any address other
than 127.0.0.1; the controller's home is a temp folder (never %ProgramData%).
"""
from __future__ import annotations

import json
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

from si_controller.client import Client, ControllerError
from si_controller.config import Config, Policy, load_config, read_token, save_config
from si_controller.controller import Controller
from si_controller.redaction import redact_line
from si_controller.words import duration, verdict

FAKE_SERVER = r'''
import argparse, json, os, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
p = argparse.ArgumentParser(); p.add_argument("--port", type=int); p.add_argument("--host")
a = p.parse_args()
if os.environ.get("FAKE_MODE") == "crash":
    print("boom: PORTFOLIO_SQL_PASSWORD=hunter2", file=sys.stderr, flush=True)
    sys.exit(3)
hang = {"on": False}
class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):   # mimic uvicorn's access log on stderr
        print('INFO:     127.0.0.1:5000 - "%s" %s OK' % (self.requestline, args[1]),
              file=sys.stderr, flush=True)
    def do_GET(self):
        if self.path.startswith("/exit"):
            os._exit(int(self.path.split("=")[1]))
        if self.path == "/hang":
            hang["on"] = True
        if self.path == "/health" and hang["on"]:
            time.sleep(3)
        body = json.dumps({"ok": True, "server_version": "9.9.9", "uptime_seconds": 1,
                           "db_ok": True, "db_error": ""}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)
print("Fake server listening", flush=True)
print("WARNING: token=abc123def456", flush=True)
ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()
'''

FAST = Policy(start_timeout=10.0, health_interval=0.3, health_timeout=0.5, unhealthy_after=2,
              stop_grace=5.0, backoff=(0.2, 0.4), crash_limit=3, crash_window=60.0, port_wait=0.3)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(predicate, timeout: float = 10.0, step: float = 0.05):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = predicate()
        if value:
            return value
        time.sleep(step)
    raise AssertionError("condition not met in time")


def http_get(url: str, port: int, path: str, headers: dict) -> int:
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=5) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except OSError:                     # /exit and /hang never answer
        return 0


@pytest.fixture
def rig(tmp_path, monkeypatch):
    """A running controller (own thread) supervising the fake server."""
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    (server_dir / "server.py").write_text(FAKE_SERVER, encoding="utf-8")
    home = tmp_path / "home"
    monkeypatch.delenv("FAKE_MODE", raising=False)
    started = []

    def start(**overrides):
        cfg = Config(python_exe=sys.executable, server_dir=str(server_dir), port=free_port(),
                     api_port=free_port(), wait_for_sql=False, policy=FAST)
        for k, v in overrides.items():
            setattr(cfg, k, v)
        ctl = Controller(cfg, home, tick_interval=0.05)
        thread = threading.Thread(target=ctl.run, daemon=True)
        thread.start()
        wait_for(lambda: read_token(home))
        client = Client(root=home, port=cfg.api_port)
        wait_for(lambda: _answers(client))
        started.append((ctl, thread))
        return ctl, client

    yield start
    for ctl, thread in started:
        ctl.shutdown()
        thread.join(timeout=15)
        assert not thread.is_alive(), "controller did not shut down"


def _answers(client: Client) -> bool:
    try:
        client.status()
        return True
    except ControllerError:
        return False


def state(client: Client) -> str:
    return client.status()["server"]["state"]


def kinds(client: Client) -> list[str]:
    return [e["kind"] for e in client.events()]


# ---------------------------------------------------------------- supervisor
def test_start_health_status_and_output(rig):
    ctl, client = rig()
    wait_for(lambda: state(client) == "running")
    st = client.status()
    srv = st["server"]
    assert srv["pid"] and srv["restarts"] == 0
    assert srv["health"]["alive"] and srv["health"]["ok"]
    assert srv["health"]["data"]["server_version"] == "9.9.9"
    assert st["controller"]["api_port"] == ctl.cfg.api_port
    assert set(st["machine"]) == {"sql", "tunnel", "disk"}
    assert verdict(st) == ("good", "The server is running and healthy.")

    wait_for(lambda: any("WARNING" in l["text"] for l in client.logs()["lines"]))
    texts = [l["text"] for l in client.logs()["lines"]]
    assert "Fake server listening" in texts
    assert "WARNING: token=[redacted]" in texts
    assert not any("GET /health" in t for t in texts), "health checks are noise"
    latest = client.logs()["latest"]
    assert client.logs(since=latest)["lines"] == []
    assert {"start_requested", "spawned", "running"} <= set(kinds(client))
    assert (ctl.root / "logs" / "server.log").read_text(encoding="utf-8").count("Fake server") == 1


def test_crash_restarts_with_backoff(rig):
    ctl, client = rig()
    wait_for(lambda: state(client) == "running")
    first_pid = client.status()["server"]["pid"]
    http_get("", ctl.cfg.port, "/exit?code=3", {})
    wait_for(lambda: "exited" in kinds(client))
    exited = [e for e in client.events() if e["kind"] == "exited"][-1]
    assert exited["code"] == 3 and exited["delay"] == 0.2
    assert "exited with code 3" in exited["message"] and "Restarting in" in exited["message"]
    wait_for(lambda: state(client) == "running" and client.status()["server"]["pid"] != first_pid)
    assert client.status()["server"]["restarts"] == 1
    assert client.status()["server"]["last_exit"]["code"] == 3


def test_crash_loop_gives_up(rig, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "crash")
    ctl, client = rig()
    wait_for(lambda: state(client) == "failed", timeout=15)
    st = client.status()
    assert st["server"]["failures_in_window"] == 3
    assert verdict(st)[0] == "bad"
    assert "failed" in kinds(client)
    stderr = [l["text"] for l in client.logs()["lines"] if l["stream"] == "stderr"]
    assert "boom: PORTFOLIO_SQL_PASSWORD=[redacted]" in stderr
    assert not any("hunter2" in t for t in stderr)
    time.sleep(0.5)
    assert state(client) == "failed", "a failed server is left stopped"


def test_graceful_stop_then_start_and_restart(rig):
    ctl, client = rig()
    wait_for(lambda: state(client) == "running")
    client.command("stop")
    wait_for(lambda: state(client) == "stopped")
    st = client.status()["server"]
    assert st["last_exit"]["code"] == 0, "stopped by the launcher, not killed"
    assert "killed" not in kinds(client)
    assert verdict(client.status())[1].startswith("The server is not running.")
    stop_event = [e for e in client.events() if e["kind"] == "stop_requested"][-1]
    assert stop_event["who"] == client.who

    client.command("start")
    wait_for(lambda: state(client) == "running")
    pid = client.status()["server"]["pid"]
    client.command("restart")
    wait_for(lambda: state(client) == "running" and client.status()["server"]["pid"] != pid)
    assert client.status()["server"]["restarts"] == 0, "a requested restart is not a failure"


def test_hung_server_is_restarted(rig):
    ctl, client = rig()
    wait_for(lambda: state(client) == "running")
    pid = client.status()["server"]["pid"]
    threading.Thread(target=http_get, args=("", ctl.cfg.port, "/hang", {}), daemon=True).start()
    wait_for(lambda: "hung" in kinds(client), timeout=10)
    wait_for(lambda: state(client) == "running" and client.status()["server"]["pid"] != pid)


def test_waits_while_port_is_taken(rig):
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 0))
    blocker.listen()
    port = blocker.getsockname()[1]
    try:
        ctl, client = rig(port=port)
        wait_for(lambda: state(client) == "waiting")
        assert "already in use" in client.status()["server"]["message"]
        assert verdict(client.status())[0] == "warn"
    finally:
        blocker.close()
    wait_for(lambda: state(client) == "running")


# ----------------------------------------------------------------------- API
def test_api_requires_token_loopback_host_and_no_origin(rig):
    ctl, client = rig(autostart=False)
    port = ctl.cfg.api_port
    token = read_token(ctl.root)
    good = {"Authorization": f"Bearer {token}"}
    assert http_get("", port, "/status", good) == 200
    assert http_get("", port, "/status", {}) == 401
    assert http_get("", port, "/status", {"Authorization": "Bearer wrong"}) == 401
    assert http_get("", port, "/status", {**good, "Origin": "http://evil.example"}) == 401
    assert http_get("", port, "/status", {**good, "Host": f"evil.example:{port}"}) == 401
    assert http_get("", port, "/nope", good) == 404
    assert state(client) == "stopped"

    bad = Client(root=ctl.root, port=port)
    bad._token = lambda: "wrong"
    with pytest.raises(ControllerError) as exc:
        bad.status()
    assert exc.value.status == 401


def test_second_controller_cannot_take_the_api_port(rig, tmp_path):
    ctl, _client = rig(autostart=False)
    other = Controller(ctl.cfg, tmp_path / "other")
    assert other.run() == 2
    assert other.events.recent()[-1]["kind"] == "api_failed"


def test_unreachable_controller_is_reported(tmp_path):
    (tmp_path / "token").write_text("t", encoding="ascii")
    with pytest.raises(ControllerError, match="not answering"):
        Client(root=tmp_path, port=free_port(), timeout=0.5).status()


# ------------------------------------------------------------------- helpers
@pytest.mark.parametrize("line, expected", [
    ("PORTFOLIO_SQL_PASSWORD=hunter2", "PORTFOLIO_SQL_PASSWORD=[redacted]"),
    ("DRIVER={ODBC};SERVER=x;UID=sa;PWD=s3cr3t;", "DRIVER={ODBC};SERVER=x;UID=sa;PWD=[redacted];"),
    ('{"token": "abc.def"}', '{"token": "[redacted]"}'),
    ("Authorization: Bearer eyJhbGciOi.abc", "Authorization: Bearer [redacted]"),
    ("calling Bearer abcdef123456 now", "calling Bearer [redacted] now"),
    ("https://user:pa55@example.com/x", "https://user:[redacted]@example.com/x"),
    ("password=None", "password=None"),
    ("INFO: GET /trades 200", "INFO: GET /trades 200"),
])
def test_redaction(line, expected):
    assert redact_line(line) == expected


def test_config_defaults_and_partial_file(tmp_path):
    cfg = load_config(tmp_path)
    assert (cfg.port, cfg.api_port) == (8742, 8746)
    assert cfg.sql_service == "MSSQL$STOCKINSIGHTS"
    (tmp_path / "controller.json").write_text(
        json.dumps({"port": 9000, "policy": {"backoff": [1, 2]}, "unknown": 1}), encoding="utf-8")
    cfg = load_config(tmp_path)
    assert cfg.port == 9000 and cfg.policy.backoff == (1.0, 2.0) and cfg.api_port == 8746
    save_config(cfg, tmp_path)
    assert load_config(tmp_path).policy.backoff == (1.0, 2.0)
    (tmp_path / "controller.json").write_text("{broken", encoding="utf-8")
    assert load_config(tmp_path).port == 8742


def test_manager_tasks_commands():
    """The Tasks page's commands (pure; no Qt needed)."""
    import base64
    from si_manager.tasks import build_tasks, powershell_args, sql_server_name

    assert sql_server_name("MSSQL$STOCKINSIGHTS") == r"localhost\STOCKINSIGHTS"
    assert sql_server_name("MSSQLSERVER") == "localhost"
    tasks = {t.key: t for t in build_tasks("MSSQL$OTHER")}
    assert tasks["migrate"].command.startswith(r"sqlcmd -S localhost\OTHER -d StockInsights -E -C -b -I")
    assert tasks["migrate"].elevated and not tasks["logs"].elevated
    script = base64.b64decode(powershell_args(tasks["install"]).split()[-1]).decode("utf-16-le")
    assert "install_autostart.ps1" in script and "Read-Host" in script


def test_words():
    assert duration(42) == "42 s"
    assert duration(3600 * 3 + 60 * 12) == "3 h 12 min"
    assert duration(86400 * 2 + 3600) == "2 days 1 h"
    assert verdict(None)[0] == "bad"
    running_db_down = {"server": {"state": "running", "health": {
        "alive": True, "ok": False, "detail": "database unavailable (see server log)"}}}
    assert verdict(running_db_down) == (
        "warn", "The server is running, but it reports a problem: "
                "database unavailable (see server log).")
    assert verdict({"server": {"state": "backoff", "retry_in_seconds": 15}})[1] == \
        "The server stopped unexpectedly and restarts in 15 s."
