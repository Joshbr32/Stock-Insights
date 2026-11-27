"""api_client.py — DataStore abstraction, HTTP client and offline fallback.

DataStore           Abstract interface for all user-data persistence.  The UI
                    (MainWindow, PortfolioTab, dialogs) only talks to this.
RemoteDataStore     Talks to the FastAPI server (server/server.py) over HTTP
                    through one pooled requests.Session.
LocalDataStore      QSettings-backed store.  Used on its own for "work
                    offline", and as the on-device cache behind
                    FallbackDataStore.
FallbackDataStore   Remote first; when the server is unreachable it serves
                    reads from the local cache and parks writes in
                    sync_queue until ReconnectWorker replays them.

Trades are saved one at a time: save_trade / delete_trade address a trade by
its `uid` (PUT / DELETE /trades/{account}/{uid}, server 1.1+).  The bulk
save_account_trades stays for restore-from-backup and the admin viewer, and is
what RemoteDataStore falls back to when the server predates the per-trade
routes.

Threading: store methods are called from the GUI thread and from short-lived
QThreads (StoreCallWorker, ReconnectWorker), so every class here guards its
shared state with a lock and never touches widgets.  FallbackDataStore
delivers its status callbacks on the GUI thread.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import replace
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

from PySide6.QtCore import QCoreApplication, QObject, QSettings, QThread, Signal, Slot

from .logging_utils import get_logger
from .portfolio import Trade, new_trade_uid, trade_to_dict, trades_from_json, trades_to_json

logger = get_logger("api_client")

DEFAULT_GOAL_TARGET = 500_000.0
DEFAULT_GOAL_PRESETS = (250_000.0, 500_000.0, 1_000_000.0)

# (connect, read) seconds.  Connect is short because store calls can run on
# the GUI thread: an unreachable server must fail fast, while a slow SQL
# query on a reachable server still gets a reasonable read window.
_TIMEOUT = (4, 10)
_HEALTH_TIMEOUT = 3
_RECONNECT_TIMEOUT = 4

# HTTP statuses where retrying the same request later can succeed.  401 is in
# the list because an expired token is fixed by signing in again; the queued
# write must survive until then.  Every other 4xx means the server rejected
# the request itself and replaying it would fail the same way.
_TRANSIENT_STATUSES = frozenset({401, 408, 425, 429})


def is_transient_status(status_code: int) -> bool:
    """True when a failed request is worth retrying later (see above)."""
    return status_code >= 500 or status_code in _TRANSIENT_STATUSES


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

    def save_trade(self, account_name: str, trade: Trade) -> str:
        """Insert or update one trade, identified by `trade.uid`, in
        `account_name`.  A trade that currently sits in another account is
        moved.  Saving the same trade twice is harmless.

        Returns the uid the trade is stored under.  That is `trade.uid`
        except when the server had to refuse it (see RemoteDataStore).

        This default works on any store through the bulk call: read the
        account, apply the change, write the account back.
        """
        stored = replace(trade, account=account_name)
        all_trades = self.get_all_trades()
        # Source accounts first.  Written the other way round, a store that
        # keeps one flat list would hold the trade under both accounts until
        # the second write.
        for source in _accounts_holding(all_trades, stored.uid):
            if source != account_name:
                self.save_account_trades(
                    source, [t for t in _in_account(all_trades, source) if t.uid != stored.uid])
        self.save_account_trades(
            account_name, _upsert(_in_account(all_trades, account_name), stored))
        return stored.uid

    def delete_trade(self, account_name: str, uid: str) -> None:
        """Delete the trade with this uid.  Deleting a trade that does not
        exist is not an error.  `account_name` is the account the caller
        believes holds it; the uid alone decides what is removed."""
        all_trades = self.get_all_trades()
        for source in _accounts_holding(all_trades, uid):
            self.save_account_trades(
                source, [t for t in _in_account(all_trades, source) if t.uid != uid])

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
    """The server answered, but with a non-2xx status."""

    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code

    @property
    def is_transient(self) -> bool:
        return is_transient_status(self.status_code)


def _new_session() -> "requests.Session":
    """Session with keep-alive pooling and one quick retry.

    The retry covers the common "pooled connection was closed by the proxy
    while idle" failure and brief 502/503/504 blips from the tunnel.  Every
    data route is a GET, a full-replace PUT, or an upsert / delete by uid, so
    resending is idempotent.
    Read timeouts are not retried: the server may still be processing, and
    a second attempt would only double the wait on the calling thread.
    """
    retry = Retry(
        total=1, connect=1, read=0, status=1,
        backoff_factor=0.3,
        status_forcelist=(502, 503, 504),
        allowed_methods=frozenset({"GET", "PUT", "DELETE"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(pool_connections=2, pool_maxsize=4, max_retries=retry)
    session = requests.Session()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def _error_message(response) -> str:
    """Prefer FastAPI's {"detail": ...} over the raw body."""
    try:
        detail = response.json().get("detail")
    except Exception:
        detail = None
    if isinstance(detail, str) and detail:
        return detail
    if detail:
        return json.dumps(detail)
    return response.text or f"HTTP {response.status_code}"


def _account_path(account_name: str) -> str:
    # Account names are user text; '?', '#' and '%' would otherwise change
    # the meaning of the URL.
    return quote(str(account_name), safe="")


def _trade_path(account_name: str, uid: str) -> str:
    return f"/trades/{_account_path(account_name)}/{quote(str(uid), safe='')}"


def _account_of(trade: Trade) -> str:
    return (trade.account or "").strip()


def _in_account(trades: List[Trade], account_name: str) -> List[Trade]:
    return [t for t in trades if _account_of(t) == account_name]


def _accounts_holding(trades: List[Trade], uid: str) -> List[str]:
    """Accounts with a trade of this uid (normally none or one)."""
    return list(dict.fromkeys(_account_of(t) for t in trades if t.uid == uid))


def _upsert(trades: List[Trade], trade: Trade) -> List[Trade]:
    """Copy of `trades` with `trade` replacing the entry of the same uid, in
    the same position, or appended when it is new.  That matches the server,
    which lists trades in insertion order and updates rows in place."""
    out = list(trades)
    for i, existing in enumerate(out):
        if existing.uid == trade.uid:
            out[i] = trade
            return out
    out.append(trade)
    return out


