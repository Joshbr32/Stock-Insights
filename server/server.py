#!/usr/bin/env python3
r"""Stock Insights — Portfolio Sync Server (SQL Server edition).

Prerequisites on COLONIAL_SERVER
─────────────────────────────────
1.  Run init_stockinsights.sql in SSMS to create the DB, login, and tables.
2.  Install Python deps:
        pip install fastapi uvicorn pyodbc
3.  Set environment variables (or edit the defaults below):
        PORTFOLIO_SQL_SERVER    e.g. localhost\STOCKINSIGHTS  (default)
        PORTFOLIO_SQL_DATABASE  e.g. StockInsights            (default)
        PORTFOLIO_SQL_USER      e.g. stock_app                (default)
        PORTFOLIO_SQL_PASSWORD  your login password           (required)
        PORTFOLIO_HOST          0.0.0.0                       (default)
        PORTFOLIO_PORT          8742                          (default)
4.  First-time: create an admin account:
        python server.py --setup
5.  Run:
        python server.py

Other devices on your network (or via external IP 66.225.151.13) connect
to http://COLONIAL_SERVER:8742  —  SQL Server itself does NOT need to be
exposed externally; only port 8742 does.
"""

import argparse
import hashlib
import json
import mimetypes
import os
import pathlib
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

# Python's mimetypes db doesn't know .webmanifest by default; some browsers
# refuse to install a PWA without the right Content-Type. Register it once.
mimetypes.add_type("application/manifest+json", ".webmanifest")

# ---------------------------------------------------------------------------
# Load .env (if present) BEFORE we read any PORTFOLIO_* env vars.
#
# python-dotenv is listed in server/requirements.txt — installing it is
# the recommended setup so you can drop the SQL password into a local
# .env file and forget about it. If it's not installed (e.g. someone is
# poking at the script in isolation) we silently fall back to real env
# vars; existing deployments that already export PORTFOLIO_SQL_PASSWORD
# in the shell continue to work unchanged.
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv

    # Look for .env next to server.py (the canonical location), but don't
    # walk up the tree — we don't want to accidentally pick up an unrelated
    # .env from the project root or a parent folder.
    _ENV_FILE = pathlib.Path(__file__).resolve().parent / ".env"
    if _ENV_FILE.exists():
        load_dotenv(_ENV_FILE, override=False)
except ImportError:
    # dotenv missing — keep going; either the user is running with shell
    # env vars set manually, or the SQL_PASSWORD check below will fail
    # with a clear error message that points at the right fix.
    pass

# ---------------------------------------------------------------------------
# Optional dependency guards
# ---------------------------------------------------------------------------
try:
    import pyodbc
except ImportError:
    print("\nMissing dependency: pyodbc")
    print("Install with:  pip install pyodbc\n")
    raise SystemExit(1)

try:
    import uvicorn
    from fastapi import Depends, FastAPI, HTTPException, Request, status
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel
except ImportError as _e:
    print(f"\nMissing dependency: {_e}")
    print("Install with:  pip install fastapi uvicorn\n")
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
TOKEN_DAYS = 30


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


def _conn_string() -> str:
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
    """Fetch a single scalar value (e.g. SCOPE_IDENTITY())."""
    row = cursor.fetchone()
    return row[0] if row else None


def _exec(conn, sql: str, *params):
    """Execute a statement and return the cursor."""
    cur = conn.cursor()
    cur.execute(sql, params)
    return cur


def _last_id(conn) -> int:
    """Return the identity value inserted by the last INSERT on this connection."""
    cur = conn.cursor()
    cur.execute("SELECT SCOPE_IDENTITY()")
    return int(_scalar(cur) or 0)


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
    return f"{salt}:{dk.hex()}"


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt, dk_hex = stored_hash.split(":", 1)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
        return secrets.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


def _new_token() -> str:
    return secrets.token_hex(32)  # 64 hex chars — fits NVARCHAR(64)


def _token_expiry() -> str:
    return (datetime.utcnow() + timedelta(days=TOKEN_DAYS)).strftime("%Y-%m-%dT%H:%M:%S")


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
    if expiry < datetime.utcnow():
        return None
    return row


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="Stock Insights Portfolio Sync", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
    username: str
    password: str
    is_admin: bool = False


class UpdatePasswordRequest(BaseModel):
    new_password: str


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

# Single source of truth for the server-side version. Bump alongside the
# desktop's stock_insights/version.py when you ship coordinated changes
# (new endpoints, schema migrations, etc.). Independent of APP_VERSION
# because server + desktop can update on different cadences.
SERVER_VERSION = "1.0.0"
import time as _time

_SERVER_BOOT_TIME = _time.time()


