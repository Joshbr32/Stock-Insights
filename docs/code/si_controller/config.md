# si_controller/config.py
**Purpose:** Where the controller keeps its files (the *home*), its JSON configuration with defaults, and the management API token.
**Used by:** every other `si_controller` module, `si_manager` (`tasks.py`, through `Client`), `server/install_autostart.ps1` (writes the same JSON).  **Depends on:** stdlib only.

## Key types and functions
| Name | Kind | Contract |
|---|---|---|
| `home()` | func | `$SI_CONTROLLER_HOME`, else `%ProgramData%\StockInsights\controller`. Tests and the screenshot harness always use a temp folder. |
| `logs_dir(root)` | func | `<home>\logs`. |
| `Policy` | dataclass | Supervisor timings (see `supervisor.md`); `backoff` is a tuple. |
| `Config` | dataclass | `python_exe` (default: this Python), `server_dir` (default `<repo>\server`), `server_script`, `port` 8742, `host` ("" = the server's default 0.0.0.0), `api_port` 8746, `autostart`, `sql_service` `MSSQL$STOCKINSIGHTS`, `tunnel_service` `cloudflared`, `wait_for_sql`, `policy`. |
| `Config.server_argv(launcher)` | method | `[python, -X utf8, launcher, server.py, --port N (, --host H)]`. |
| `load_config(root)` | func | Missing or broken file = defaults (note on stderr); unknown keys ignored; UTF-8 with or without BOM (PowerShell 5.1 writes one). |
| `save_config(cfg, root)` | func | Atomic (temp file + `os.replace`). |
| `token_path` / `read_token` / `ensure_token` | func | `<home>\token`, 43 url-safe characters, created once with `O_EXCL`; never rotated automatically (delete it and restart the controller to rotate). |

## Data and state
`<home>\controller.json` (keys above, `policy` nested) and `<home>\token`. Who may read the token is decided by the folder's ACL, set by the installer: the owner, SYSTEM, Administrators.

## How to change it safely
- Ports 8740-8745 belong to the Colonial controller on the same PC; keep the defaults clear of them.
- A new key needs a default here and, if the installer should set it, a line in `install_autostart.ps1` step 4.

## Map
- 1-30 docstring, constants
- 32-42 `home`, `logs_dir`
- 44-83 `Policy`, `Config`
- 85-121 load / save
- 123-end token
