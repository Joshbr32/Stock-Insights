"""api_client.py — DataStore abstraction and remote HTTP client.

DataStore
─────────
Abstract base class for all data access.  PortfolioTab and MainWindow
use DataStore methods; they don't care whether data lives on the remote
server or locally in QSettings.

RemoteDataStore   — talks to the FastAPI server over HTTP.
LocalDataStore    — falls back to QSettings (device-local, no sync).
"""

from __future__ import annotations

import json
import threading
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

try:
    import requests

    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

from PySide6.QtCore import QSettings

from .portfolio import Trade, trades_from_json, trades_to_json


# ---------------------------------------------------------------------------
# DataStore ABC
# ---------------------------------------------------------------------------

class DataStore(ABC):
    """Abstract interface for all user-data persistence."""

    # ---- Trades ----
    @abstractmethod
    def get_all_trades(self) -> List[Trade]:
        """Return all trades for all accounts belonging to this user."""

    @abstractmethod
    def save_account_trades(self, account_name: str, trades: List[Trade]) -> None:
        """Replace all trades for a single account (other accounts unchanged)."""

    # ---- Accounts ----
    @abstractmethod
    def get_account_names(self) -> List[str]:
        ...

    @abstractmethod
    def save_accounts(self, accounts: List[str]) -> None:
        """Save account list (names only; settings preserved where possible)."""

    # ---- Goal targets & presets ----
    @abstractmethod
    def get_goal_target(self, account_name: str) -> float:
        ...

    @abstractmethod
    def set_goal_target(self, account_name: str, value: float) -> None:
        ...

    @abstractmethod
    def get_goal_presets(self, account_name: str) -> List[float]:
        ...

    @abstractmethod
    def set_goal_presets(self, account_name: str, presets: List[float]) -> None:
        ...

    # ---- Goal group (shared tracking) ----
    @abstractmethod
    def get_goal_group(self) -> Tuple[List[str], float]:
        """Return (shared_account_names, shared_goal_target)."""

    @abstractmethod
    def set_goal_group(
            self,
            shared_accounts: List[str],
            shared_goal: float,
            individual_goals: Dict[str, float],
            individual_presets: Dict[str, List[float]],
    ) -> None:
        ...

    # ---- Watchlist ----
    @abstractmethod
    def get_watchlist(self) -> List[str]:
        ...

    @abstractmethod
    def save_watchlist(self, symbols: List[str]) -> None:
        ...

    # ---- Identity ----
    @property
    @abstractmethod
    def user_info(self) -> dict:
        """Return {user_id, username, is_admin}."""

    @property
    def is_admin(self) -> bool:
        return bool(self.user_info.get("is_admin", False))

    @property
    def username(self) -> str:
        return str(self.user_info.get("username", ""))


# ---------------------------------------------------------------------------
# RemoteDataStore — connects to server.py over HTTP
# ---------------------------------------------------------------------------

class APIError(Exception):
    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