@app.get("/health")
def health():
    """Lightweight liveness probe + version surface.

    Returns the server version, process uptime, and whether a quick SQL
    Server SELECT succeeds. Used by the desktop's status pill (polled
    every few seconds) and by external monitoring (the response is the
    same shape both consumers can parse).

    No auth — the response carries no sensitive data, and requiring a
    token would defeat the point of a network-edge health check.
    """
    db_ok = False
    db_error = ""
    try:
        with db() as conn:
            cur = _exec(conn, "SELECT 1")
            cur.fetchone()
            db_ok = True
    except Exception as exc:
        db_error = str(exc)[:200]  # truncate so a verbose ODBC error doesn't bloat the response

    return {
        "ok": db_ok,
        "server_version": SERVER_VERSION,
        "uptime_seconds": int(_time.time() - _SERVER_BOOT_TIME),
        "db_ok": db_ok,
        "db_error": db_error if not db_ok else "",
    }


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.post("/auth/login")
def login(body: LoginRequest):
    with db() as conn:
        cur = _exec(conn,
                    "SELECT id, username, password_hash, is_admin "
                    "FROM dbo.users WHERE username = ?",
                    body.username,
                    )
        user = _one(cur)
    if user is None or not _verify_password(body.password, user["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    token = _new_token()
    with db() as conn:
        _exec(conn,
              "INSERT INTO dbo.sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
              token, int(user["id"]), _token_expiry(),
              )
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
def change_password(user_id: int, body: UpdatePasswordRequest, user: dict = Depends(current_user)):
    if user_id != user["user_id"] and not user["is_admin"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Cannot change another user's password")
    with db() as conn:
        _exec(conn,
              "UPDATE dbo.users SET password_hash = ? WHERE id = ?",
              _hash_password(body.new_password), user_id,
              )
    return {"ok": True}


@app.delete("/users/{user_id}")
def delete_user(user_id: int, user: dict = Depends(admin_user)):
    if user_id == user["user_id"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot delete yourself")
    with db() as conn:
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
    uid = _resolve_uid(user, for_user_id)
    with db() as conn:
        # Fetch existing accounts
        cur = _exec(conn, "SELECT id, name FROM dbo.accounts WHERE user_id = ?", uid)
        existing = {r["name"]: r["id"] for r in _all(cur)}
        new_names = {a.name for a in body.accounts}

        # Delete removed accounts (cascades to trades)
        for name, acct_id in existing.items():
            if name not in new_names:
                _exec(conn, "DELETE FROM dbo.accounts WHERE id = ?", acct_id)

        # Insert or update remaining
        for pos, acct in enumerate(body.accounts):
            if acct.name in existing:
                _exec(conn,
                      "UPDATE dbo.accounts SET goal_target = ?, goal_presets = ?, position = ? "
                      "WHERE id = ?",
                      acct.goal_target, json.dumps(acct.goal_presets),
                      pos, existing[acct.name],
                      )
            else:
                _exec(conn,
                      "INSERT INTO dbo.accounts (user_id, name, goal_target, goal_presets, position) "
                      "VALUES (?, ?, ?, ?, ?)",
                      uid, acct.name, acct.goal_target,
                      json.dumps(acct.goal_presets), pos,
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
    """Atomically replace all trades for one account (other accounts untouched)."""
    uid = _resolve_uid(user, for_user_id)
    with db() as conn:
        cur = _exec(conn,
                    "SELECT id FROM dbo.accounts WHERE user_id = ? AND name = ?",
                    uid, account_name,
                    )
        row = _one(cur)
        if row is None:
            # Auto-create the account if it doesn't exist yet
            _exec(conn,
                  "INSERT INTO dbo.accounts (user_id, name) VALUES (?, ?)",
                  uid, account_name,
                  )
            acct_id = _last_id(conn)
        else:
            acct_id = int(row["id"])

        # Delete existing trades for this account
        _exec(conn, "DELETE FROM dbo.trades WHERE account_id = ?", acct_id)

        # Bulk insert new trades
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
    with db() as conn:
        # Check existence first, then INSERT or UPDATE
        cur = _exec(conn, "SELECT 1 FROM dbo.goal_group WHERE user_id = ?", uid)
        exists = cur.fetchone() is not None
        if exists:
            _exec(conn,
                  "UPDATE dbo.goal_group SET account_names = ?, shared_goal = ? WHERE user_id = ?",
                  json.dumps(body.account_names), body.shared_goal, uid,
                  )
        else:
            _exec(conn,
                  "INSERT INTO dbo.goal_group (user_id, account_names, shared_goal) VALUES (?, ?, ?)",
                  uid, json.dumps(body.account_names), body.shared_goal,
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
# Primary source: Stooq. Free, unauthenticated, reliable, and crucially —
# not Yahoo, which has been actively breaking yfinance for the past year.
# Stooq returns CSV directly, so we hit them once with all symbols and
# parse the result. yfinance is kept as a fallback for any symbol Stooq
# couldn't price (e.g. very new IPOs, foreign exchanges).
#
# Results are cached in-process for QUOTE_TTL seconds so rapid-fire
# polling from the PWA doesn't spam either upstream.

import csv
import io
import time
from threading import Lock

try:
    import requests as _requests

    _REQ_OK = True
except ImportError:
    _REQ_OK = False

try:
    import yfinance as _yf

    _YF_OK = True
except ImportError:
    _YF_OK = False

_QUOTE_CACHE: Dict[str, tuple] = {}  # symbol -> (price, fetched_at)
_QUOTE_LOCK = Lock()
QUOTE_TTL = 20.0  # seconds

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
        resp = _requests.get(
            _STOOQ_URL, params=params,
            headers={"User-Agent": _UA},
            timeout=10,
        )
        resp.raise_for_status()
        text = resp.text
    except Exception as exc:
        print(f"[quotes] Stooq fetch failed: {exc}")
        return out

    try:
        reader = csv.DictReader(io.StringIO(text))
        # Map normalized symbol -> original casing supplied by caller
        original_for = {s.upper(): s for s in symbols}
        for row in reader:
            # Stooq returns "NVDA.US" — strip the suffix
            raw = (row.get("Symbol") or "").upper().split(".")[0]
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
    except Exception as exc:
        print(f"[quotes] Stooq CSV parse failed: {exc}")

    missing = [s for s, v in out.items() if v is None]
    if missing:
        print(f"[quotes] Stooq missing: {missing}")
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
        print(f"[quotes] yfinance batch failed: {exc}")
        return out

    for sym in symbols:
        try:
            sub = df[sym] if (len(symbols) > 1 and sym in df) else df
            close = sub["Close"].dropna()
            if len(close):
                out[sym] = float(close.iloc[-1])
        except Exception:
            pass
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

    now = time.time()
    out: Dict[str, Optional[float]] = {}
    to_fetch: List[str] = []

    with _QUOTE_LOCK:
        for sym in requested:
            cached = _QUOTE_CACHE.get(sym)
            if cached and (now - cached[1]) < QUOTE_TTL:
                out[sym] = cached[0]
            else:
                to_fetch.append(sym)

    # Fetch outside the lock so concurrent requests don't block on one another.
    fresh: Dict[str, Optional[float]] = {}
    if to_fetch:
        # Primary: Stooq
        fresh = _fetch_quotes_stooq(to_fetch)
        # Fallback: yfinance for any symbol Stooq couldn't price
        still_missing = [s for s, v in fresh.items() if v is None]
        if still_missing and _YF_OK:
            yf_results = _fetch_quotes_yfinance(still_missing)
            for sym, price in yf_results.items():
                if price is not None:
                    fresh[sym] = price

    with _QUOTE_LOCK:
        for sym, price in fresh.items():
            if price is not None:
                _QUOTE_CACHE[sym] = (price, now)
            out[sym] = price

    return out


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

_PWA_DIR = pathlib.Path(os.environ.get(
    "PORTFOLIO_PWA_DIR",
    str(pathlib.Path(__file__).resolve().parent.parent / "pwa"),
))
_PWA_MOUNTED = False
if _PWA_DIR.is_dir():
    # html=True makes "/" serve "/index.html" automatically.
    app.mount("/", StaticFiles(directory=str(_PWA_DIR), html=True), name="pwa")
    _PWA_MOUNTED = True


# ---------------------------------------------------------------------------
# Connection test (called at startup)
# ---------------------------------------------------------------------------

def _test_connection():
    """Verify we can reach SQL Server and the schema exists."""
    try:
        with db() as conn:
            cur = _exec(conn, "SELECT COUNT(*) FROM dbo.users")
            count = _scalar(cur) or 0
        return int(count)
    except Exception as exc:
        print(f"\n[ERROR] Cannot connect to SQL Server: {exc}")
        print("Check SQL_SERVER / SQL_USER / SQL_PASSWORD environment variables.")
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# Setup CLI  (create first admin account)
# ---------------------------------------------------------------------------

def setup_admin():
    _test_connection()
    print("\n=== Stock Insights — First-time Setup ===")
    username = input("Username: ").strip()
    password = input("Password: ").strip()
    admin_rights = input("Admin rights? (Y/N): ").strip().upper()
    if not username or not password or not admin_rights:
        print("Cancelled.");
        return
    try:
        with db() as conn:
            if admin_rights == "Y":
                _exec(conn,
                      "INSERT INTO dbo.users (username, password_hash, is_admin) VALUES (?, ?, 1)",
                      username, _hash_password(password),
                      )
            else:
                _exec(conn,
                      "INSERT INTO dbo.users (username, password_hash, is_admin) VALUES (?, ?, 0)",
                      username, _hash_password(password),
                      )
        print(f"\nUser '{username}' created. Start the server with: python server.py\n")
    except pyodbc.IntegrityError:
        print(f"User '{username}' already exists.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
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