def _trade_fields(t: Trade) -> dict:
    """A trade's content as the server's TradeIn model, without its uid."""
    return {
        "instrument": t.normalized_instrument(),
        "share_count": int(t.share_count),
        "buy_price": float(t.buy_price),
        "sell_price": None if t.sell_price is None else float(t.sell_price),
        "open_date": t.open_date.isoformat() if t.open_date else None,
        "close_date": t.close_date.isoformat() if t.close_date else None,
        "notes": t.notes or "",
        "is_pending": bool(t.is_pending),
        "is_short": bool(t.is_short),
        "tag": (t.tag or "").strip(),
    }


def _trade_payload(t: Trade) -> dict:
    """One trade as sent to the server.  Servers older than 1.1 ignore
    `tag` and `uid`."""
    return {**_trade_fields(t), "uid": t.uid}


class RemoteDataStore(DataStore):
    """DataStore backed by the FastAPI server.

    Parameters
    ----------
    base_url : e.g. 'http://192.168.1.10:8742'
    token    : Bearer token obtained from /auth/login
    user_info_dict : dict returned by /auth/login {user_id, username, is_admin}
    for_user_id : if set (admin use), all requests proxy for this user_id
    session : optional requests.Session to reuse (keeps the login connection)

    Reads are cached in memory until the matching write invalidates them.
    A per-trade save or delete updates the cached trade list instead of
    dropping it, so the refresh after a save costs no request.
    Safe to call from several threads.
    """

    def __init__(
            self,
            base_url: str,
            token: str,
            user_info_dict: dict,
            for_user_id: Optional[int] = None,
            session: Optional["requests.Session"] = None,
    ):
        if not _REQUESTS_OK:
            raise ImportError("Install 'requests':  pip install requests")
        self._base = base_url.rstrip("/")
        self._token = token
        self._user_info = user_info_dict
        self._for_user_id = for_user_id
        self._session = session or _new_session()
        self._lock = threading.RLock()

        # In-memory caches.  Each has a generation counter that every
        # invalidation bumps, so a fetch that started before a write cannot
        # store its (now stale) answer after the write invalidated the cache.
        self._account_cache: Optional[List[dict]] = None  # [{name, goal_target, goal_presets}]
        self._trade_cache: Optional[List[Trade]] = None
        self._goal_group_cache: Optional[Tuple[List[str], float]] = None
        self._account_gen = 0
        self._trade_gen = 0
        self._goal_group_gen = 0

        # Can the server take PUT/DELETE /trades/{account}/{uid}?  None
        # until the first per-trade call answers; False (for the rest of the
        # session) once a server older than 1.1 answered 404/405, or a 1.1
        # server whose database is not migrated yet answered 503.
        self._per_trade_routes: Optional[bool] = None
        # Old servers only (see _trades_from_rows): content-derived uid of a
        # row -> the uid this session saved that trade under, so the trade
        # keeps the uid its caller knows when the list is fetched again.
        self._legacy_uids: Dict[str, str] = {}

    # ---- internal ----

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"}

    def _params(self) -> dict:
        return {"for_user_id": self._for_user_id} if self._for_user_id else {}

    def _request(self, method: str, path: str, *, json_body: Any = None,
                 scoped: bool = True, timeout=_TIMEOUT) -> Any:
        """One authenticated call.  Raises APIError on a non-2xx answer and
        requests.RequestException when the server cannot be reached."""
        r = self._session.request(
            method, f"{self._base}{path}",
            json=json_body,
            headers=self._headers(),
            params=self._params() if scoped else None,
            timeout=timeout,
        )
        if not r.ok:
            raise APIError(_error_message(r), r.status_code)
        try:
            return r.json()
        except ValueError:
            # A captive portal or proxy error page answering 200 with HTML.
            # Reported as a gateway error so callers treat it as an outage.
            raise APIError("Server returned a non-JSON response", 502) from None

    def _get(self, path: str) -> Any:
        return self._request("GET", path)

    def _put(self, path: str, data: dict) -> Any:
        return self._request("PUT", path, json_body=data)

    def _per_trade_call(self, method: str, path: str, json_body: Any = None) -> bool:
        """Call a per-trade route.  True when the server applied it, False
        when the server has no such route and the caller must use the bulk
        route instead.  Raises like _request otherwise; the trade cache is
        dropped then, because a request that timed out may still have been
        applied."""
        if self._per_trade_routes is False:
            return False
        try:
            self._request(method, path, json_body=json_body)
        except APIError as exc:
            reason = self._per_trade_unavailable(exc)
            if reason:
                self._per_trade_routes = False
                logger.warning(
                    "Per-trade saves are not available (%s answered %s: %s); saving "
                    "whole accounts for the rest of this session.",
                    method, exc.status_code, reason)
                return False
            self._invalidate_trades()
            raise
        except BaseException:
            self._invalidate_trades()
            raise
        self._per_trade_routes = True
        return True

    def _per_trade_unavailable(self, exc: APIError) -> str:
        """Why a failed per-trade call means "use the whole-account route",
        or "" when the failure is an ordinary error."""
        # 404/405 from a server that never accepted a per-trade call: the
        # route does not exist.  Once the route is known to work, the same
        # status is a real error.
        if exc.status_code in (404, 405) and self._per_trade_routes is None:
            return "the server is older than 1.1, update it"
        # A 1.1 server answers 503 on these routes until its database has
        # the new columns, while the whole-account route keeps working.
        # Any other 503 is an outage and must stay one (offline + queue).
        if exc.status_code == 503 and self.ping_health().get("schema") == "needs_migration":
            return "the server's database needs the 1.1 migration"
        return ""

    def _edit_trade_cache(self, edit: Callable[[List[Trade]], List[Trade]]) -> None:
        """Apply a confirmed write to the cached trade list.

        The list is replaced, never changed in place: readers hold the old
        one.  The generation is bumped either way, so a GET that started
        before the write cannot store its older answer afterwards.
        """
        with self._lock:
            self._trade_gen += 1
            if self._trade_cache is not None:
                self._trade_cache = edit(self._trade_cache)

    def _account_may_be_new(self, account_name: str) -> None:
        """Saving a trade creates its account on the server when missing;
        drop the account cache if this name is not in it."""
        with self._lock:
            cached = self._account_cache
        if cached is not None and all(a.get("name") != account_name for a in cached):
            self._invalidate_accounts()

    def _invalidate_trades(self) -> None:
        with self._lock:
            self._trade_cache = None
            self._trade_gen += 1

    def _invalidate_accounts(self) -> None:
        with self._lock:
            self._account_cache = None
            self._account_gen += 1

    def _invalidate_goal_group(self) -> None:
        with self._lock:
            self._goal_group_cache = None
            self._goal_group_gen += 1

    def invalidate_caches(self) -> None:
        """Forget everything cached (used after an outage, when another
        device may have changed the data)."""
        self._invalidate_trades()
        self._invalidate_accounts()
        self._invalidate_goal_group()

    def _get_account_data(self) -> List[dict]:
        with self._lock:
            cached = self._account_cache
            gen = self._account_gen
        if cached is not None:
            return cached
        # The network call runs outside the lock so a slow fetch on one
        # thread never blocks cache hits on another.
        data = self._get("/accounts")
        with self._lock:
            if gen == self._account_gen:
                self._account_cache = data
        return data

    def _put_account_settings(self, account_name: str, goal_target: float,
                              goal_presets: List[float]) -> None:
        # The server ignores `position` on this route but its model requires
        # the field.
        self._put(f"/accounts/{_account_path(account_name)}/settings", {
            "name": account_name,
            "goal_target": float(goal_target),
            "goal_presets": [float(p) for p in goal_presets],
            "position": 0,
        })

    # ---- DataStore implementation ----

    @property
    def user_info(self) -> dict:
        return self._user_info

    def get_all_trades(self) -> List[Trade]:
        with self._lock:
            cached = self._trade_cache
            gen = self._trade_gen
        if cached is None:
            rows = self._get("/trades")
            with self._lock:
                known = dict(self._legacy_uids)
            cached = _trades_from_rows(rows, self.username, known)
            with self._lock:
                if gen == self._trade_gen:
                    self._trade_cache = cached
        return list(cached)

    def save_account_trades(self, account_name: str, trades: List[Trade]) -> None:
        payload = {
            "account_name": account_name,
            "trades": [_trade_payload(t) for t in trades],
        }
        try:
            self._put(f"/trades/{_account_path(account_name)}", payload)
            if self._per_trade_routes is False:
                self._remember_legacy_uids(account_name, trades)
        finally:
            # Also on failure: a timed-out PUT may still have been applied.
            self._invalidate_trades()

    def _remember_legacy_uids(self, account_name: str, trades: List[Trade]) -> None:
        """After a whole-account save to a server that does not store uids,
        note which content-derived uid each saved trade will come back
        with."""
        saved = [replace(t, account=account_name) for t in trades]
        uids = {t.uid for t in saved}
        with self._lock:
            # Forget what these trades looked like before this save.
            self._legacy_uids = {k: v for k, v in self._legacy_uids.items() if v not in uids}
            for derived, trade in zip(_content_uids(saved, self.username), saved):
                if derived != trade.uid:
                    self._legacy_uids[derived] = trade.uid

    def save_trade(self, account_name: str, trade: Trade) -> str:
        # The copy keeps the cache independent of the caller's object.
        stored = replace(trade, account=account_name)
        try:
            applied = self._per_trade_call(
                "PUT", _trade_path(account_name, stored.uid), _trade_payload(stored))
        except APIError as exc:
            if exc.status_code != 409:
                raise
            # The uid belongs to another user's trade (e.g. a backup restored
            # into a second login).  Save it under a new uid, once; a second
            # 409 is raised and, being a 4xx, is never queued or retried.
            stored = replace(stored, uid=new_trade_uid())
            logger.warning("Trade uid %s is taken on the server; saved as %s", trade.uid, stored.uid)
            applied = self._per_trade_call(
                "PUT", _trade_path(account_name, stored.uid), _trade_payload(stored))
        if applied:
            # (The filter only matters after a 409: drop the refused uid.)
            self._edit_trade_cache(lambda trades: _upsert(
                [t for t in trades if t.uid != trade.uid or t.uid == stored.uid], stored))
            self._account_may_be_new(account_name)
        else:
            # No per-trade route: rewrite the whole account instead.
            DataStore.save_trade(self, account_name, stored)
        return stored.uid

    def delete_trade(self, account_name: str, uid: str) -> None:
        if self._per_trade_call("DELETE", _trade_path(account_name, uid)):
            self._edit_trade_cache(lambda trades: [t for t in trades if t.uid != uid])
        else:
            DataStore.delete_trade(self, account_name, uid)

    def get_account_names(self) -> List[str]:
        return [a["name"] for a in self._get_account_data()]

    def save_accounts(self, accounts: List[str]) -> None:
        existing = {a["name"]: a for a in self._get_account_data()}
        payload_accounts = []
        for pos, name in enumerate(accounts):
            ex = existing.get(name, {})
            payload_accounts.append({
                "name": name,
                "goal_target": float(ex.get("goal_target", DEFAULT_GOAL_TARGET)),
                "goal_presets": _parse_presets(ex.get("goal_presets", None)),
                "position": pos,
            })
        try:
            self._put("/accounts", {"accounts": payload_accounts})
        finally:
            self._invalidate_accounts()
            # Removing an account cascades to its trades on the server.
            self._invalidate_trades()

    def get_goal_target(self, account_name: str) -> float:
        for a in self._get_account_data():
            if a["name"] == account_name:
                return float(a.get("goal_target", DEFAULT_GOAL_TARGET))
        return DEFAULT_GOAL_TARGET

    def set_goal_target(self, account_name: str, value: float) -> None:
        presets = self.get_goal_presets(account_name)
        try:
            self._put_account_settings(account_name, value, presets)
        finally:
            self._invalidate_accounts()

    def get_goal_presets(self, account_name: str) -> List[float]:
        for a in self._get_account_data():
            if a["name"] == account_name:
                return _parse_presets(a.get("goal_presets", None))
        return list(DEFAULT_GOAL_PRESETS)

    def set_goal_presets(self, account_name: str, presets: List[float]) -> None:
        target = self.get_goal_target(account_name)
        try:
            self._put_account_settings(account_name, target, presets)
        finally:
            self._invalidate_accounts()

    def get_goal_group(self) -> Tuple[List[str], float]:
        with self._lock:
            cached = self._goal_group_cache
            gen = self._goal_group_gen
        if cached is None:
            data = self._get("/goal-group")
            cached = (
                list(data.get("account_names", [])),
                float(data.get("shared_goal", DEFAULT_GOAL_TARGET)),
            )
            with self._lock:
                if gen == self._goal_group_gen:
                    self._goal_group_cache = cached
        return list(cached[0]), cached[1]

    def set_goal_group(
            self,
            shared_accounts: List[str],
            shared_goal: float,
            individual_goals: Dict[str, float],
            individual_presets: Dict[str, List[float]],
    ) -> None:
        # One settings PUT per account.  An account listed both ways takes
        # the shared goal, as it did when the two loops ran back to back.
        targets: Dict[str, float] = {name: float(goal) for name, goal in individual_goals.items()}
        for account in shared_accounts:
            targets[account] = float(shared_goal)
        try:
            self._put("/goal-group", {
                "account_names": list(shared_accounts),
                "shared_goal": float(shared_goal),
            })
            for account, target in targets.items():
                presets = individual_presets.get(account)
                if presets is None:
                    presets = self.get_goal_presets(account)
                self._put_account_settings(account, target, presets)
        finally:
            self._invalidate_goal_group()
            self._invalidate_accounts()

    def get_watchlist(self) -> List[str]:
        return self._get("/watchlist")

    def save_watchlist(self, symbols: List[str]) -> None:
        self._put("/watchlist", {"symbols": list(symbols)})

    # ---- Admin-only: create a view-only store for another user ----

    def store_for_user(self, user_id: int, username: str) -> "RemoteDataStore":
        """Return a read-only-capable DataStore scoped to another user (admin use)."""
        store = RemoteDataStore(
            base_url=self._base,
            token=self._token,
            user_info_dict={"user_id": user_id, "username": username, "is_admin": False},
            for_user_id=user_id,
            session=self._session,
        )
        # Same server, so what is known about its routes carries over.
        store._per_trade_routes = self._per_trade_routes
        return store

    def list_users(self) -> List[dict]:
        """Admin: list all users."""
        return self._request("GET", "/users", scoped=False)

    def check_auth(self, timeout=_RECONNECT_TIMEOUT) -> None:
        """Cheap authenticated round trip (/auth/me).  Raises like _request."""
        self._request("GET", "/auth/me", scoped=False, timeout=timeout)

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
        t0 = time.monotonic()

        def elapsed_ms() -> int:
            return int((time.monotonic() - t0) * 1000)

        try:
            # No auth header — /health is intentionally public.
            r = self._session.get(f"{self._base}/health", timeout=_HEALTH_TIMEOUT)
            latency_ms = elapsed_ms()
            if not r.ok:
                return {"ok": False, "latency_ms": latency_ms,
                        "error": f"HTTP {r.status_code}"}
            data = r.json()
            data["ok"] = bool(data.get("ok", False))
            data["latency_ms"] = latency_ms
            return data
        except requests.exceptions.Timeout:
            return {"ok": False, "latency_ms": elapsed_ms(), "error": "timeout"}
        except Exception as exc:
            return {"ok": False, "latency_ms": elapsed_ms(), "error": str(exc)[:120]}


