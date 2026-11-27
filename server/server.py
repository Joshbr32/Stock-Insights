#!/usr/bin/env python3
r"""Stock Insights — Portfolio Sync Server (SQL Server edition).

FastAPI app that stores each user's trades, accounts, goal settings and
watchlist in SQL Server (via pyodbc), proxies live quotes for the PWA, and
serves the PWA itself (../pwa) from the same origin.

Prerequisites on COLONIAL_SERVER
─────────────────────────────────
1.  Run init_stockinsights.sql in SSMS to create the DB, login, and tables.
2.  Install Python deps:
        pip install -r requirements.txt
3.  Set environment variables (or put them in server/.env — see .env.example):
        PORTFOLIO_SQL_SERVER    e.g. localhost\STOCKINSIGHTS  (default)
        PORTFOLIO_SQL_DATABASE  e.g. StockInsights            (default)
        PORTFOLIO_SQL_USER      e.g. stock_app                (default: sa)
        PORTFOLIO_SQL_PASSWORD  your login password           (required)
        PORTFOLIO_HOST          0.0.0.0                       (default)
        PORTFOLIO_PORT          8742                          (default)
        PORTFOLIO_CORS_ORIGINS  comma-separated origins       (default: *)
4.  First-time: create an admin account:
        python server.py --setup
5.  Run:
        python server.py

Other devices on your network connect to http://COLONIAL_SERVER:8742;
external (off-LAN) clients reach the same server through the Cloudflare
Tunnel at https://si.coloniallawns.ca/  —  the tunnel terminates HTTPS
at Cloudflare's edge and proxies to the origin on port 8742, so port
8742 does NOT need to be open on the public internet. SQL Server itself
is never exposed externally.
"""

import argparse
import csv
import functools
import getpass
import hashlib
import io
import json
import logging
import mimetypes
import os
import pathlib
import re
import secrets
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any, Dict, List, Optional

# Python's mimetypes db doesn't know .webmanifest by default; some browsers
# refuse to install a PWA without the right Content-Type. Register it once.
mimetypes.add_type("application/manifest+json", ".webmanifest")

log = logging.getLogger("stock_insights.server")

# ---------------------------------------------------------------------------
# Load .env (if present) BEFORE we read any PORTFOLIO_* env vars.
#
# python-dotenv is optional: without it, .env is ignored and real environment
# variables are used, so deployments that export PORTFOLIO_SQL_PASSWORD in the
# shell keep working.
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv

    # Only the .env next to server.py — never walk up the tree and pick up an
    # unrelated .env from the project root.
    _ENV_FILE = pathlib.Path(__file__).resolve().parent / ".env"
    if _ENV_FILE.exists():
        load_dotenv(_ENV_FILE, override=False)
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Optional dependency guards
# ---------------------------------------------------------------------------
try:
    import pyodbc
except ImportError:
    print("\nMissing dependency: pyodbc")
    print("Install with:  pip install -r requirements.txt\n")
    raise SystemExit(1)

try:
    import uvicorn
    from fastapi import Depends, FastAPI, HTTPException, Request, status
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.middleware.gzip import GZipMiddleware
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel, Field
    from starlette.datastructures import MutableHeaders
except ImportError as _e:
    print(f"\nMissing dependency: {_e}")
    print("Install with:  pip install -r requirements.txt\n")
    raise SystemExit(1)

# ---------------------------------------------------------------------------
# Configuration  (override via environment variables)
# ---------------------------------------------------------------------------

SQL_SERVER = os.environ.get("PORTFOLIO_SQL_SERVER", r"localhost\STOCKINSIGHTS")
SQL_DATABASE = os.environ.get("PORTFOLIO_SQL_DATABASE", "StockInsights")
SQL_USER = os.environ.get("PORTFOLIO_SQL_USER", "sa")
SQL_PASSWORD = os.environ.get("PORTFOLIO_SQL_PASSWORD")
if not SQL_PASSWORD:
    raise SystemExit(
        "PORTFOLIO_SQL_PASSWORD is not set.\n"
        "\n"
        "Recommended: create server/.env and put your password there:\n"
        "    copy .env.example .env\n"
        "    (then edit .env and fill in PORTFOLIO_SQL_PASSWORD=...)\n"
        "\n"
        "Or set it in your shell before launching:\n"
        "    set PORTFOLIO_SQL_PASSWORD=your_password           (cmd)\n"
        "    $env:PORTFOLIO_SQL_PASSWORD='your_password'        (PowerShell)"
    )
