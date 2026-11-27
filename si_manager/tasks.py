"""The once-in-a-while jobs on the Tasks page, and how they are started.

Each ``Task`` says in words what it does and carries the exact command it runs,
which the page shows and can copy. Jobs that need administrator rights start in
their own PowerShell window through Windows' "Run as administrator" prompt
(``ShellExecuteW`` with the ``runas`` verb), so the manager itself never runs
elevated. The window says "Finished." or why it stopped and waits for Enter.
"""
from __future__ import annotations

import base64
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from si_controller.config import REPO_ROOT, logs_dir

MIGRATION = REPO_ROOT / "server" / "migrations" / "001_tags_trade_uid.sql"
INSTALL = REPO_ROOT / "server" / "install_autostart.ps1"
UNINSTALL = REPO_ROOT / "server" / "uninstall_autostart.ps1"


@dataclass(frozen=True)
class Task:
    key: str
    title: str
    description: str
    command: str              # exactly what runs, as shown to the owner
    elevated: bool
    missing: str = ""         # why it cannot run here ("" = it can)


def sql_server_name(sql_service: str) -> str:
    """``MSSQL$STOCKINSIGHTS`` -> ``localhost\\STOCKINSIGHTS``; ``MSSQLSERVER`` -> ``localhost``."""
    if sql_service.upper().startswith("MSSQL$"):
        return "localhost\\" + sql_service[6:]
    return "localhost"


def _ps_quote(path: Path | str) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def build_tasks(sql_service: str = "MSSQL$STOCKINSIGHTS", home: Path | None = None) -> list[Task]:
    logs = logs_dir(home)
    server = sql_server_name(sql_service)
    return [
        Task("migrate", "Update the database schema",
             "Runs migration 001 (trade tags and IDs, wider password hashes, indexes) on the "
             "StockInsights database with sqlcmd, signed in as you (Windows sign-in). The server "
             "applies it itself at start-up when its SQL login may; run this when the Dashboard "
             "says the schema needs it. Safe to run twice. Restart the server afterwards.",
             f'sqlcmd -S {server} -d StockInsights -E -C -b -I -i "{MIGRATION}"',
             elevated=True,
             missing="" if MIGRATION.exists() else
             f"The migration file is not in this copy of the repository ({MIGRATION.name})."),
        Task("logs", "Open the logs folder",
             "Shows the server output files (server.log, rotated at 5 MB) and the controller's "
             "events (events.jsonl) in File Explorer.",
             f'explorer "{logs}"', elevated=False,
             missing="" if logs.exists() else "The controller has not written any logs on this PC yet."),
        Task("install", "Turn on autostart",
             "Sets SQL Server to start with Windows and registers the scheduled task "
             "\"StockInsights Controller\", which starts the server at boot and restarts it when it "
             "stops. Safe to run again; it prints what it changed.",
             f'powershell -NoProfile -ExecutionPolicy Bypass -File "{INSTALL}"', elevated=True),
        Task("uninstall", "Turn off autostart",
             "Removes the scheduled task (the server stops) and puts SQL Server's start type back "
             "to what it was. Only undoes what \"Turn on autostart\" changed; logs are kept.",
             f'powershell -NoProfile -ExecutionPolicy Bypass -File "{UNINSTALL}"', elevated=True),
    ]


def _script_for(task: Task) -> str:
    """The PowerShell the elevated window runs: the command, then how it ended."""
    if task.key in ("install", "uninstall"):
        body = f"& {_ps_quote(INSTALL if task.key == 'install' else UNINSTALL)}"
    else:
        body = "& " + task.command        # sqlcmd: run exactly as shown
    return (
        f"Set-Location {_ps_quote(REPO_ROOT)}\n"
        f"Write-Host {_ps_quote(task.title)} -ForegroundColor Cyan\n"
        f"Write-Host {_ps_quote('> ' + task.command)}\n"
        "$ok = $true\n"
        f"try {{ {body}; if ($LASTEXITCODE) {{ $ok = $false }} }}\n"
        "catch { Write-Host $_ -ForegroundColor Red; $ok = $false }\n"
        "Write-Host ''\n"
        "if ($ok) { Write-Host 'Finished.' -ForegroundColor Green }\n"
        "else { Write-Host 'It stopped with an error (see above).' -ForegroundColor Red }\n"
        "Read-Host 'Press Enter to close this window' | Out-Null\n"
    )


def powershell_args(task: Task) -> str:
    encoded = base64.b64encode(_script_for(task).encode("utf-16-le")).decode("ascii")
    return f"-NoProfile -ExecutionPolicy Bypass -EncodedCommand {encoded}"


def run(task: Task) -> str:
    """Start ``task``; returns a sentence for the page. Never blocks."""
    if task.missing:
        return task.missing
    if task.key == "logs":
        os.startfile(str(logs_dir()))  # noqa: S606 - opens Explorer on our own folder
        return "Opened the logs folder."
    if sys.platform != "win32":
        return "Tasks run only on Windows."
    if not task.elevated:
        subprocess.Popen(["powershell.exe"] + powershell_args(task).split(" "),
                         creationflags=subprocess.CREATE_NEW_CONSOLE)
        return f"Started \"{task.title}\" in its own window."
    import ctypes

    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", "powershell.exe",
                                             powershell_args(task), str(REPO_ROOT), 1)
    if rc <= 32:
        return (f"Windows did not start \"{task.title}\" (administrator permission was not "
                f"given, code {rc}).")
    return f"Started \"{task.title}\" in an administrator window. Follow it there."