# ---------------------------------------------------------------------------
# LocalDataStore — QSettings fallback (offline / no server)
# ---------------------------------------------------------------------------

class LocalDataStore(DataStore):
    """DataStore backed by QSettings — matches the pre-server behaviour exactly.

    Everything lives under user_cache/<hex(username)>/ so several users can
    share one Windows profile.  One QSettings object is shared by every
    caller, so all access goes through a lock (QSettings is only reentrant,
    not safe to share between threads).
    """

    ORG = "StockInsights"
    APP = "StocksGUI"

    TRADES_KEY = "portfolio/trades"
    GOAL_GROUP_KEY = "portfolio/goal_dashboard_accounts"
    GOAL_GROUP_SHARED_KEY = "portfolio/goal_dashboard_shared_goal"
    ACCOUNTS_KEY = "user_account/accounts"
    WATCHLIST_KEY = "watchlist/items"
    # Which datasets hold a full copy of the server's data (see
    # FallbackDataStore): JSON list of dataset names.
    MIRRORED_KEY = "cache/mirrored"

    def __init__(self, username: str = "local"):
        self._settings = QSettings(self.ORG, self.APP)
        self._username = username
        self._scope_prefix = f"user_cache/{_scope_username(username)}"
        self._lock = threading.RLock()

    def _scoped_key(self, key: str) -> str:
        return f"{self._scope_prefix}/{key}"

    def _goal_target_key(self, account_name: str) -> str:
        return self._scoped_key(f"portfolio/goal_target/{account_name}")

    def _goal_presets_key(self, account_name: str) -> str:
        return self._scoped_key(f"goals/presets/{account_name}")

    @property
    def user_info(self) -> dict:
        return {"user_id": 0, "username": self._username, "is_admin": False}

    def get_all_trades(self) -> List[Trade]:
        with self._lock:
            raw = self._settings.value(self._scoped_key(self.TRADES_KEY), [])
            trades = trades_from_json(raw)
            if trades and not _uids_stored(raw, trades):
                # Data written before trades had uids: keep the ones just
                # generated, otherwise every read would hand out different
                # ids and a per-trade save could not find its trade.
                self._write_trades(trades)
        return trades

    def _write_trades(self, trades: List[Trade]) -> None:
        """Caller holds the lock."""
        self._settings.setValue(self._scoped_key(self.TRADES_KEY), trades_to_json(trades))
        self._settings.sync()

    def save_account_trades(self, account_name: str, trades: List[Trade]) -> None:
        # Read all trades, replace the slice for this account, write back
        with self._lock:
            kept = [t for t in self.get_all_trades() if _account_of(t) != account_name]
            self._write_trades(kept + list(trades))

    def save_trade(self, account_name: str, trade: Trade) -> str:
        # Same result as the DataStore default, in one read and one write
        # (a move is then atomic instead of two account rewrites).
        with self._lock:
            self._write_trades(_upsert(self.get_all_trades(), replace(trade, account=account_name)))
        return trade.uid

    def delete_trade(self, account_name: str, uid: str) -> None:
        with self._lock:
            trades = self.get_all_trades()
            kept = [t for t in trades if t.uid != uid]
            if len(kept) != len(trades):
                self._write_trades(kept)

    def get_account_names(self) -> List[str]:
        with self._lock:
            raw = self._settings.value(self._scoped_key(self.ACCOUNTS_KEY), ["Default"])
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except ValueError:
                raw = [x.strip() for x in raw.split(",") if x.strip()]
        if not isinstance(raw, list):
            raw = ["Default"]
        return _unique_names(raw) or ["Default"]

    def save_accounts(self, accounts: List[str]) -> None:
        with self._lock:
            existing_accounts = set(self.get_account_names())
            normalized_accounts = _unique_names(accounts)
            allowed_accounts = set(normalized_accounts)

            # Dropping an account drops its trades, like the server's cascade.
            kept_trades = [t for t in self.get_all_trades() if (t.account or "").strip() in allowed_accounts]
            self._settings.setValue(self._scoped_key(self.TRADES_KEY), trades_to_json(kept_trades))
            self._settings.setValue(self._scoped_key(self.ACCOUNTS_KEY), json.dumps(normalized_accounts))

            shared_accounts, shared_goal = self.get_goal_group()
            filtered_shared = [name for name in shared_accounts if name in allowed_accounts]
            self._settings.setValue(self._scoped_key(self.GOAL_GROUP_KEY), json.dumps(filtered_shared))
            self._settings.setValue(self._scoped_key(self.GOAL_GROUP_SHARED_KEY), float(shared_goal))

            for account in existing_accounts - allowed_accounts:
                self._settings.remove(self._goal_target_key(account))
                self._settings.remove(self._goal_presets_key(account))
            self._settings.sync()

    def get_goal_target(self, account_name: str) -> float:
        with self._lock:
            raw = self._settings.value(self._goal_target_key(account_name), DEFAULT_GOAL_TARGET)
        try:
            return float(raw or DEFAULT_GOAL_TARGET)
        except (TypeError, ValueError):
            return DEFAULT_GOAL_TARGET

    def set_goal_target(self, account_name: str, value: float) -> None:
        with self._lock:
            self._settings.setValue(self._goal_target_key(account_name), float(value))
            self._settings.sync()

    def get_goal_presets(self, account_name: str) -> List[float]:
        with self._lock:
            raw = self._settings.value(self._goal_presets_key(account_name), None)
        if raw is not None:
            try:
                parsed = json.loads(raw) if isinstance(raw, str) else raw
                if isinstance(parsed, list) and len(parsed) == 3:
                    return [max(1.0, float(x)) for x in parsed]
            except (TypeError, ValueError):
                pass
        return list(DEFAULT_GOAL_PRESETS)

    def set_goal_presets(self, account_name: str, presets: List[float]) -> None:
        with self._lock:
            self._settings.setValue(
                self._goal_presets_key(account_name),
                json.dumps([float(p) for p in presets]),
            )
            self._settings.sync()

    def get_goal_group(self) -> Tuple[List[str], float]:
        with self._lock:
            raw = self._settings.value(self._scoped_key(self.GOAL_GROUP_KEY), [])
            raw_goal = self._settings.value(self._scoped_key(self.GOAL_GROUP_SHARED_KEY), DEFAULT_GOAL_TARGET)
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except ValueError:
                raw = []
        if not isinstance(raw, list):
            raw = []
        try:
            shared_goal = float(raw_goal or DEFAULT_GOAL_TARGET)
        except (TypeError, ValueError):
            shared_goal = DEFAULT_GOAL_TARGET
        return list(raw), shared_goal

    def set_goal_group(
            self,
            shared_accounts: List[str],
            shared_goal: float,
            individual_goals: Dict[str, float],
            individual_presets: Dict[str, List[float]],
    ) -> None:
        with self._lock:
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
        with self._lock:
            items = self._settings.value(self._scoped_key(self.WATCHLIST_KEY), [])
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except ValueError:
                items = [x.strip() for x in items.split(",") if x.strip()]
        return [str(t).upper() for t in items] if items else []

    def save_watchlist(self, symbols: List[str]) -> None:
        with self._lock:
            self._settings.setValue(self._scoped_key(self.WATCHLIST_KEY), list(symbols))
            self._settings.sync()

    # ---- cache mirroring (used by FallbackDataStore) ----

    def mirrored_datasets(self) -> set:
        """Names of the datasets that hold a full copy of the server's data."""
        with self._lock:
            raw = self._settings.value(self._scoped_key(self.MIRRORED_KEY), "[]")
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            return {str(x) for x in parsed} if isinstance(parsed, list) else set()
        except (TypeError, ValueError):
            return set()

    def _mark_mirrored(self, dataset: str) -> None:
        done = self.mirrored_datasets()
        if dataset not in done:
            done.add(dataset)
            self._settings.setValue(self._scoped_key(self.MIRRORED_KEY), json.dumps(sorted(done)))

    def mirror_trades(self, trades: List[Trade]) -> None:
        """Overwrite every cached trade with the server's list."""
        with self._lock:
            self._settings.setValue(self._scoped_key(self.TRADES_KEY), trades_to_json(list(trades)))
            self._mark_mirrored("trades")
            self._settings.sync()

    def mirror_accounts(self, accounts: List[dict]) -> None:
        """Overwrite cached account names, goal targets and presets with the
        server's rows ({name, goal_target, goal_presets}).  Trades are left
        alone; mirror_trades owns those."""
        with self._lock:
            names = _unique_names([a.get("name") for a in accounts])
            for stale in set(self.get_account_names()) - set(names):
                self._settings.remove(self._goal_target_key(stale))
                self._settings.remove(self._goal_presets_key(stale))
            self._settings.setValue(self._scoped_key(self.ACCOUNTS_KEY), json.dumps(names))
            for a in accounts:
                name = str(a.get("name") or "").strip()
                if not name:
                    continue
                try:
                    target = float(a.get("goal_target", DEFAULT_GOAL_TARGET))
                except (TypeError, ValueError):
                    target = DEFAULT_GOAL_TARGET
                self._settings.setValue(self._goal_target_key(name), target)
                self._settings.setValue(
                    self._goal_presets_key(name),
                    json.dumps(_parse_presets(a.get("goal_presets"))),
                )
            self._mark_mirrored("accounts")
            self._settings.sync()

    def mirror_goal_group(self, shared_accounts: List[str], shared_goal: float) -> None:
        with self._lock:
            self._settings.setValue(self._scoped_key(self.GOAL_GROUP_KEY), json.dumps(list(shared_accounts)))
            self._settings.setValue(self._scoped_key(self.GOAL_GROUP_SHARED_KEY), float(shared_goal))
            self._mark_mirrored("goal_group")
            self._settings.sync()

    def mirror_watchlist(self, symbols: List[str]) -> None:
        with self._lock:
            self._settings.setValue(self._scoped_key(self.WATCHLIST_KEY), list(symbols))
            self._mark_mirrored("watchlist")
            self._settings.sync()