HOST = os.environ.get("PORTFOLIO_HOST", "0.0.0.0")
PORT = int(os.environ.get("PORTFOLIO_PORT", "8742"))
# The PWA is served same-origin and the desktop client is not a browser, so
# neither needs CORS. "*" is kept as the default only for setups that host
# the PWA elsewhere (window.SI_API_URL); set an explicit list to lock it down.
CORS_ORIGINS = [
    o.strip() for o in os.environ.get("PORTFOLIO_CORS_ORIGINS", "*").split(",") if o.strip()
]
TOKEN_DAYS = 30

# Single source of truth for the server-side version. Bump alongside the
# desktop's stock_insights/version.py when you ship coordinated changes
# (new endpoints, schema migrations, etc.). Independent of APP_VERSION
# because server + desktop can update on different cadences.
SERVER_VERSION = "1.0.0"
_SERVER_BOOT_TIME = time.time()


# ---------------------------------------------------------------------------
# Database connection helpers
# ---------------------------------------------------------------------------

def _odbc_driver() -> str:
    """Return the best available ODBC driver name."""
    available = pyodbc.drivers()
    for driver in [
        "ODBC Driver 18 for SQL Server",
        "ODBC Driver 17 for SQL Server",
        "SQL Server Native Client 11.0",
        "SQL Server",
    ]:
        if driver in available:
            return driver
    raise RuntimeError(
        "No ODBC Driver for SQL Server found.\n"
        "Install from: https://aka.ms/downloadmsodbcsql"
    )


@functools.lru_cache(maxsize=1)
def _conn_string() -> str:
    """Build the ODBC connection string once.

    Cached because pyodbc.drivers() enumerates the registry and every
    request opens a connection. The ODBC driver manager pools the physical
    connections (pyodbc.pooling defaults to True), so connect() per request
    is cheap as long as the connection string is identical.
    """
    driver = _odbc_driver()
    # TrustServerCertificate is required for ODBC 18 with self-signed certs
    trust = "TrustServerCertificate=yes;" if "18" in driver else ""
    return (
            f"DRIVER={{{driver}}};"
            f"SERVER={SQL_SERVER};"
            f"DATABASE={SQL_DATABASE};"
            f"UID={SQL_USER};"
            f"PWD={SQL_PASSWORD};"
            + trust
    )


@contextmanager
def db():
    """Yield a pyodbc connection; commit on success, rollback on exception."""
    conn = pyodbc.connect(_conn_string(), autocommit=False)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# Row → dict helpers (pyodbc rows don't support ["key"] access)

def _one(cursor) -> Optional[Dict[str, Any]]:
    row = cursor.fetchone()
    if row is None:
        return None
    cols = [d[0] for d in cursor.description]
    return dict(zip(cols, row))


def _all(cursor) -> List[Dict[str, Any]]:
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def _scalar(cursor):
    """Fetch a single scalar value from the first row."""
    row = cursor.fetchone()
    return row[0] if row else None


def _exec(conn, sql: str, *params):
    """Execute a parameterised statement and return the cursor.

    Every query in this file goes through `?` placeholders — never build SQL
    with f-strings or %-formatting from request data.
    """
    cur = conn.cursor()
    cur.execute(sql, params)
    return cur


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

_PBKDF2_ITERATIONS = 260_000  # baked into stored hashes (format is "salt:hex")


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ITERATIONS)
    return f"{salt}:{dk.hex()}"


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt, dk_hex = stored_hash.split(":", 1)
    except (AttributeError, ValueError):
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ITERATIONS)
    return secrets.compare_digest(dk.hex(), dk_hex)


# Verified against when the username doesn't exist, so a login for an unknown
# user costs the same PBKDF2 time as a wrong password (no user enumeration via
# response timing).
_DUMMY_HASH = _hash_password(secrets.token_hex(8))


def _new_token() -> str:
    return secrets.token_hex(32)  # 64 hex chars — fits NVARCHAR(64)


def _utc_now() -> datetime:
    """Naive UTC now. Tokens are stored tz-naive because the SQL column is
    datetime2 without offset; we only ever compare naive-UTC to naive-UTC."""
    return datetime.now(tz=timezone.utc).replace(tzinfo=None)


def _token_expiry() -> str:
    return (_utc_now() + timedelta(days=TOKEN_DAYS)).strftime("%Y-%m-%dT%H:%M:%S")


def _get_user_from_token(token: str) -> Optional[Dict[str, Any]]:
    with db() as conn:
        cur = _exec(
            conn,
            "SELECT s.user_id, s.expires_at, u.username, u.is_admin "
            "FROM dbo.sessions s JOIN dbo.users u ON u.id = s.user_id "
            "WHERE s.token = ?",
            token,
        )
        row = _one(cur)
    if row is None:
        return None
    expiry = row["expires_at"]
    if isinstance(expiry, str):
        expiry = datetime.fromisoformat(expiry)
    if expiry < _utc_now():
        return None
    return row