class RemoteDataStore(DataStore):
    """DataStore backed by the FastAPI server.

    Parameters
    ----------
    base_url : e.g. 'http://192.168.1.10:8742'
    token    : Bearer token obtained from /auth/login
    user_info_dict : dict returned by /auth/login {user_id, username, is_admin}
    for_user_id : if set (admin use), all requests proxy for this user_id
    """

    def __init__(
            self,
            base_url: str,
            token: str,
            user_info_dict: dict,
            for_user_id: Optional[int] = None,
    ):
        if not _REQUESTS_OK:
            raise ImportError("Install 'requests':  pip install requests")
        self._base = base_url.rstrip("/")
        self._token = token
        self._user_info = user_info_dict
        self._for_user_id = for_user_id
        self._lock = threading.Lock()

        # Local cache to reduce round-trips
        self._account_cache: Optional[List[dict]] = None  # [{name, goal_target, goal_presets}]
        self._trade_cache: Optional[List[Trade]] = None
        self._goal_group_cache: Optional[Tuple[List[str], float]] = None

    # ---- internal ----

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"}

    def _params(self) -> dict:
        return {"for_user_id": self._for_user_id} if self._for_user_id else {}

    def _get(self, path: str) -> Any:
        r = requests.get(f"{self._base}{path}", headers=self._headers(), params=self._params(), timeout=10)
        if not r.ok:
            raise APIError(r.text, r.status_code)
        return r.json()

    def _put(self, path: str, data: dict) -> Any:
        r = requests.put(
            f"{self._base}{path}", json=data,
            headers=self._headers(), params=self._params(), timeout=10
        )
        if not r.ok:
            raise APIError(r.text, r.status_code)
        return r.json()

    def _invalidate_trades(self):
        self._trade_cache = None

    def _invalidate_accounts(self):
        self._account_cache = None

    def _get_account_data(self) -> List[dict]:
        if self._account_cache is None:
            self._account_cache = self._get("/accounts")
        return self._account_cache

    # ---- DataStore implementation ----

    @property
    def user_info(self) -> dict:
        return self._user_info

    def get_all_trades(self) -> List[Trade]:
        with self._lock:
            if self._trade_cache is None:
                rows = self._get("/trades")
                trades = []
                for r in rows:
                    trades.append(Trade(
                        instrument=r["instrument"],
                        share_count=int(r["share_count"]),
                        buy_price=float(r["buy_price"]),
                        sell_price=None if r["sell_price"] is None else float(r["sell_price"]),
                        open_date=_parse_date_str(r.get("open_date")),
                        close_date=_parse_date_str(r.get("close_date")),
                        notes=str(r.get("notes") or ""),
                        account=str(r.get("account") or ""),
                        is_pending=bool(r.get("is_pending", False)),
                        is_short=bool(r.get("is_short", False)),
                    ))
                self._trade_cache = trades
            return list(self._trade_cache)

    def save_account_trades(self, account_name: str, trades: List[Trade]) -> None:
        payload = {
            "account_name": account_name,
            "trades": [
                {
                    "instrument": t.normalized_instrument(),
                    "share_count": int(t.share_count),
                    "buy_price": float(t.buy_price),
                    "sell_price": None if t.sell_price is None else float(t.sell_price),
                    "open_date": t.open_date.isoformat() if t.open_date else None,
                    "close_date": t.close_date.isoformat() if t.close_date else None,
                    "notes": t.notes or "",
                    "is_pending": bool(t.is_pending),
                    "is_short": bool(t.is_short),
                }
                for t in trades
            ]
        }
        self._put(f"/trades/{account_name}", payload)
        self._invalidate_trades()

    def get_account_names(self) -> List[str]:
        return [a["name"] for a in self._get_account_data()]

    def save_accounts(self, accounts: List[str]) -> None:
        existing = {a["name"]: a for a in self._get_account_data()}
        payload_accounts = []
        for pos, name in enumerate(accounts):
            ex = existing.get(name, {})
            payload_accounts.append({
                "name": name,
                "goal_target": float(ex.get("goal_target", 500_000.0)),
                "goal_presets": _parse_presets(ex.get("goal_presets", None)),
                "position": pos,
            })
        self._put("/accounts", {"accounts": payload_accounts})
        self._invalidate_accounts()

    def get_goal_target(self, account_name: str) -> float:
        for a in self._get_account_data():
            if a["name"] == account_name:
                return float(a.get("goal_target", 500_000.0))
        return 500_000.0

    def set_goal_target(self, account_name: str, value: float) -> None:
        presets = self.get_goal_presets(account_name)
        self._put(f"/accounts/{account_name}/settings", {
            "name": account_name, "goal_target": float(value),
            "goal_presets": presets, "position": 0,
        })
        self._invalidate_accounts()

    def get_goal_presets(self, account_name: str) -> List[float]:
        for a in self._get_account_data():
            if a["name"] == account_name:
                return _parse_presets(a.get("goal_presets", None))
        return [250_000.0, 500_000.0, 1_000_000.0]

    def set_goal_presets(self, account_name: str, presets: List[float]) -> None:
        target = self.get_goal_target(account_name)
        self._put(f"/accounts/{account_name}/settings", {
            "name": account_name, "goal_target": target,
            "goal_presets": [float(p) for p in presets], "position": 0,
        })
        self._invalidate_accounts()

    def get_goal_group(self) -> Tuple[List[str], float]:
        if self._goal_group_cache is None:
            data = self._get("/goal-group")
            self._goal_group_cache = (data.get("account_names", []), float(data.get("shared_goal", 500_000.0)))
        return self._goal_group_cache

    def set_goal_group(
            self,
            shared_accounts: List[str],
            shared_goal: float,
            individual_goals: Dict[str, float],
            individual_presets: Dict[str, List[float]],
    ) -> None:
        self._put("/goal-group", {"account_names": shared_accounts, "shared_goal": float(shared_goal)})
        self._goal_group_cache = None
        # Persist individual targets and presets
        for account, goal in individual_goals.items():
            presets = individual_presets.get(account, self.get_goal_presets(account))
            self._put(f"/accounts/{account}/settings", {
                "name": account, "goal_target": float(goal),
                "goal_presets": presets, "position": 0,
            })
        # Persist shared goal for all shared accounts
        for account in shared_accounts:
            presets = individual_presets.get(account, self.get_goal_presets(account))
            self._put(f"/accounts/{account}/settings", {
                "name": account, "goal_target": float(shared_goal),
                "goal_presets": presets, "position": 0,
            })
        self._invalidate_accounts()

    def get_watchlist(self) -> List[str]:
        return self._get("/watchlist")

    def save_watchlist(self, symbols: List[str]) -> None:
        self._put("/watchlist", {"symbols": symbols})

    # ---- Admin-only: create a view-only store for another user ----

    def store_for_user(self, user_id: int, username: str) -> "RemoteDataStore":
        """Return a read-only-capable DataStore scoped to another user (admin use)."""
        return RemoteDataStore(
            base_url=self._base,
            token=self._token,
            user_info_dict={"user_id": user_id, "username": username, "is_admin": False},
            for_user_id=user_id,
        )

    def list_users(self) -> List[dict]:
        """Admin: list all users."""
        r = requests.get(f"{self._base}/users", headers=self._headers(), timeout=10)
        if not r.ok:
            raise APIError(r.text, r.status_code)
        return r.json()

    # ---- Health probe (used by the status pill) -----------------------

    def ping_health(self) -> dict:
        """Lightweight liveness probe.

        Returns a dict shaped like:
            {
                "ok": True/False,
                "latency_ms": <int>,
                "server_version": "1.2.3",   # only on success
                "uptime_seconds": 12345,     # only on success
                "db_ok": True/False,         # only on success
                "error": "...",              # only on failure
            }

        Short timeout (3s) because this is called on a polling loop —
        we'd rather report "server slow" via a stale-ish version field
        than block the worker on a 30s hang. Never raises; surfaces
        every failure mode via the `ok` flag so the caller's UI logic
        stays simple.
        """
        import time
        t0 = time.monotonic()
        try:
            # No auth header — /health is intentionally public.
            r = requests.get(f"{self._base}/health", timeout=3)
            latency_ms = int((time.monotonic() - t0) * 1000)
            if not r.ok:
                return {"ok": False, "latency_ms": latency_ms,
                        "error": f"HTTP {r.status_code}"}
            data = r.json()
            data["ok"] = bool(data.get("ok", False))
            data["latency_ms"] = latency_ms
            return data
        except requests.exceptions.Timeout:
            return {"ok": False, "latency_ms": int((time.monotonic() - t0) * 1000),
                    "error": "timeout"}
        except Exception as exc:
            return {"ok": False, "latency_ms": int((time.monotonic() - t0) * 1000),
                    "error": str(exc)[:120]}