# ---------------------------------------------------------------------------
# Login helper (used by ConnectionDialog)
# ---------------------------------------------------------------------------

def remote_login(base_url: str, username: str, password: str, timeout: int = 5) -> RemoteDataStore:
    """Authenticate and return a ready RemoteDataStore. Raises APIError on failure."""
    if not _REQUESTS_OK:
        raise ImportError("Install 'requests':  pip install requests")
    url = base_url.rstrip("/")
    session = _new_session()
    try:
        r = session.post(f"{url}/auth/login", json={"username": username, "password": password},
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
            # Hand the warm connection to the store: the first data request
            # skips a second TCP/TLS handshake.
            session=session,
        )
    except BaseException:
        session.close()
        raise


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _parse_date_str(value):
    if not value:
        return None
    text = str(value).strip()
    if not text or text in ("None", "null"):
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _content_uids(trades: List[Trade], username: str) -> List[str]:
    """A uid for each trade derived from its content: owner, account and
    fields, plus a counter that tells identical trades apart.  The tag is
    left out because the servers this is for (older than 1.1) do not store
    it."""
    out: List[str] = []
    seen: Dict[str, int] = {}
    for trade in trades:
        fields = {**_trade_fields(trade), "tag": ""}
        content = json.dumps([username, _account_of(trade), fields], sort_keys=True)
        n = seen[content] = seen.get(content, 0) + 1
        out.append(hashlib.sha256(f"{content}#{n}".encode("utf-8")).hexdigest()[:32])
    return out