# ---- Login throttling -------------------------------------------------------
# The server is reachable from the public internet through the tunnel, so
# cap failed logins per username and per client IP. In-memory is enough for a
# single-process server; a restart simply resets the counters.

_LOGIN_WINDOW_S = 15 * 60
_LOGIN_MAX_FAILS_PER_USER = 10
_LOGIN_MAX_FAILS_PER_IP = 30
_LOGIN_FAILS: Dict[str, List[float]] = {}
_LOGIN_LOCK = Lock()


def _client_ip(request: Request) -> str:
    # Behind cloudflared every request arrives from localhost; Cloudflare puts
    # the real client address in CF-Connecting-IP.
    return (request.headers.get("CF-Connecting-IP")
            or (request.client.host if request.client else "unknown"))


def _login_keys(username: str, ip: str) -> List[tuple]:
    return [("u:" + username.strip().lower(), _LOGIN_MAX_FAILS_PER_USER),
            ("ip:" + ip, _LOGIN_MAX_FAILS_PER_IP)]


def _login_blocked(username: str, ip: str) -> bool:
    cutoff = time.time() - _LOGIN_WINDOW_S
    with _LOGIN_LOCK:
        for key, limit in _login_keys(username, ip):
            recent = [t for t in _LOGIN_FAILS.get(key, []) if t > cutoff]
            if recent:
                _LOGIN_FAILS[key] = recent
            else:
                _LOGIN_FAILS.pop(key, None)
            if len(recent) >= limit:
                return True
    return False


def _record_login_failure(username: str, ip: str) -> None:
    now = time.time()
    with _LOGIN_LOCK:
        for key, _limit in _login_keys(username, ip):
            _LOGIN_FAILS.setdefault(key, []).append(now)


def _clear_login_failures(username: str) -> None:
    with _LOGIN_LOCK:
        _LOGIN_FAILS.pop("u:" + username.strip().lower(), None)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

