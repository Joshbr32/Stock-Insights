"""``python -m si_controller run|status|start|stop|restart|logs|events``.

``run`` is the controller itself (what the scheduled task starts); every other
command is a client of its management API and works from any (non-elevated)
PowerShell of the account that can read the token.
"""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import signal
import sys

from . import CONTROLLER_VERSION
from .client import Client, ControllerError
from .config import home, load_config, logs_dir
from .words import STATE_WORDS, duration, service_line, verdict


def _run() -> int:
    from .controller import Controller

    root = home()
    cfg = load_config(root)
    logs_dir(root).mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        logs_dir(root) / "controller.log", maxBytes=1024 * 1024, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler, logging.StreamHandler()])

    controller = Controller(cfg, root)

    def stop(*_args):
        controller.shutdown()

    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), stop)
    print(f"Stock Insights controller {CONTROLLER_VERSION}: server on port {cfg.port}, "
          f"API on 127.0.0.1:{cfg.api_port}, files in {root}. Ctrl+C stops both.")
    return controller.run()


def _print_status(data: dict) -> None:
    _tone, sentence = verdict(data)
    srv = data["server"]
    health = srv.get("health") or {}
    hd = health.get("data") or {}
    print(sentence)
    print(f"  State      {STATE_WORDS.get(srv['state'], srv['state'])}"
          + (f" (process {srv['pid']})" if srv.get("pid") else ""))
    if srv.get("uptime_seconds") is not None:
        print(f"  Up for     {duration(srv['uptime_seconds'])}")
    print(f"  Restarts   {srv.get('restarts', 0)}")
    if hd.get("server_version"):
        print(f"  Version    {hd['server_version']}")
    if hd:
        print(f"  Database   {'reachable' if hd.get('db_ok') else 'not reachable'}")
    if hd.get("schema"):
        print(f"  Schema     {hd['schema'].replace('_', ' ')}")
    if srv.get("last_exit"):
        ex = srv["last_exit"]
        print(f"  Last exit  {ex.get('at')}: {ex.get('reason')}")
    machine = data.get("machine", {})
    for label, key in (("SQL Server", "sql"), ("Tunnel", "tunnel")):
        print(f"  {service_line(label, machine.get(key))[1]}")
    disk = machine.get("disk")
    if disk:
        print(f"  Disk {disk['path']} {disk['free_gb']} GB free of {disk['total_gb']} GB")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m si_controller",
                                     description="Keeps the Stock Insights sync server running.")
    parser.add_argument("command", choices=["run", "status", "start", "stop", "restart",
                                            "logs", "events"])
    parser.add_argument("--limit", type=int, default=40, help="lines for logs / events")
    args = parser.parse_args(argv)

    if args.command == "run":
        return _run()
    try:
        client = Client()
        if args.command == "status":
            _print_status(client.status())
        elif args.command in ("start", "stop", "restart"):
            client.command(args.command)
            print(f"Asked the controller to {args.command} the server. "
                  "See: python -m si_controller status")
        elif args.command == "logs":
            for line in client.logs(0, args.limit)["lines"]:
                print(f"{line['at']} {line['stream']:<6} {line['text']}")
        elif args.command == "events":
            for ev in client.events(args.limit):
                print(f"{ev['at']}  {ev['message']}")
    except ControllerError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0