# ---------------------------------------------------------------------------
# LocalDataStore — QSettings fallback (offline / no server)
# ---------------------------------------------------------------------------

class LocalDataStore(DataStore):
    """DataStore backed by QSettings — matches the pre-server behaviour exactly."""

    ORG = "StockInsights"
    APP = "StocksGUI"

    TRADES_KEY = "portfolio/trades"
    GOAL_GROUP_KEY = "portfolio/goal_dashboard_accounts"
    GOAL_GROUP_SHARED_KEY = "portfolio/goal_dashboard_shared_goal"
    ACCOUNTS_KEY = "user_account/accounts"

    def __init__(self, username: str = "local"):
        self._settings = QSettings(self.ORG, self.APP)
        self._username = username
        self._scope_prefix = f"user_cache/{_scope_username(username)}"

    def _scoped_key(self, key: str) -> str:
        return f"{self._scope_prefix}/{key}"

    @property
    def user_info(self) -> dict:
        return {"user_id": 0, "username": self._username, "is_admin": False}

    def get_all_trades(self) -> List[Trade]:
        return trades_from_json(self._settings.value(self._scoped_key(self.TRADES_KEY), []))

    def save_account_trades(self, account_name: str, trades: List[Trade]) -> None:
        # Read all trades, replace the slice for this account, write back
        all_trades = self.get_all_trades()
        kept = [t for t in all_trades if (t.account or "").strip() != account_name]
        combined = kept + list(trades)
        self._settings.setValue(self._scoped_key(self.TRADES_KEY), trades_to_json(combined))
        self._settings.sync()

    def get_account_names(self) -> List[str]:
        raw = self._settings.value(self._scoped_key(self.ACCOUNTS_KEY), ["Default"])
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = [x.strip() for x in raw.split(",") if x.strip()]
        if not isinstance(raw, list): raw = ["Default"]
        out, seen = [], set()
        for item in raw:
            name = str(item or "").strip()
            if name and name not in seen:
                seen.add(name);
                out.append(name)
        return out or ["Default"]

    def save_accounts(self, accounts: List[str]) -> None:
        existing_accounts = set(self.get_account_names())
        normalized_accounts = []
        seen = set()
        for item in accounts:
            name = str(item or "").strip()
            if name and name not in seen:
                seen.add(name)
                normalized_accounts.append(name)
        allowed_accounts = set(normalized_accounts)

        all_trades = self.get_all_trades()
        kept_trades = [t for t in all_trades if (t.account or "").strip() in allowed_accounts]
        self._settings.setValue(self._scoped_key(self.TRADES_KEY), trades_to_json(kept_trades))
        self._settings.setValue(self._scoped_key(self.ACCOUNTS_KEY), json.dumps(normalized_accounts))

        shared_accounts, shared_goal = self.get_goal_group()
        filtered_shared = [name for name in shared_accounts if name in allowed_accounts]
        self._settings.setValue(self._scoped_key(self.GOAL_GROUP_KEY), json.dumps(filtered_shared))
        self._settings.setValue(self._scoped_key(self.GOAL_GROUP_SHARED_KEY), float(shared_goal))

        removed_accounts = existing_accounts - allowed_accounts
        for account in removed_accounts:
            self._settings.remove(self._scoped_key(f"portfolio/goal_target/{account}"))
            self._settings.remove(self._scoped_key(f"goals/presets/{account}"))
        self._settings.sync()

    def get_goal_target(self, account_name: str) -> float:
        try:
            return float(
                self._settings.value(
                    self._scoped_key(f"portfolio/goal_target/{account_name}"),
                    500_000.0,
                ) or 500_000.0
            )
        except Exception:
            return 500_000.0

    def set_goal_target(self, account_name: str, value: float) -> None:
        self._settings.setValue(self._scoped_key(f"portfolio/goal_target/{account_name}"), float(value))
        self._settings.sync()

    def get_goal_presets(self, account_name: str) -> List[float]:
        raw = self._settings.value(self._scoped_key(f"goals/presets/{account_name}"), None)
        if raw is not None:
            try:
                parsed = json.loads(raw) if isinstance(raw, str) else raw
                if isinstance(parsed, list) and len(parsed) == 3:
                    return [max(1.0, float(x)) for x in parsed]
            except Exception:
                pass
        return [250_000.0, 500_000.0, 1_000_000.0]

    def set_goal_presets(self, account_name: str, presets: List[float]) -> None:
        self._settings.setValue(
            self._scoped_key(f"goals/presets/{account_name}"),
            json.dumps([float(p) for p in presets]),
        )
        self._settings.sync()

    def get_goal_group(self) -> Tuple[List[str], float]:
        raw = self._settings.value(self._scoped_key(self.GOAL_GROUP_KEY), [])
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = []
        if not isinstance(raw, list): raw = []
        shared_goal = float(
            self._settings.value(self._scoped_key(self.GOAL_GROUP_SHARED_KEY), 500_000.0) or 500_000.0
        )
        return list(raw), shared_goal

    def set_goal_group(
            self,
            shared_accounts: List[str],
            shared_goal: float,
            individual_goals: Dict[str, float],
            individual_presets: Dict[str, List[float]],
    ) -> None:
        self._settings.setValue(self._scoped_key(self.GOAL_GROUP_KEY), json.dumps(shared_accounts))
        self._settings.setValue(self._scoped_key(self.GOAL_GROUP_SHARED_KEY), float(shared_goal))
        for account in shared_accounts:
            self.set_goal_target(account, shared_goal)
            if account in individual_presets:
                self.set_goal_presets(account, individual_presets[account])
        for account, goal in individual_goals.items():
            self.set_goal_target(account, goal)
            if account in individual_presets:
                self.set_goal_presets(account, individual_presets[account])
        self._settings.sync()

    def get_watchlist(self) -> List[str]:
        items = self._settings.value(self._scoped_key("watchlist/items"), [])
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except Exception:
                items = [x.strip() for x in items.split(",") if x.strip()]
        return [str(t).upper() for t in items] if items else []

    def save_watchlist(self, symbols: List[str]) -> None:
        self._settings.setValue(self._scoped_key("watchlist/items"), symbols)
        self._settings.sync()