class _CacheControlMiddleware:
    """Mark every response without its own Cache-Control as `no-store`.

    API responses carry per-user portfolio data and must never be cached by
    the browser, the service worker or Cloudflare. The static PWA mount sets
    its own header (see _PWAStaticFiles), so it is left alone.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                if "cache-control" not in headers:
                    headers["Cache-Control"] = "no-store"
            await send(message)

        await self.app(scope, receive, send_wrapper)


app = FastAPI(title="Stock Insights Portfolio Sync", version=SERVER_VERSION)
app.add_middleware(_CacheControlMiddleware)
# /trades for a long history is the largest payload; JSON compresses ~10x.
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- Auth dependencies -----------------------------------------------------

def _bearer(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing token")
    return auth[7:]


def current_user(token: str = Depends(_bearer)) -> dict:
    row = _get_user_from_token(token)
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    return {
        "user_id": int(row["user_id"]),
        "username": str(row["username"]),
        "is_admin": bool(row["is_admin"]),
    }


def admin_user(user: dict = Depends(current_user)) -> dict:
    if not user["is_admin"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin required")
    return user


def _resolve_uid(user: dict, for_user_id: Optional[int]) -> int:
    """Return the user id a request acts on; only admins may act for others."""
    if for_user_id is not None and for_user_id != user["user_id"]:
        if not user["is_admin"]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin required to access other users")
        return for_user_id
    return user["user_id"]


# ---- Pydantic models -------------------------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)
    is_admin: bool = False


class UpdatePasswordRequest(BaseModel):
    new_password: str = Field(min_length=1)


class AccountIn(BaseModel):
    name: str
    goal_target: float = 500_000.0
    goal_presets: List[float] = [250_000.0, 500_000.0, 1_000_000.0]
    position: int = 0


class AccountsUpdate(BaseModel):
    accounts: List[AccountIn]


class TradeIn(BaseModel):
    instrument: str
    share_count: int
    buy_price: float
    sell_price: Optional[float] = None
    open_date: Optional[str] = None
    close_date: Optional[str] = None
    notes: str = ""
    is_pending: bool = False
    is_short: bool = False


class TradesBatch(BaseModel):
    account_name: str
    trades: List[TradeIn]


class GoalGroupUpdate(BaseModel):
    account_names: List[str]
    shared_goal: float


class WatchlistUpdate(BaseModel):
    symbols: List[str]


# ---------------------------------------------------------------------------
# Health check  (no auth — surfaces version + db status to the client's
# status pill so the user can see "Server v1.2.3 · 12ms" at a glance)
# ---------------------------------------------------------------------------

# Every desktop client polls /health every few seconds and the route is
# public, so the DB probe result is reused for a few seconds instead of
# opening a SQL connection per hit.
_HEALTH_TTL_S = 5.0
_health_cache: Dict[str, Any] = {"at": 0.0, "db_ok": False}
_HEALTH_LOCK = Lock()


def _probe_db() -> bool:
    now = time.monotonic()
    with _HEALTH_LOCK:
        if now - _health_cache["at"] < _HEALTH_TTL_S:
            return _health_cache["db_ok"]
        try:
            with db() as conn:
                _exec(conn, "SELECT 1").fetchone()
            ok = True
        except Exception:
            # Full ODBC text (server name, login, driver) goes to the log
            # only — this endpoint is public.
            log.exception("Health check: database probe failed")
            ok = False
        _health_cache.update(at=time.monotonic(), db_ok=ok)
        return ok


@app.get("/health")
def health():
    """Liveness probe + version surface. Public; carries no sensitive data.

    Shape: {ok, server_version, uptime_seconds, db_ok, db_error}. Used by the
    desktop status pill (polled every few seconds) and external monitoring.
    """
    db_ok = _probe_db()
    return {
        "ok": db_ok,
        "server_version": SERVER_VERSION,
        "uptime_seconds": int(time.time() - _SERVER_BOOT_TIME),
        "db_ok": db_ok,
        "db_error": "" if db_ok else "database unavailable (see server log)",
    }


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.post("/auth/login")
def login(body: LoginRequest, request: Request):
    ip = _client_ip(request)
    if _login_blocked(body.username, ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            "Too many failed login attempts. Try again in a few minutes.")
    with db() as conn:
        cur = _exec(conn,
                    "SELECT id, username, password_hash, is_admin "
                    "FROM dbo.users WHERE username = ?",
                    body.username,
                    )
        user = _one(cur)
        stored = user["password_hash"] if user else _DUMMY_HASH
        if not _verify_password(body.password, stored) or user is None:
            _record_login_failure(body.username, ip)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
        token = _new_token()
        # Expired sessions are never read again; prune them here so the
        # table doesn't grow forever.
        _exec(conn, "DELETE FROM dbo.sessions WHERE expires_at < ?", _utc_now())
        _exec(conn,
              "INSERT INTO dbo.sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
              token, int(user["id"]), _token_expiry(),
              )
    _clear_login_failures(body.username)
    return {
        "token": token,
        "user_id": int(user["id"]),
        "username": str(user["username"]),
        "is_admin": bool(user["is_admin"]),
    }


@app.post("/auth/logout")
def logout(token: str = Depends(_bearer)):
    with db() as conn:
        _exec(conn, "DELETE FROM dbo.sessions WHERE token = ?", token)
    return {"ok": True}


@app.get("/auth/me")
def me(user: dict = Depends(current_user)):
    return user


# ---------------------------------------------------------------------------
# User management (admin only)
# ---------------------------------------------------------------------------

@app.get("/users")
def list_users(user: dict = Depends(admin_user)):
    with db() as conn:
        cur = _exec(conn,
                    "SELECT id, username, is_admin, created_at "
                    "FROM dbo.users ORDER BY id"
                    )
        rows = _all(cur)
    return rows


@app.post("/users", status_code=201)
def create_user(body: CreateUserRequest, user: dict = Depends(admin_user)):
    try:
        with db() as conn:
            _exec(conn,
                  "INSERT INTO dbo.users (username, password_hash, is_admin) VALUES (?, ?, ?)",
                  body.username, _hash_password(body.password), int(body.is_admin),
                  )
    except pyodbc.IntegrityError:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Username '{body.username}' already exists")
    return {"ok": True}


@app.put("/users/{user_id}/password")
def change_password(
        user_id: int, body: UpdatePasswordRequest,
        user: dict = Depends(current_user), token: str = Depends(_bearer),
):
    if user_id != user["user_id"] and not user["is_admin"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Cannot change another user's password")
    with db() as conn:
        _exec(conn,
              "UPDATE dbo.users SET password_hash = ? WHERE id = ?",
              _hash_password(body.new_password), user_id,
              )
        # A password change revokes every other session of that user (e.g. a
        # stolen token); the caller's own session survives.
        _exec(conn,
              "DELETE FROM dbo.sessions WHERE user_id = ? AND token <> ?",
              user_id, token,
              )
    return {"ok": True}


@app.delete("/users/{user_id}")
def delete_user(user_id: int, user: dict = Depends(admin_user)):
    if user_id == user["user_id"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot delete yourself")
    with db() as conn:
        _exec(conn, "DELETE FROM dbo.sessions WHERE user_id = ?", user_id)
        _exec(conn, "DELETE FROM dbo.users WHERE id = ?", user_id)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

@app.get("/accounts")
def get_accounts(user: dict = Depends(current_user), for_user_id: Optional[int] = None):
    uid = _resolve_uid(user, for_user_id)
    with db() as conn:
        cur = _exec(conn,
                    "SELECT id, name, goal_target, goal_presets, position "
                    "FROM dbo.accounts WHERE user_id = ? ORDER BY position, name",
                    uid,
                    )
        return _all(cur)


@app.put("/accounts")
def replace_accounts(
        body: AccountsUpdate,
        user: dict = Depends(current_user),
        for_user_id: Optional[int] = None,
):
    """Make the user's account list match `body` (order = list order).

    Accounts missing from the body are deleted (cascading to their trades),
    existing ones are updated in place so their trades survive.
    """
    uid = _resolve_uid(user, for_user_id)
    with db() as conn:
        cur = _exec(conn, "SELECT id, name FROM dbo.accounts WHERE user_id = ?", uid)
        existing = {r["name"]: r["id"] for r in _all(cur)}
        new_names = {a.name for a in body.accounts}

        removed = [(acct_id,) for name, acct_id in existing.items() if name not in new_names]
        updates, inserts = [], []
        for pos, acct in enumerate(body.accounts):
            presets = json.dumps(acct.goal_presets)
            if acct.name in existing:
                updates.append((acct.goal_target, presets, pos, existing[acct.name]))
            else:
                inserts.append((uid, acct.name, acct.goal_target, presets, pos))

        cur = conn.cursor()
        if removed:
            cur.executemany("DELETE FROM dbo.accounts WHERE id = ?", removed)
        if updates:
            cur.executemany(
                "UPDATE dbo.accounts SET goal_target = ?, goal_presets = ?, position = ? "
                "WHERE id = ?",
                updates,
            )
        if inserts:
            cur.executemany(
                "INSERT INTO dbo.accounts (user_id, name, goal_target, goal_presets, position) "
                "VALUES (?, ?, ?, ?, ?)",
                inserts,
            )
    return {"ok": True}


@app.put("/accounts/{account_name}/settings")
def update_account_settings(
        account_name: str, body: AccountIn,
        user: dict = Depends(current_user), for_user_id: Optional[int] = None,
):
    uid = _resolve_uid(user, for_user_id)
    with db() as conn:
        _exec(conn,
              "UPDATE dbo.accounts SET goal_target = ?, goal_presets = ? "
              "WHERE user_id = ? AND name = ?",
              body.goal_target, json.dumps(body.goal_presets), uid, account_name,
              )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Trades
# ---------------------------------------------------------------------------

@app.get("/trades")
def get_trades(user: dict = Depends(current_user), for_user_id: Optional[int] = None):
    uid = _resolve_uid(user, for_user_id)
    with db() as conn:
        cur = _exec(conn,
                    "SELECT t.id, a.name AS account, t.instrument, t.share_count, "
                    "       t.buy_price, t.sell_price, t.open_date, t.close_date, "
                    "       t.notes, t.is_pending, t.is_short "
                    "FROM dbo.trades t "
                    "JOIN dbo.accounts a ON a.id = t.account_id "
                    "WHERE a.user_id = ? "
                    "ORDER BY t.id",
                    uid,
                    )
        return _all(cur)


@app.put("/trades/{account_name}")
def replace_account_trades(
        account_name: str, body: TradesBatch,
        user: dict = Depends(current_user), for_user_id: Optional[int] = None,
):
    """Atomically replace all trades for one account (other accounts untouched).

    The account named in the URL is the one written; body.account_name is
    accepted for compatibility but ignored.
    """
    uid = _resolve_uid(user, for_user_id)
    with db() as conn:
        lookup = "SELECT id FROM dbo.accounts WHERE user_id = ? AND name = ?"
        acct_id = _scalar(_exec(conn, lookup, uid, account_name))
        if acct_id is None:
            # Auto-create the account if it doesn't exist yet. Re-select the
            # id instead of SCOPE_IDENTITY(): pyodbc runs each parameterised
            # execute() in its own scope, so a follow-up SCOPE_IDENTITY()
            # returns NULL.
            _exec(conn, "INSERT INTO dbo.accounts (user_id, name) VALUES (?, ?)",
                  uid, account_name)
            acct_id = _scalar(_exec(conn, lookup, uid, account_name))
        acct_id = int(acct_id)

        _exec(conn, "DELETE FROM dbo.trades WHERE account_id = ?", acct_id)

        if body.trades:
            cur2 = conn.cursor()
            cur2.executemany(
                "INSERT INTO dbo.trades "
                "(account_id, instrument, share_count, buy_price, "
                " sell_price, open_date, close_date, notes, is_pending, is_short) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        acct_id, t.instrument, t.share_count, t.buy_price,
                        t.sell_price, t.open_date, t.close_date, t.notes,
                        int(t.is_pending), int(t.is_short),
                    )
                    for t in body.trades
                ],
            )

    return {"ok": True}


# ---------------------------------------------------------------------------
# Goal group
# ---------------------------------------------------------------------------

@app.get("/goal-group")
def get_goal_group(user: dict = Depends(current_user), for_user_id: Optional[int] = None):
    uid = _resolve_uid(user, for_user_id)
    with db() as conn:
        cur = _exec(conn,
                    "SELECT account_names, shared_goal FROM dbo.goal_group WHERE user_id = ?", uid
                    )
        row = _one(cur)
    if row is None:
        return {"account_names": [], "shared_goal": 500_000.0}
    return {
        "account_names": json.loads(row["account_names"]),
        "shared_goal": float(row["shared_goal"]),
    }


@app.put("/goal-group")
def update_goal_group(
        body: GoalGroupUpdate,
        user: dict = Depends(current_user),
        for_user_id: Optional[int] = None,
):
    uid = _resolve_uid(user, for_user_id)
    names = json.dumps(body.account_names)
    with db() as conn:
        # UPDATE-then-INSERT: one round trip in the common case, and no
        # check-then-insert gap for two concurrent saves to race through.
        cur = _exec(conn,
                    "UPDATE dbo.goal_group SET account_names = ?, shared_goal = ? WHERE user_id = ?",
                    names, body.shared_goal, uid,
                    )
        if cur.rowcount == 0:
            _exec(conn,
                  "INSERT INTO dbo.goal_group (user_id, account_names, shared_goal) VALUES (?, ?, ?)",
                  uid, names, body.shared_goal,
                  )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------

@app.get("/watchlist")
def get_watchlist(user: dict = Depends(current_user), for_user_id: Optional[int] = None):
    uid = _resolve_uid(user, for_user_id)
    with db() as conn:
        cur = _exec(conn,
                    "SELECT symbol FROM dbo.watchlist WHERE user_id = ? ORDER BY position, symbol",
                    uid,
                    )
        return [r["symbol"] for r in _all(cur)]


@app.put("/watchlist")
def update_watchlist(
        body: WatchlistUpdate,
        user: dict = Depends(current_user),
        for_user_id: Optional[int] = None,
):
    uid = _resolve_uid(user, for_user_id)
    with db() as conn:
        _exec(conn, "DELETE FROM dbo.watchlist WHERE user_id = ?", uid)
        if body.symbols:
            cur2 = conn.cursor()
            cur2.executemany(
                "INSERT INTO dbo.watchlist (user_id, symbol, position) VALUES (?, ?, ?)",
                [(uid, sym, pos) for pos, sym in enumerate(body.symbols)],
            )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Quotes  (live prices for the mobile / web client)
# ---------------------------------------------------------------------------
#
# Primary source: Stooq — free, unauthenticated, one CSV request for all
# symbols, and not Yahoo (which keeps breaking yfinance). yfinance is the
# fallback for anything Stooq couldn't price (new IPOs, foreign listings).
#
# Results — including misses — are cached in-process for QUOTE_TTL seconds so
# rapid polling from the PWA doesn't spam either upstream, and an unpriceable
# symbol doesn't trigger a slow yfinance download on every poll.

try:
    import requests as _requests

    _REQ_OK = True
    _HTTP = _requests.Session()  # reuses the TLS connection to Stooq
except ImportError:
    _REQ_OK = False
    _HTTP = None

try:
    import yfinance as _yf

    _YF_OK = True
except ImportError:
    _YF_OK = False

_QUOTE_CACHE: Dict[str, tuple] = {}  # symbol -> (price_or_None, fetched_at)
_QUOTE_LOCK = Lock()
QUOTE_TTL = 20.0  # seconds
_MAX_QUOTE_SYMBOLS = 250
# Tickers like AAPL, BRK.B, BTC-USD, ^GSPC, EURUSD=X. Anything else is
# answered with null without reaching an upstream.
_SYMBOL_RE = re.compile(r"^[A-Z0-9.\-^=]{1,20}$")

_STOOQ_URL = "https://stooq.com/q/l/"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def _fetch_quotes_stooq(symbols: List[str]) -> Dict[str, Optional[float]]:
    """Batch-fetch latest prices from Stooq. Returns {symbol: price_or_None}.
    Stooq lists US equities with a `.us` suffix; we strip it on the way back."""
    out: Dict[str, Optional[float]] = {s: None for s in symbols}
    if not symbols or not _REQ_OK:
        return out

    params = {
        "s": ",".join(f"{s.lower()}.us" for s in symbols),
        "f": "sd2t2ohlcv",
        "h": "",
        "e": "csv",
    }
    try:
        resp = _HTTP.get(_STOOQ_URL, params=params, headers={"User-Agent": _UA}, timeout=10)
        resp.raise_for_status()
        text = resp.text
    except Exception as exc:
        log.warning("Stooq fetch failed: %s", exc)
        return out

    try:
        reader = csv.DictReader(io.StringIO(text))
        # Map normalized symbol -> original casing supplied by caller
        original_for = {s.upper(): s for s in symbols}
        for row in reader:
            # Stooq echoes "NVDA.US"; strip only that suffix so dotted
            # tickers like BRK.B still map back.
            raw = (row.get("Symbol") or "").upper()
            if raw.endswith(".US"):
                raw = raw[:-3]
            sym = original_for.get(raw)
            if not sym:
                continue
            close = (row.get("Close") or "").strip()
            if not close or close.upper() == "N/D":
                continue
            try:
                out[sym] = float(close)
            except ValueError:
                pass
    except csv.Error as exc:
        log.warning("Stooq CSV parse failed: %s", exc)

    missing = [s for s, v in out.items() if v is None]
    if missing:
        log.info("Stooq missing: %s", missing)
    return out


def _fetch_quotes_yfinance(symbols: List[str]) -> Dict[str, Optional[float]]:
    """Fallback fetcher — yfinance batch download. Returns {sym: price_or_None}.
    Only called for symbols Stooq couldn't price."""
    out: Dict[str, Optional[float]] = {s: None for s in symbols}
    if not symbols or not _YF_OK:
        return out
    try:
        df = _yf.download(
            tickers=symbols,
            interval="1m", period="1d",
            group_by="ticker",
            progress=False, threads=False,
        )
    except Exception as exc:
        log.warning("yfinance batch failed: %s", exc)
        return out
    if df is None or df.empty:
        return out

    # Newer yfinance returns (ticker, field) MultiIndex columns even for a
    # single ticker; older versions return flat columns for one ticker.
    multi = getattr(df.columns, "nlevels", 1) > 1
    tickers = set(df.columns.get_level_values(0)) if multi else set()
    for sym in symbols:
        try:
            if multi:
                if sym not in tickers:
                    continue
                close = df[sym]["Close"].dropna()
            else:
                close = df["Close"].dropna()
            if len(close):
                out[sym] = float(close.iloc[-1])
        except (KeyError, TypeError, ValueError) as exc:
            log.info("yfinance: no price for %s (%s)", sym, exc)
    return out


