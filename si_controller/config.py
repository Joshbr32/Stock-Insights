"""Where the controller keeps its files, its configuration, and the API token.

Everything lives in one folder, the *home*:

    %ProgramData%\\StockInsights\\controller\\     (override: SI_CONTROLLER_HOME)
        controller.json     configuration (written by server/install_autostart.ps1)
        token               the management API token (created on first start)
        logs\\server.log     server output, rotated (server.log.1 ... .5)
        logs\\events.jsonl   controller events, one JSON object per line, rotated
        logs\\controller.log the controller's own problems

A missing or partly written ``controller.json`` is not an error: every key has a
default, so ``python -m si_controller run`` works on a fresh PC.
"""
from __future__ import annotations

import json
import os
import secrets
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_SERVER_PORT = 8742          # what the Cloudflare tunnel and LAN clients use
DEFAULT_API_PORT = 8746             # Colonial uses 8740 (API) and 8744 (server): keep clear
DEFAULT_SQL_SERVICE = "MSSQL$STOCKINSIGHTS"
DEFAULT_TUNNEL_SERVICE = "cloudflared"


def home() -> Path:
    override = os.environ.get("SI_CONTROLLER_HOME")
    if override:
        return Path(override)
    base = os.environ.get("ProgramData") or os.environ.get("PROGRAMDATA") or r"C:\ProgramData"
    return Path(base) / "StockInsights" / "controller"


def logs_dir(root: Path | None = None) -> Path:
    return (root or home()) / "logs"


@dataclass
class Policy:
    """How the supervisor reacts. Seconds unless the name says otherwise."""
    start_timeout: float = 90.0       # a new process must answer /health within this
    health_interval: float = 15.0     # between checks while running
    health_timeout: float = 5.0
    unhealthy_after: int = 3          # missed checks in a row before a restart
    stop_grace: float = 20.0          # time to finish requests before being killed
    backoff: tuple = (2.0, 5.0, 15.0, 30.0, 60.0)
    crash_limit: int = 5              # this many failures ...
    crash_window: float = 600.0       # ... within this window = give up ("failed")
    port_wait: float = 10.0           # re-check interval while the port is taken


@dataclass
class Config:
    python_exe: str = field(default_factory=lambda: sys.executable)
    server_dir: str = field(default_factory=lambda: str(REPO_ROOT / "server"))
    server_script: str = "server.py"
    port: int = DEFAULT_SERVER_PORT
    host: str = ""                    # empty = the server's own default (0.0.0.0)
    api_port: int = DEFAULT_API_PORT
    autostart: bool = True            # start the server when the controller starts
    sql_service: str = DEFAULT_SQL_SERVICE
    tunnel_service: str = DEFAULT_TUNNEL_SERVICE
    wait_for_sql: bool = True         # hold the start until sql_service runs (if it exists)
    policy: Policy = field(default_factory=Policy)

    def server_argv(self, launcher: Path) -> list[str]:
        argv = [self.python_exe, "-X", "utf8", str(launcher),
                str(Path(self.server_dir) / self.server_script), "--port", str(self.port)]
        if self.host:
            argv += ["--host", self.host]
        return argv

    def to_json(self) -> dict:
        data = asdict(self)
        data["policy"]["backoff"] = list(self.policy.backoff)
        return data


def _known(cls, raw: dict) -> dict:
    names = {f.name for f in fields(cls)}
    return {k: v for k, v in raw.items() if k in names}


def load_config(root: Path | None = None) -> Config:
    """Read ``controller.json``; unknown keys are ignored, missing ones defaulted."""
    path = (root or home()) / "controller.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(raw, dict):
            raw = {}
    except FileNotFoundError:
        raw = {}
    except (OSError, ValueError) as exc:
        print(f"controller.json could not be read ({exc}); using defaults", file=sys.stderr)
        raw = {}
    policy_raw = raw.pop("policy", None) or {}
    cfg = Config(**_known(Config, raw))
    pol = _known(Policy, policy_raw)
    if "backoff" in pol:
        pol["backoff"] = tuple(float(x) for x in pol["backoff"]) or Policy.backoff
    cfg.policy = Policy(**pol)
    cfg.port = int(cfg.port)
    cfg.api_port = int(cfg.api_port)
    return cfg


def save_config(cfg: Config, root: Path | None = None) -> Path:
    root = root or home()
    root.mkdir(parents=True, exist_ok=True)
    path = root / "controller.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg.to_json(), indent=2), encoding="utf-8")
    os.replace(tmp, path)       # atomic: a reader never sees half a file
    return path


# ---------------------------------------------------------------------------
# The API token. Whoever can read this file can start and stop the server, so
# the folder's Windows permissions (set by install_autostart.ps1) decide who
# that is: the owner's account, SYSTEM and Administrators.
# ---------------------------------------------------------------------------
def token_path(root: Path | None = None) -> Path:
    return (root or home()) / "token"


def read_token(root: Path | None = None) -> str | None:
    try:
        return token_path(root).read_text(encoding="ascii").strip() or None
    except (OSError, UnicodeDecodeError):
        return None


def ensure_token(root: Path | None = None) -> str:
    existing = read_token(root)
    if existing:
        return existing
    path = token_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    # O_EXCL: if two controllers race, one creates and the other reads it back.
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return read_token(root) or token
    with os.fdopen(fd, "w", encoding="ascii") as fh:
        fh.write(token)
    return token