# ---------------------------------------------------------------------------
# Login helper (used by ConnectionDialog)
# ---------------------------------------------------------------------------

def remote_login(base_url: str, username: str, password: str, timeout: int = 5) -> RemoteDataStore:
    """Authenticate and return a ready RemoteDataStore. Raises APIError on failure."""
    if not _REQUESTS_OK:
        raise ImportError("Install 'requests':  pip install requests")
    url = base_url.rstrip("/")
    r = requests.post(f"{url}/auth/login", json={"username": username, "password": password},
                      timeout=(timeout, timeout))
    if not r.ok:
        raise APIError(f"Login failed ({r.status_code}): {r.text}", r.status_code)
    data = r.json()
    return RemoteDataStore(
        base_url=url,
        token=data["token"],
        user_info_dict={
            "user_id": data["user_id"],
            "username": data["username"],
            "is_admin": bool(data["is_admin"]),
        },
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _parse_date_str(value):
    if not value:
        return None
    from datetime import datetime
    text = str(value).strip()
    if not text or text in ("None", "null"):
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_presets(raw) -> List[float]:
    if raw is None:
        return [250_000.0, 500_000.0, 1_000_000.0]
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return [250_000.0, 500_000.0, 1_000_000.0]
    if isinstance(raw, list) and len(raw) == 3:
        try:
            return [float(x) for x in raw]
        except Exception:
            pass
    return [250_000.0, 500_000.0, 1_000_000.0]


def _scope_username(username: str) -> str:
    text = str(username or "local").strip() or "local"
    return text.encode("utf-8").hex()


# ---------------------------------------------------------------------------
# FallbackDataStore — wraps RemoteDataStore with automatic offline fallback
# ---------------------------------------------------------------------------

class FallbackDataStore(DataStore):
    """Wraps RemoteDataStore with transparent offline fallback.

    On any network or server error during a write:
      1. The write is saved to LocalDataStore (QSettings) immediately so no
         data is lost.
      2. The operation is queued in sync_queue for replay on reconnect.
      3. _on_offline_cb(n_pending) is called so MainWindow can update the
         status bar.

    On reconnect (call attempt_reconnect()):
      1. Tries a lightweight ping to the server.
      2. If successful, flushes the sync queue.
      3. Calls _on_online_cb(synced_count) so MainWindow can show "Synced".

    Reads always try the remote first, falling back to local cache on failure.
    """

    def __init__(
            self,
            remote: RemoteDataStore,
            local: "LocalDataStore",
            on_offline_cb=None,  # callable(n_pending: int)
            on_online_cb=None,  # callable(synced_count: int)
    ):
        self._remote = remote
        self._local = local
        self._on_offline_cb = on_offline_cb
        self._on_online_cb = on_online_cb
        self._is_online = True

    # ---- internal ----

    def _handle_write_failure(self, exc: Exception, action: str, payload: dict) -> None:
        """Called when a remote write fails. Save locally and queue for sync."""
        from . import sync_queue
        self._is_online = False
        username = self._remote.user_info.get("username", "unknown")
        sync_queue.enqueue(username, action, payload)
        n = sync_queue.queue_length(username=username)
        if self._on_offline_cb:
            self._on_offline_cb(n)

    def _safe_remote_get(self, fn, fallback_fn):
        """Try remote read; fall back to local on any error."""
        try:
            result = fn()
            self._is_online = True
            return result
        except Exception:
            return fallback_fn()

    # ---- identity ----

    @property
    def user_info(self) -> dict:
        return self._remote.user_info

    @property
    def is_admin(self) -> bool:
        return self._remote.is_admin

    # ---- trades ----

    def get_all_trades(self) -> List[Trade]:
        return self._safe_remote_get(
            self._remote.get_all_trades,
            self._local.get_all_trades,
        )

    def save_account_trades(self, account_name: str, trades: List[Trade]) -> None:
        # Always write locally first — instant, no data loss
        self._local.save_account_trades(account_name, trades)
        try:
            self._remote.save_account_trades(account_name, trades)
            self._is_online = True
        except Exception as exc:
            from .portfolio import trade_to_dict
            payload = {
                "account_name": account_name,
                "trades": [trade_to_dict(t) for t in trades],
            }
            self._handle_write_failure(exc, "save_trades", payload)

    # ---- accounts ----

    def get_account_names(self) -> List[str]:
        return self._safe_remote_get(
            self._remote.get_account_names,
            self._local.get_account_names,
        )

    def save_accounts(self, accounts: List[str]) -> None:
        self._local.save_accounts(accounts)
        try:
            self._remote.save_accounts(accounts)
            self._is_online = True
        except Exception as exc:
            self._handle_write_failure(exc, "save_accounts", {"accounts": accounts})

    # ---- goal targets & presets ----

    def get_goal_target(self, account_name: str) -> float:
        return self._safe_remote_get(
            lambda: self._remote.get_goal_target(account_name),
            lambda: self._local.get_goal_target(account_name),
        )

    def set_goal_target(self, account_name: str, value: float) -> None:
        self._local.set_goal_target(account_name, value)
        try:
            self._remote.set_goal_target(account_name, value)
            self._is_online = True
        except Exception as exc:
            self._handle_write_failure(
                exc, "set_goal_target",
                {"account_name": account_name, "value": float(value)},
            )

    def get_goal_presets(self, account_name: str) -> List[float]:
        return self._safe_remote_get(
            lambda: self._remote.get_goal_presets(account_name),
            lambda: self._local.get_goal_presets(account_name),
        )

    def set_goal_presets(self, account_name: str, presets: List[float]) -> None:
        self._local.set_goal_presets(account_name, presets)
        try:
            self._remote.set_goal_presets(account_name, presets)
            self._is_online = True
        except Exception as exc:
            self._handle_write_failure(
                exc, "set_goal_presets",
                {"account_name": account_name, "presets": [float(p) for p in presets]},
            )

    # ---- goal group ----

    def get_goal_group(self) -> Tuple[List[str], float]:
        return self._safe_remote_get(
            self._remote.get_goal_group,
            self._local.get_goal_group,
        )

    def set_goal_group(
            self,
            shared_accounts: List[str],
            shared_goal: float,
            individual_goals: Dict[str, float],
            individual_presets: Dict[str, List[float]],
    ) -> None:
        self._local.set_goal_group(shared_accounts, shared_goal, individual_goals, individual_presets)
        try:
            self._remote.set_goal_group(shared_accounts, shared_goal, individual_goals, individual_presets)
            self._is_online = True
        except Exception as exc:
            self._handle_write_failure(exc, "set_goal_group", {
                "account_names": shared_accounts,
                "shared_goal": float(shared_goal),
                "individual_goals": {k: float(v) for k, v in individual_goals.items()},
                "individual_presets": {k: [float(p) for p in v] for k, v in individual_presets.items()},
            })

    # ---- watchlist ----

    def get_watchlist(self) -> List[str]:
        return self._safe_remote_get(
            self._remote.get_watchlist,
            self._local.get_watchlist,
        )

    def save_watchlist(self, symbols: List[str]) -> None:
        self._local.save_watchlist(symbols)
        try:
            self._remote.save_watchlist(symbols)
            self._is_online = True
        except Exception as exc:
            self._handle_write_failure(exc, "save_watchlist", {"symbols": symbols})

    # ---- admin passthrough ----

    def store_for_user(self, user_id: int, username: str) -> RemoteDataStore:
        return self._remote.store_for_user(user_id, username)

    def list_users(self) -> List[dict]:
        return self._remote.list_users()

    # ---- reconnect ----

    def attempt_reconnect(self) -> bool:
        """Ping the server and flush the sync queue if reachable.

        Returns True if the server is now reachable.
        Called periodically by MainWindow's reconnect timer.
        """
        from . import sync_queue

        try:
            r = requests.get(
                f"{self._remote._base}/auth/me",
                headers=self._remote._headers(),
                timeout=4,
            )
            if not r.ok:
                return False
        except Exception:
            return False

        # Server is back — flush queued writes
        self._is_online = True
        synced, failed = sync_queue.flush(self._remote, username=self.username)
        if self._on_online_cb:
            self._on_online_cb(synced)
        return True

    @property
    def pending_sync_count(self) -> int:
        from . import sync_queue
        return sync_queue.queue_length(username=self.username)