@app.get("/quotes")
def get_quotes(symbols: str = "", user: dict = Depends(current_user)):
    """Return {symbol: price_or_null} for a comma-separated symbol list.

    Auth-gated so anonymous traffic can't drive up our upstream usage.
    Cached in-process for QUOTE_TTL seconds per symbol. Tries Stooq first,
    then falls back to yfinance for anything Stooq couldn't price.
    """
    if not _REQ_OK and not _YF_OK:
        raise HTTPException(503, "Neither requests nor yfinance is installed")

    requested = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    requested = list(dict.fromkeys(requested))  # de-dupe, preserve order
    if not requested:
        return {}
    if len(requested) > _MAX_QUOTE_SYMBOLS:
        raise HTTPException(400, f"At most {_MAX_QUOTE_SYMBOLS} symbols per request")

    now = time.time()
    out: Dict[str, Optional[float]] = {}
    to_fetch: List[str] = []

    with _QUOTE_LOCK:
        for sym in requested:
            if not _SYMBOL_RE.match(sym):
                out[sym] = None
                continue
            cached = _QUOTE_CACHE.get(sym)
            if cached and (now - cached[1]) < QUOTE_TTL:
                out[sym] = cached[0]
            else:
                to_fetch.append(sym)

    # Fetch outside the lock so concurrent requests don't block on one another.
    fresh: Dict[str, Optional[float]] = {}
    if to_fetch:
        fresh = _fetch_quotes_stooq(to_fetch)
        still_missing = [s for s, v in fresh.items() if v is None]
        if still_missing and _YF_OK:
            for sym, price in _fetch_quotes_yfinance(still_missing).items():
                if price is not None:
                    fresh[sym] = price

    with _QUOTE_LOCK:
        for sym, price in fresh.items():
            _QUOTE_CACHE[sym] = (price, now)
            out[sym] = price

    # Preserve request order in the response.
    return {sym: out.get(sym) for sym in requested}