def _trades_from_rows(rows: List[dict], username: str,
                      known_uids: Optional[Dict[str, str]] = None) -> List[Trade]:
    """Build the trade list from a GET /trades answer.

    Servers older than 1.1 send no uid.  Their rows get one derived from the
    row's content, not a random one: the list is fetched again after every
    whole-account save, and a trade must keep its uid across those fetches
    for a later save or delete of it to find it.  `known_uids` maps such a
    derived uid to the uid this session already uses for the trade.
    """
    trades = [_trade_from_row(row) for row in rows]
    anonymous = [t for t, row in zip(trades, rows) if not row.get("uid")]
    if anonymous:
        taken = {t.uid for t, row in zip(trades, rows) if row.get("uid")}
        for trade, derived in zip(anonymous, _content_uids(anonymous, username)):
            uid = (known_uids or {}).get(derived, derived)
            trade.uid = derived if uid in taken else uid
            taken.add(trade.uid)
    return trades


def _uids_stored(raw, trades: List[Trade]) -> bool:
    """True when every uid in `trades` came from the stored JSON `raw`
    (False when trades_from_json had to generate or replace one)."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return False
    if not isinstance(raw, list):
        return False
    stored = [item.get("uid") for item in raw if isinstance(item, dict)]
    return len(stored) == len(set(stored)) and {t.uid for t in trades} <= set(stored)


def _trade_from_row(r: dict) -> Trade:
    """Build a Trade from one GET /trades row."""
    return Trade(
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
        tag=str(r.get("tag") or "").strip(),
        uid=str(r.get("uid") or ""),
    )


def _parse_presets(raw) -> List[float]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = None
    if isinstance(raw, list) and len(raw) == 3:
        try:
            return [float(x) for x in raw]
        except (TypeError, ValueError):
            pass
    return list(DEFAULT_GOAL_PRESETS)


def _unique_names(items) -> List[str]:
    """Strip, drop blanks and duplicates, keep first-seen order."""
    out: List[str] = []
    seen = set()
    for item in items or []:
        name = str(item or "").strip()
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def _scope_username(username: str) -> str:
    text = str(username or "local").strip() or "local"
    return text.encode("utf-8").hex()


class _MainThreadInvoker(QObject):
    """Runs callables on the GUI thread.

    FallbackDataStore's status callbacks update widgets, but the store is
    also driven from worker threads.  The signal is connected to a slot on
    this object, which lives in the GUI thread, so Qt queues the call when
    it is emitted from anywhere else.
    """

    _call = Signal(object)

    def __init__(self):
        super().__init__()
        self._call.connect(self._run)

    @Slot(object)
    def _run(self, fn) -> None:
        try:
            fn()
        except Exception:
            logger.exception("status callback failed")

    def post(self, fn: Callable[[], None]) -> None:
        self._call.emit(fn)


_invoker: Optional[_MainThreadInvoker] = None
_invoker_lock = threading.Lock()


def _call_on_gui_thread(fn: Callable[..., None], *args) -> None:
    """Run fn(*args) on the GUI thread: at once if already there (or if no
    Qt application exists, e.g. in scripts), queued otherwise."""
    global _invoker
    app = QCoreApplication.instance()
    if app is None or QThread.currentThread() == app.thread():
        try:
            fn(*args)
        except Exception:
            logger.exception("status callback failed")
        return
    with _invoker_lock:
        if _invoker is None:
            invoker = _MainThreadInvoker()
            invoker.moveToThread(app.thread())
            _invoker = invoker
    _invoker.post(lambda: fn(*args))


# ---------------------------------------------------------------------------
# FallbackDataStore — wraps RemoteDataStore with automatic offline fallback
# ---------------------------------------------------------------------------

class FallbackDataStore(DataStore):
    """Wraps RemoteDataStore with transparent offline fallback.

    Two states, held in `_is_online`:

    online   Reads come from the server and are copied into the local cache
             (LocalDataStore) so it is complete when the server goes away.
             Writes go to the local cache first, then to the server.
    offline  Entered when a request fails for a reason that can clear up
             (no network, timeout, 5xx, expired token), or at start-up when
             queued writes are left from an earlier session.  Reads come
             from the local cache and writes are appended to sync_queue,
             both without touching the network, so the UI never waits on a
             dead server.  Only attempt_reconnect() leaves this state: it
             pings the server, replays the queue in order and goes online
             once the queue is empty.

    Invariant: online implies this user has no queued writes.  That is what
    keeps writes ordered (nothing overtakes the queue) and makes it safe to
    overwrite the local cache with server data.

    A write the server rejects outright (4xx other than 401/408/425/429)
    raises APIError: replaying it could never succeed.

    Status callbacks, both invoked on the GUI thread:
      _on_offline_cb(n_pending)   after going offline or queueing a write
      _on_online_cb(synced_count) after a successful reconnect
    """

    def __init__(
            self,
            remote: RemoteDataStore,
            local: "LocalDataStore",
            on_offline_cb=None,  # callable(n_pending: int)
            on_online_cb=None,  # callable(synced_count: int)
    ):
        from . import sync_queue

        self._remote = remote
        self._local = local
        self._on_offline_cb = on_offline_cb
        self._on_online_cb = on_online_cb
        # Guards _is_online, _write_gen and the mirror bookkeeping.  Never
        # held across a network call.
        self._state_lock = threading.RLock()
        # Bumped by every local write; a read that started before the write
        # must not mirror its older server data over it.
        self._write_gen = 0
        # Identity of the remote cache objects last copied into the local
        # cache, so repeated cache hits cost no QSettings writes.
        self._mirrored_src: Dict[str, Any] = {}
        self._mirrored = local.mirrored_datasets()
        self._auth_warned = False
        # Writes left over from an earlier session must reach the server
        # before anything newer does; start offline so the reconnect timer
        # replays them first.
        self._is_online = sync_queue.is_empty(username=self.username)

    # ---- internal ----

    def _pending(self) -> int:
        from . import sync_queue
        return sync_queue.queue_length(username=self.username)

    def _notify_offline(self) -> None:
        if self._on_offline_cb:
            _call_on_gui_thread(self._on_offline_cb, self._pending())

    def _go_offline(self, exc: Exception) -> None:
        with self._state_lock:
            was_online = self._is_online
            self._is_online = False
        if was_online:
            logger.warning("Server unavailable, switching to the local cache: %s", exc)

    def _handle_write_failure(self, _exc: Exception, action: str, payload: dict) -> None:
        """Park a write in the sync queue and switch to offline mode."""
        from . import sync_queue
        with self._state_lock:
            self._is_online = False
            sync_queue.enqueue(self.username, action, payload)
        self._notify_offline()

    def _safe_remote_get(self, fn, fallback_fn, dataset: Optional[str] = None,
                         mirror: Optional[Callable[[], None]] = None):
        """Read from the server when online, otherwise from the local cache.

        `mirror` copies the fresh server data into the local cache.  While
        offline the server is still tried when the local cache has never
        held a full copy of `dataset` (first run after an upgrade): stale
        but complete beats partial.
        """
        with self._state_lock:
            online = self._is_online
            gen = self._write_gen
            cache_complete = dataset is None or dataset in self._mirrored
        if not online and cache_complete:
            return fallback_fn()
        try:
            result = fn()
        except APIError as exc:
            if online and exc.is_transient:
                self._go_offline(exc)
                self._notify_offline()
            else:
                logger.warning("Server refused a read (%s): %s", exc.status_code, exc)
            return fallback_fn()
        except requests.exceptions.RequestException as exc:
            if online:
                self._go_offline(exc)
                self._notify_offline()
            return fallback_fn()
        except Exception:
            # Unexpected response shape.  Keep the UI alive on cached data,
            # but leave a trace: this is a bug, not an outage.
            logger.exception("Remote read failed unexpectedly; using the local cache")
            return fallback_fn()
        if mirror is not None:
            with self._state_lock:
                if self._is_online and gen == self._write_gen:
                    try:
                        mirror()
                    except Exception:
                        logger.exception("Could not update the local cache")
        return result

    def _mirror_once(self, dataset: str, source: Any, write: Callable[[], None]) -> None:
        """Run `write` unless `source` (a remote cache object) was already
        mirrored.  Caller holds _state_lock."""
        if source is None or self._mirrored_src.get(dataset) is source:
            return
        write()
        self._mirrored_src[dataset] = source
        self._mirrored.add(dataset)

    def _mirror_trades(self) -> None:
        cached = self._remote._trade_cache
        self._mirror_once("trades", cached, lambda: self._local.mirror_trades(cached))

    def _mirror_accounts(self) -> None:
        cached = self._remote._account_cache
        self._mirror_once("accounts", cached, lambda: self._local.mirror_accounts(cached))

    def _mirror_goal_group(self) -> None:
        cached = self._remote._goal_group_cache
        self._mirror_once("goal_group", cached, lambda: self._local.mirror_goal_group(*cached))

    def _write(self, action: str, payload_fn: Callable[[], dict],
               local_fn: Callable[[], None], remote_fn: Callable[[], None]) -> None:
        """Shared write path: local cache first, then server or sync queue."""
        from . import sync_queue
        with self._state_lock:
            self._write_gen += 1
            # Always write locally first — instant, no data loss
            local_fn()
            online = self._is_online
            if not online:
                sync_queue.enqueue(self.username, action, payload_fn())
        if not online:
            self._notify_offline()
            return
        try:
            remote_fn()
        except APIError as exc:
            if not exc.is_transient:
                logger.error("Server rejected %s (%s): %s", action, exc.status_code, exc)
                raise
            self._handle_write_failure(exc, action, payload_fn())
        except requests.exceptions.RequestException as exc:
            self._handle_write_failure(exc, action, payload_fn())

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
            dataset="trades", mirror=self._mirror_trades,
        )

    def save_account_trades(self, account_name: str, trades: List[Trade]) -> None:
        self._write(
            "save_trades",
            lambda: {"account_name": account_name, "trades": [trade_to_dict(t) for t in trades]},
            lambda: self._local.save_account_trades(account_name, trades),
            lambda: self._remote.save_account_trades(account_name, trades),
        )

    def save_trade(self, account_name: str, trade: Trade) -> str:
        stored = replace(trade, account=account_name)
        saved_as = [stored.uid]

        def remote() -> None:
            saved_as[0] = self._remote.save_trade(account_name, stored) or stored.uid

        self._write(
            "save_trade",
            lambda: {"account_name": account_name, "trade": trade_to_dict(stored)},
            lambda: self._local.save_trade(account_name, stored),
            lambda: self._remote_trade_write(remote),
        )
        if saved_as[0] != stored.uid:
            # The server stored it under a new uid (the old one was taken):
            # give the local copy the same identity.
            with self._state_lock:
                self._write_gen += 1
                self._local.delete_trade(account_name, stored.uid)
                self._local.save_trade(account_name, replace(stored, uid=saved_as[0]))
        return saved_as[0]

    def delete_trade(self, account_name: str, uid: str) -> None:
        self._write(
            "delete_trade",
            lambda: {"account_name": account_name, "uid": uid},
            lambda: self._local.delete_trade(account_name, uid),
            lambda: self._remote_trade_write(lambda: self._remote.delete_trade(account_name, uid)),
        )

    def _remote_trade_write(self, remote_fn: Callable[[], None]) -> None:
        """Run a per-trade remote write.  The remote store answers it by
        swapping in an updated trade list; the local cache already received
        the same change, so that new list counts as mirrored and the next
        read does not rewrite every cached trade."""
        before = self._remote._trade_cache
        remote_fn()
        after = self._remote._trade_cache
        with self._state_lock:
            if before is not None and after is not None and self._mirrored_src.get("trades") is before:
                self._mirrored_src["trades"] = after

    # ---- accounts ----

    def get_account_names(self) -> List[str]:
        return self._safe_remote_get(
            self._remote.get_account_names,
            self._local.get_account_names,
            dataset="accounts", mirror=self._mirror_accounts,
        )

    def save_accounts(self, accounts: List[str]) -> None:
        self._write(
            "save_accounts",
            lambda: {"accounts": list(accounts)},
            lambda: self._local.save_accounts(accounts),
            lambda: self._remote.save_accounts(accounts),
        )

    # ---- goal targets & presets ----

    def get_goal_target(self, account_name: str) -> float:
        return self._safe_remote_get(
            lambda: self._remote.get_goal_target(account_name),
            lambda: self._local.get_goal_target(account_name),
            dataset="accounts", mirror=self._mirror_accounts,
        )

    def set_goal_target(self, account_name: str, value: float) -> None:
        self._write(
            "set_goal_target",
            lambda: {"account_name": account_name, "value": float(value)},
            lambda: self._local.set_goal_target(account_name, value),
            lambda: self._remote.set_goal_target(account_name, value),
        )

    def get_goal_presets(self, account_name: str) -> List[float]:
        return self._safe_remote_get(
            lambda: self._remote.get_goal_presets(account_name),
            lambda: self._local.get_goal_presets(account_name),
            dataset="accounts", mirror=self._mirror_accounts,
        )

    def set_goal_presets(self, account_name: str, presets: List[float]) -> None:
        self._write(
            "set_goal_presets",
            lambda: {"account_name": account_name, "presets": [float(p) for p in presets]},
            lambda: self._local.set_goal_presets(account_name, presets),
            lambda: self._remote.set_goal_presets(account_name, presets),
        )

    # ---- goal group ----

    def get_goal_group(self) -> Tuple[List[str], float]:
        return self._safe_remote_get(
            self._remote.get_goal_group,
            self._local.get_goal_group,
            dataset="goal_group", mirror=self._mirror_goal_group,
        )

    def set_goal_group(
            self,
            shared_accounts: List[str],
            shared_goal: float,
            individual_goals: Dict[str, float],
            individual_presets: Dict[str, List[float]],
    ) -> None:
        self._write(
            "set_goal_group",
            lambda: {
                "account_names": list(shared_accounts),
                "shared_goal": float(shared_goal),
                "individual_goals": {k: float(v) for k, v in individual_goals.items()},
                "individual_presets": {k: [float(p) for p in v] for k, v in individual_presets.items()},
            },
            lambda: self._local.set_goal_group(shared_accounts, shared_goal, individual_goals, individual_presets),
            lambda: self._remote.set_goal_group(shared_accounts, shared_goal, individual_goals, individual_presets),
        )

    # ---- watchlist ----

    def get_watchlist(self) -> List[str]:
        # RemoteDataStore does not cache the watchlist, so the result itself
        # is what gets mirrored.
        fetched: List[List[str]] = []

        def fetch() -> List[str]:
            fetched.append(self._remote.get_watchlist())
            return fetched[0]

        return self._safe_remote_get(
            fetch,
            self._local.get_watchlist,
            dataset="watchlist",
            mirror=lambda: self._mirror_once(
                "watchlist", fetched[0], lambda: self._local.mirror_watchlist(fetched[0])),
        )

    def save_watchlist(self, symbols: List[str]) -> None:
        self._write(
            "save_watchlist",
            lambda: {"symbols": list(symbols)},
            lambda: self._local.save_watchlist(symbols),
            lambda: self._remote.save_watchlist(symbols),
        )

    # ---- admin passthrough ----

    def store_for_user(self, user_id: int, username: str) -> RemoteDataStore:
        return self._remote.store_for_user(user_id, username)

    def list_users(self) -> List[dict]:
        return self._remote.list_users()

    # ---- reconnect ----

    def attempt_reconnect(self) -> bool:
        """Ping the server and replay the sync queue if it is reachable.

        Returns True once the server is reachable and every queued write
        has been applied (the store is then online again).  Called from
        ReconnectWorker, off the GUI thread, on MainWindow's reconnect timer.
        """
        from . import sync_queue

        try:
            self._remote.check_auth()
        except APIError as exc:
            if exc.status_code == 401 and not self._auth_warned:
                self._auth_warned = True
                logger.warning(
                    "Session expired; %d queued change(s) will sync after the next sign-in",
                    self._pending(),
                )
            return False
        except Exception:
            return False

        # Server is back — flush queued writes
        synced, _failed = sync_queue.flush(self._remote, username=self.username)
        # Whatever was cached before the outage may be out of date now.
        self._remote.invalidate_caches()
        with self._state_lock:
            # Checked under the lock: a write queued during the flush keeps
            # the store offline until the next attempt replays it.
            if self._pending() > 0:
                return False
            self._is_online = True
        if self._on_online_cb:
            _call_on_gui_thread(self._on_online_cb, synced)
        return True

    @property
    def pending_sync_count(self) -> int:
        return self._pending()