# ---------------------------------------------------------------------------
# Static files — serve the mobile PWA from the same origin
# ---------------------------------------------------------------------------
#
# Layout assumed:
#     StockInsights/
#         server/server.py    (this file)
#         pwa/                (mobile PWA — index.html, js/, etc.)
#
# Override with PORTFOLIO_PWA_DIR if your layout differs. The mount is
# conditional — if the directory doesn't exist, the API still works, you
# just won't be able to load the PWA from this server.
#
# IMPORTANT: this mount MUST be the last route registered. StaticFiles
# at "/" catches every path that hasn't already matched, so anything
# below it would be unreachable.

class _PWAStaticFiles(StaticFiles):
    """StaticFiles that hides non-app files and sets revalidation headers.

    The pwa/ folder also holds helper scripts and docs (*.py, *.md) that
    should not be downloadable from the public tunnel. File names aren't
    content-hashed, so everything is served `no-cache`: the browser keeps a
    copy but revalidates with ETag/Last-Modified (a cheap 304). The service
    worker's own versioned cache handles offline use.
    """

    _HIDDEN_SUFFIXES = {".py", ".pyc", ".md"}

    async def get_response(self, path: str, scope) -> Any:
        p = pathlib.PurePosixPath(path)
        if p.suffix.lower() in self._HIDDEN_SUFFIXES or any(
                part.startswith(".") or part == "__pycache__" for part in p.parts):
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        response = await super().get_response(path, scope)
        response.headers.setdefault("Cache-Control", "no-cache")
        return response


_PWA_DIR = pathlib.Path(os.environ.get(
    "PORTFOLIO_PWA_DIR",
    str(pathlib.Path(__file__).resolve().parent.parent / "pwa"),
))
_PWA_MOUNTED = False
if _PWA_DIR.is_dir():
    # html=True makes "/" serve "/index.html" automatically.
    app.mount("/", _PWAStaticFiles(directory=str(_PWA_DIR), html=True), name="pwa")
    _PWA_MOUNTED = True


# ---------------------------------------------------------------------------
# Connection test (called at startup)
# ---------------------------------------------------------------------------

def _test_connection() -> int:
    """Verify we can reach SQL Server and the schema exists; return user count."""
    try:
        with db() as conn:
            count = _scalar(_exec(conn, "SELECT COUNT(*) FROM dbo.users")) or 0
        return int(count)
    except Exception as exc:
        print(f"\n[ERROR] Cannot connect to SQL Server: {exc}")
        print("Check PORTFOLIO_SQL_SERVER / PORTFOLIO_SQL_USER / PORTFOLIO_SQL_PASSWORD.")
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# Setup CLI  (create first admin account)
# ---------------------------------------------------------------------------

def setup_admin():
    _test_connection()
    print("\n=== Stock Insights — First-time Setup ===")
    username = input("Username: ").strip()
    password = getpass.getpass("Password: ").strip()  # not echoed
    admin_rights = input("Admin rights? (Y/N): ").strip().upper()
    if not username or not password or not admin_rights:
        print("Cancelled.")
        return
    try:
        with db() as conn:
            _exec(conn,
                  "INSERT INTO dbo.users (username, password_hash, is_admin) VALUES (?, ?, ?)",
                  username, _hash_password(password), int(admin_rights == "Y"),
                  )
        print(f"\nUser '{username}' created. Start the server with: python server.py\n")
    except pyodbc.IntegrityError:
        print(f"User '{username}' already exists.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Stock Insights Portfolio Sync Server")
    parser.add_argument("--setup", action="store_true", help="Create initial admin account and exit")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()

    if args.setup:
        setup_admin()
    else:
        user_count = _test_connection()
        print(f"\nStock Insights Portfolio Server  (SQL Server edition)")
        print(f"SQL Server : {SQL_SERVER}  /  {SQL_DATABASE}")
        print(f"Listening  : http://{args.host}:{args.port}")
        print(f"API docs   : http://localhost:{args.port}/docs")
        if _PWA_MOUNTED:
            print(f"Mobile PWA : http://localhost:{args.port}/   (from {_PWA_DIR})")
        else:
            print(f"Mobile PWA : NOT MOUNTED — directory not found at {_PWA_DIR}")
        print(f"Users      : {user_count} registered\n")

        if user_count == 0:
            print("WARNING: No users exist. Run 'python server.py --setup' first.\n")

        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
