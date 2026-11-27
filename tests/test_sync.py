"""Tests for per-trade saves: DataStore.save_trade / delete_trade on every
store class, the sync queue's per-trade actions, and the fallback to
whole-account saves on a server older than 1.1.

The "server" is an in-process HTTP server on 127.0.0.1 that implements the
routes of docs/api/server-1.1-changes.md (or, in legacy mode, only the 1.0
ones). QSettings is redirected to an .ini under tmp_path and the queue file
to tmp_path, so neither the registry, the real queue nor a real server is
ever touched.
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import replace
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

import pytest
import requests
from PySide6.QtCore import QSettings

from stock_insights import api_client, sync_queue
from stock_insights.api_client import (
    APIError,
    DataStore,
    FallbackDataStore,
    LocalDataStore,
    RemoteDataStore,
)
from stock_insights.portfolio import Trade, trade_to_dict, trades_to_json

USER = "tester"


def T(sym="AAA", qty=10, buy=10.0, account="Main", **kw) -> Trade:
    return Trade(sym, qty, buy, None, date(2024, 1, 2), None, account=account, **kw)


# ---------------------------------------------------------------------------
# Fake server
# ---------------------------------------------------------------------------

class FakeServer:
    """State + request log of the in-process server."""

    def __init__(self, per_trade: bool = True):
        self.per_trade = per_trade  # False = behave like server 1.0
        self.down = False           # True = every request answers 503
        self.needs_migration = False  # True = 1.1 server, database not migrated
        self.foreign_uids = set()   # uids owned by another user (PUT -> 409)
        self.rows = []              # [{account, uid, ...TradeIn fields}], insertion order
        self.accounts = ["Main"]
        self.log = []               # [(method, path)]
        self._next = 0
        self.lock = threading.Lock()
        self.httpd = None

    # -- helpers used by the tests --
    def calls(self, method=None, prefix=""):
        return [(m, p) for m, p in self.log if (method is None or m == method) and p.startswith(prefix)]

    def uids(self, account=None):
        return [r["uid"] for r in self.rows if account is None or r["account"] == account]

    def row(self, uid):
        return next(r for r in self.rows if r["uid"] == uid)

    # -- request handling --
    def _server_uid(self) -> str:
        self._next += 1
        return f"{self._next:032x}"

    def handle(self, method: str, raw_path: str, body):
        path = urlsplit(raw_path).path
        self.log.append((method, path))
        if self.down:
            return 503, {"detail": "down"}
        parts = [unquote(p) for p in path.strip("/").split("/")]
        if parts == ["health"]:
            return 200, {"ok": True, "schema": "needs_migration" if self.needs_migration else "ok"}
        if parts == ["auth", "me"]:
            return 200, {"username": USER}
        if parts == ["accounts"] and method == "GET":
            return 200, [{"name": a, "goal_target": 500000.0, "goal_presets": "[1,2,3]"}
                         for a in self.accounts]
        if parts == ["accounts"] and method == "PUT":
            self.accounts = [a["name"] for a in body["accounts"]]
            self.rows = [r for r in self.rows if r["account"] in self.accounts]
            return 200, {"ok": True}
        if parts == ["trades"] and method == "GET":
            hidden = () if self.per_trade and not self.needs_migration else ("uid", "tag")
            return 200, [{k: v for k, v in r.items() if k not in hidden} for r in self.rows]
        if parts[0] == "trades" and len(parts) == 2 and method == "PUT":
            account = parts[1]
            self._ensure_account(account)
            self.rows = [r for r in self.rows if r["account"] != account]
            for t in body["trades"]:
                self.rows.append({**t, "account": account, "uid": t.get("uid") or self._server_uid()})
            return 200, {"ok": True}
        if parts[0] == "trades" and len(parts) == 3 and self.per_trade:
            account, uid = parts[1], parts[2]
            if self.needs_migration:
                return 503, {"detail": "database needs migration"}
            if method == "PUT" and uid in self.foreign_uids:
                return 409, {"detail": "That trade uid belongs to another user"}
            if method == "PUT":
                self._ensure_account(account)
                row = {**body, "account": account, "uid": uid}
                for i, existing in enumerate(self.rows):
                    if existing["uid"] == uid:
                        self.rows[i] = row
                        break
                else:
                    self.rows.append(row)
                return 200, {"ok": True, "uid": uid}
            if method == "DELETE":
                self.rows = [r for r in self.rows if r["uid"] != uid]
                return 200, {"ok": True}
        return 404, {"detail": "Not Found"}

    def _ensure_account(self, account):
        if account not in self.accounts:
            self.accounts.append(account)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"


def _start(fake: FakeServer) -> None:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _serve(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length)) if length else None
            with fake.lock:
                status, payload = fake.handle(self.command, self.path, body)
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_PUT = do_DELETE = _serve

        def log_message(self, *args):
            pass

    fake.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=fake.httpd.serve_forever, daemon=True).start()


@pytest.fixture
def server():
    fake = FakeServer(per_trade=True)
    _start(fake)
    yield fake
    fake.httpd.shutdown()
    fake.httpd.server_close()


@pytest.fixture
def old_server():
    fake = FakeServer(per_trade=False)
    _start(fake)
    yield fake
    fake.httpd.shutdown()
    fake.httpd.server_close()


def remote_for(fake: FakeServer) -> RemoteDataStore:
    # A plain Session: no automatic retry, so a 503 fails at once.
    return RemoteDataStore(fake.url, "token", {"user_id": 1, "username": USER, "is_admin": False},
                           session=requests.Session())


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Temp QSettings (.ini, never the registry) and a temp queue file.

    QSettings(org, app) always uses the native format (the registry on
    Windows) whatever setDefaultFormat says, so the class LocalDataStore
    instantiates is swapped for one bound to an .ini file under tmp_path.
    """
    ini = tmp_path / "settings.ini"
    monkeypatch.setattr(api_client, "QSettings",
                        lambda *_org_app: QSettings(str(ini), QSettings.Format.IniFormat))
    monkeypatch.setattr(sync_queue, "_QUEUE_FILE", str(tmp_path / "queue.json"))
    probe = LocalDataStore(USER)._settings
    assert probe.format() == QSettings.Format.IniFormat and probe.fileName() == ini.as_posix()
    yield tmp_path


def queued():
    return [(e["action"], e["payload"]) for e in sync_queue._load_raw()]


def queued_actions():
    return [action for action, _ in queued()]


# ---------------------------------------------------------------------------
# DataStore default implementation
# ---------------------------------------------------------------------------

class MemoryStore(DataStore):
    """Only the bulk trade calls, so save_trade/delete_trade are the defaults."""

    def __init__(self, trades=()):
        self.trades = list(trades)
        self.bulk_calls = []

    def get_all_trades(self):
        return list(self.trades)

    def save_account_trades(self, account_name, trades):
        self.bulk_calls.append(account_name)
        self.trades = [t for t in self.trades if t.account != account_name] + list(trades)

    user_info = {"username": USER}
    get_account_names = save_accounts = get_goal_target = set_goal_target = None
    get_goal_presets = set_goal_presets = get_goal_group = set_goal_group = None
    get_watchlist = save_watchlist = None


class TestDefaultImplementation:
    def test_add_edit_delete(self):
        a, b = T("AAA"), T("BBB")
        store = MemoryStore([a])
        store.save_trade("Main", b)
        assert [t.uid for t in store.trades] == [a.uid, b.uid]

        store.save_trade("Main", replace(a, share_count=99))
        assert [t.uid for t in store.trades] == [a.uid, b.uid]  # edited in place
        assert store.trades[0].share_count == 99

        store.delete_trade("Main", a.uid)
        assert [t.uid for t in store.trades] == [b.uid]
        store.delete_trade("Main", "f" * 32)  # unknown uid: no error, no write
        assert store.bulk_calls.count("Main") == 3

    def test_move_rewrites_source_then_destination(self):
        a, b = T("AAA"), T("BBB", account="Other")
        store = MemoryStore([a, b])
        store.save_trade("Other", a)
        assert store.bulk_calls == ["Main", "Other"]
        assert [(t.uid, t.account) for t in store.trades] == [(b.uid, "Other"), (a.uid, "Other")]

    def test_account_argument_wins_over_trade_account(self):
        store = MemoryStore()
        store.save_trade("Main", T(account="Somewhere else"))
        assert store.trades[0].account == "Main"


# ---------------------------------------------------------------------------
# LocalDataStore
# ---------------------------------------------------------------------------

class TestLocalStore:
    def test_save_move_delete(self, isolated):
        store = LocalDataStore(USER)
        a, b = T("AAA", tag="swing"), T("BBB")
        store.save_trade("Main", a)
        store.save_trade("Main", b)
        store.save_trade("Main", replace(a, share_count=7))
        got = store.get_all_trades()
        assert [(t.uid, t.share_count, t.tag) for t in got] == [(a.uid, 7, "swing"), (b.uid, 10, "")]

        store.save_trade("Other", a)  # move
        assert {t.uid: t.account for t in store.get_all_trades()} == {a.uid: "Other", b.uid: "Main"}

        store.delete_trade("Main", a.uid)  # found by uid, whatever the account
        assert [t.uid for t in store.get_all_trades()] == [b.uid]

    def test_survives_a_new_store_object(self, isolated):
        a = T()
        LocalDataStore(USER).save_trade("Main", a)
        assert LocalDataStore(USER).get_all_trades()[0].uid == a.uid

    def test_data_from_before_uids_gets_stable_uids(self, isolated):
        store = LocalDataStore(USER)
        legacy = [{k: v for k, v in trade_to_dict(t).items() if k != "uid"} for t in (T("AAA"), T("BBB"))]
        store._settings.setValue(store._scoped_key(store.TRADES_KEY), json.dumps(legacy))
        first = [t.uid for t in store.get_all_trades()]
        assert first == [t.uid for t in store.get_all_trades()]
        assert first == [t.uid for t in LocalDataStore(USER).get_all_trades()]

        # ...so a per-trade edit of that old data finds its trade.
        edited = replace(store.get_all_trades()[0], share_count=3)
        store.save_trade("Main", edited)
        assert [(t.uid, t.share_count) for t in store.get_all_trades()] == [(first[0], 3), (first[1], 10)]

    def test_bulk_save_still_replaces_the_account(self, isolated):
        store = LocalDataStore(USER)
        store.save_trade("Main", T("AAA"))
        store.save_trade("Other", T("BBB", account="Other"))
        store.save_account_trades("Main", [T("CCC")])
        assert sorted(t.instrument for t in store.get_all_trades()) == ["BBB", "CCC"]


# ---------------------------------------------------------------------------
# RemoteDataStore against a 1.1 server
# ---------------------------------------------------------------------------

class TestRemoteStore:
    def test_save_sends_only_that_trade(self, server):
        store = remote_for(server)
        store.save_account_trades("Main", [T(f"S{i}") for i in range(5)])
        assert len(store.get_all_trades()) == 5
        server.log.clear()

        new = T("NEW", tag="earnings")
        store.save_trade("Main", new)
        assert server.log == [("PUT", f"/trades/Main/{new.uid}")]
        row = server.row(new.uid)
        assert row["tag"] == "earnings" and row["instrument"] == "NEW" and row["account"] == "Main"

        # The cache was updated in place: reading costs no request.
        assert [t.uid for t in store.get_all_trades()][-1] == new.uid
        assert len(store.get_all_trades()) == 6
        assert server.calls("GET") == []

    def test_edit_delete_and_move(self, server):
        store = remote_for(server)
        a, b = T("AAA"), T("BBB")
        store.save_trade("Main", a)
        store.save_trade("Main", b)
        store.save_trade("Main", replace(a, share_count=42))
        assert server.uids() == [a.uid, b.uid] and server.row(a.uid)["share_count"] == 42

        store.save_trade("Other", a)  # a move is one PUT under the new account
        assert server.row(a.uid)["account"] == "Other"
        assert server.calls("PUT")[-1] == ("PUT", f"/trades/Other/{a.uid}")

        store.delete_trade("Other", a.uid)
        store.delete_trade("Other", a.uid)  # idempotent
        assert server.uids() == [b.uid]
        assert [t.uid for t in store.get_all_trades()] == [b.uid]
        assert set(server.calls("PUT", "/trades/")) == {
            ("PUT", f"/trades/Main/{a.uid}"), ("PUT", f"/trades/Main/{b.uid}"),
            ("PUT", f"/trades/Other/{a.uid}")}  # never a whole-account PUT

    def test_cache_matches_a_fresh_fetch(self, server):
        store = remote_for(server)
        store.get_all_trades()
        a, b, c = T("AAA", tag="x"), T("BBB"), T("CCC", account="Other")
        for t in (a, b, c):
            store.save_trade(t.account, t)
        store.save_trade("Other", replace(a, notes="moved"))
        store.delete_trade("Main", b.uid)
        cached = [trade_to_dict(t) for t in store.get_all_trades()]
        assert cached == [trade_to_dict(t) for t in remote_for(server).get_all_trades()]

    def test_cache_is_not_shared_with_the_callers_object(self, server):
        store = remote_for(server)
        store.get_all_trades()
        a = T("AAA")
        store.save_trade("Main", a)
        a.share_count = 999  # caller keeps editing its own object
        assert store.get_all_trades()[0].share_count == 10

    def test_account_and_uid_are_url_encoded(self, server):
        store = remote_for(server)
        name = "My acct/50% ?#"
        a = T(account=name)
        store.save_trade(name, a)
        assert server.row(a.uid)["account"] == name
        assert server.log[-1][1] == f"/trades/My%20acct%2F50%25%20%3F%23/{a.uid}"
        store.delete_trade(name, a.uid)
        assert server.rows == []

    def test_new_account_refreshes_the_account_list(self, server):
        store = remote_for(server)
        assert store.get_account_names() == ["Main"]
        store.save_trade("Brand new", T(account="Brand new"))
        assert store.get_account_names() == ["Main", "Brand new"]

    def test_failed_save_drops_the_cache(self, server):
        store = remote_for(server)
        a = T()
        store.save_trade("Main", a)
        store.get_all_trades()
        server.down = True
        with pytest.raises(APIError):
            store.save_trade("Main", replace(a, share_count=5))
        server.down = False
        server.log.clear()
        assert store.get_all_trades()[0].share_count == 10
        assert server.calls("GET", "/trades") == [("GET", "/trades")]

    def test_404_after_the_routes_worked_is_an_error(self, server):
        store = remote_for(server)
        store.save_trade("Main", T())
        server.per_trade = False  # e.g. a proxy misroute; not "old server"
        with pytest.raises(APIError) as exc:
            store.save_trade("Main", T("BBB"))
        assert exc.value.status_code == 404
        assert server.calls("PUT", "/trades/")[-1][1].count("/") == 3  # no bulk fallback

    def test_reads_uid_and_tag_from_the_server(self, server):
        a = T(tag="swing")
        remote_for(server).save_trade("Main", a)
        got = remote_for(server).get_all_trades()
        assert [(t.uid, t.tag, t.account) for t in got] == [(a.uid, "swing", "Main")]


class TestUidConflict:
    def test_409_saves_under_a_new_uid_once(self, server):
        store = remote_for(server)
        store.get_all_trades()
        a = T("AAA")
        server.foreign_uids.add(a.uid)
        saved_as = store.save_trade("Main", a)
        assert saved_as != a.uid and server.uids() == [saved_as]
        assert [m for m, _ in server.calls("PUT", "/trades/")] == ["PUT", "PUT"]
        assert [t.uid for t in store.get_all_trades()] == [saved_as]
        assert store.save_trade("Main", T("BBB")) not in (a.uid, saved_as)

    def test_409_twice_is_raised_not_retried(self, server, monkeypatch):
        store = remote_for(server)
        monkeypatch.setattr(api_client, "new_trade_uid", lambda: "e" * 32)
        a = T()
        server.foreign_uids.update({a.uid, "e" * 32})
        with pytest.raises(APIError) as exc:
            store.save_trade("Main", a)
        assert exc.value.status_code == 409 and not exc.value.is_transient
        assert len(server.calls("PUT", "/trades/")) == 2 and server.rows == []

    def test_fallback_store_renames_the_local_copy(self, isolated, server):
        store, events = fallback_for(server)
        a = T("AAA", tag="swing")
        server.foreign_uids.add(a.uid)
        saved_as = store.save_trade("Main", a)
        assert saved_as != a.uid and server.uids() == [saved_as]
        assert [(t.uid, t.tag) for t in LocalDataStore(USER).get_all_trades()] == [(saved_as, "swing")]
        assert [t.uid for t in store.get_all_trades()] == [saved_as]
        assert sync_queue.is_empty(USER) and events == []

    def test_queued_save_with_a_taken_uid_is_resolved_on_replay(self, isolated, server):
        a = T("AAA")
        q_save(a)
        server.foreign_uids.add(a.uid)
        store, _ = fallback_for(server)  # starts offline: the queue is not empty
        assert store.attempt_reconnect()
        assert sync_queue.is_empty(USER)
        assert len(server.rows) == 1 and server.uids() != [a.uid]
        # The next read mirrors the server's uid into the local cache.
        assert [t.uid for t in store.get_all_trades()] == server.uids()
        assert [t.uid for t in LocalDataStore(USER).get_all_trades()] == server.uids()


class TestUnmigratedServer:
    """1.1 server whose database lacks the new columns: per-trade routes
    answer 503, /health says needs_migration, the bulk route works."""

    def test_503_with_needs_migration_falls_back_to_bulk(self, isolated, server, caplog):
        server.needs_migration = True
        store, events = fallback_for(server)
        a, b = T("AAA"), T("BBB")
        with caplog.at_level(logging.WARNING):
            store.save_trade("Main", a)
            store.save_trade("Main", replace(a, share_count=4))
            store.save_trade("Main", b)
            store.delete_trade("Main", b.uid)
        assert [(r["instrument"], r["share_count"]) for r in server.rows] == [("AAA", 4)]
        assert events == [] and sync_queue.is_empty(USER)  # never went offline
        assert len(server.calls(prefix="/trades/Main/")) == 1  # one probe only
        assert len(server.calls("GET", "/health")) == 1
        assert len([r for r in caplog.records if "Per-trade saves are not available" in r.getMessage()]) == 1
        assert [t.uid for t in store.get_all_trades()] == [a.uid]

    def test_plain_503_is_still_an_outage(self, isolated, server):
        store, events = fallback_for(server)
        store.save_trade("Main", T("AAA"))
        server.down = True
        store.save_trade("Main", T("BBB"))
        assert queued_actions() == ["save_trade"] and events[-1] == ("offline", 1)
        assert store._remote._per_trade_routes is True
        server.down = False
        assert store.attempt_reconnect()
        assert [r["instrument"] for r in server.rows] == ["AAA", "BBB"]

    def test_queue_replays_through_the_bulk_route(self, isolated, server):
        server.needs_migration = True
        a = T("AAA")
        q_save(a)
        q_save(T("BBB"))
        q_delete(a.uid)
        assert sync_queue.flush(remote_for(server), username=USER) == (2, 0)
        assert [r["instrument"] for r in server.rows] == ["BBB"]


# ---------------------------------------------------------------------------
# RemoteDataStore against a server without the per-trade routes
# ---------------------------------------------------------------------------

class TestOldServer:
    def test_falls_back_to_whole_account_and_remembers(self, old_server, caplog):
        store = remote_for(old_server)
        a, b = T("AAA"), T("BBB")
        with caplog.at_level(logging.WARNING):
            store.save_trade("Main", a)
            store.save_trade("Main", b)
            store.delete_trade("Main", "f" * 32)
        assert [r["instrument"] for r in old_server.rows] == ["AAA", "BBB"]
        # One probe of the new route, then whole-account PUTs only.
        assert old_server.calls("PUT", "/trades/") == [
            ("PUT", f"/trades/Main/{a.uid}"), ("PUT", "/trades/Main"), ("PUT", "/trades/Main")]
        assert old_server.calls("DELETE") == []
        assert len([r for r in caplog.records if "Per-trade saves are not available" in r.getMessage()]) == 1

    def test_first_call_being_a_delete_also_falls_back(self, old_server):
        store = remote_for(old_server)
        store.save_account_trades("Main", [T("AAA"), T("BBB")])
        victim = store.get_all_trades()[0]
        store.delete_trade("Main", victim.uid)
        assert [r["instrument"] for r in old_server.rows] == ["BBB"]

    def test_uids_are_stable_across_fetches_so_edits_do_not_duplicate(self, old_server):
        store = remote_for(old_server)
        store.save_account_trades("Main", [T("AAA"), T("AAA"), T("BBB")])  # two identical rows
        first = store.get_all_trades()
        assert len({t.uid for t in first}) == 3
        store.invalidate_caches()
        assert [t.uid for t in store.get_all_trades()] == [t.uid for t in first]

        store.save_trade("Main", replace(first[1], share_count=77))
        # The cache was dropped by the bulk save; a trade read before it can
        # still be edited afterwards.
        store.save_trade("Main", replace(first[2], notes="later"))
        rows = old_server.rows
        assert [(r["instrument"], r["share_count"], r["notes"]) for r in rows] == [
            ("AAA", 10, ""), ("AAA", 77, ""), ("BBB", 10, "later")]
        # Edited trades keep their uid through the refetch as well.
        assert [t.uid for t in store.get_all_trades()] == [t.uid for t in first]

    def test_a_trade_added_this_session_keeps_its_uid(self, old_server):
        store = remote_for(old_server)
        a = T("AAA", tag="swing")
        store.save_trade("Main", a)
        store.save_trade("Main", replace(a, share_count=6))  # same object's uid, after a refetch
        store.save_trade("Main", T("AAA", qty=6))            # identical content, different trade
        assert [(r["instrument"], r["share_count"]) for r in old_server.rows] == [("AAA", 6), ("AAA", 6)]
        got = store.get_all_trades()
        assert got[0].uid == a.uid and len({t.uid for t in got}) == 2
        store.delete_trade("Main", a.uid)
        assert len(old_server.rows) == 1

    def test_move_and_delete(self, old_server):
        store = remote_for(old_server)
        store.save_account_trades("Main", [T("AAA"), T("BBB")])
        a, b = store.get_all_trades()
        store.save_trade("Other", a)
        assert [(r["instrument"], r["account"]) for r in old_server.rows] == [("BBB", "Main"), ("AAA", "Other")]
        moved = next(t for t in store.get_all_trades() if t.instrument == "AAA")
        store.delete_trade("Other", moved.uid)
        assert [r["instrument"] for r in old_server.rows] == ["BBB"]

    def test_admin_scoped_store_inherits_the_knowledge(self, old_server):
        store = remote_for(old_server)
        store.save_trade("Main", T())
        scoped = store.store_for_user(2, "other")
        old_server.log.clear()
        scoped.save_trade("Main", T("BBB"))
        assert all(p.count("/") == 2 for _, p in old_server.calls("PUT", "/trades/"))


# ---------------------------------------------------------------------------
# sync_queue: per-trade actions
# ---------------------------------------------------------------------------

def q_save(trade, account="Main", user=USER):
    sync_queue.enqueue(user, "save_trade", {"account_name": account, "trade": trade_to_dict(trade)})


def q_delete(uid, account="Main", user=USER):
    sync_queue.enqueue(user, "delete_trade", {"account_name": account, "uid": uid})


class TestQueueCoalescing:
    def test_later_save_replaces_earlier_save_of_same_trade(self, isolated):
        a, b = T("AAA"), T("BBB")
        q_save(a)
        q_save(b)
        q_save(replace(a, share_count=5), account="Other")
        assert queued_actions() == ["save_trade", "save_trade"]
        (_, first), (_, second) = queued()
        assert first["trade"]["uid"] == b.uid
        assert second["trade"]["uid"] == a.uid and second["trade"]["share_count"] == 5
        assert second["account_name"] == "Other"

    def test_delete_after_save_drops_the_save(self, isolated):
        a = T()
        q_save(a)
        q_delete(a.uid)
        assert queued() == [("delete_trade", {"account_name": "Main", "uid": a.uid})]
        q_delete(a.uid)
        assert queued_actions() == ["delete_trade"]

    def test_save_after_delete_keeps_both(self, isolated):
        a = T()
        q_delete(a.uid)
        q_save(a)
        assert queued_actions() == ["delete_trade", "save_trade"]

    def test_never_across_a_whole_account_save(self, isolated):
        a = T()
        q_save(a)
        sync_queue.enqueue(USER, "save_trades", {"account_name": "Main", "trades": []})
        q_save(replace(a, share_count=2))
        assert queued_actions() == ["save_trade", "save_trades", "save_trade"]
        q_delete(a.uid)  # merges with the save after the barrier only
        assert queued_actions() == ["save_trade", "save_trades", "delete_trade"]

    def test_never_across_a_structural_write(self, isolated):
        a = T()
        q_save(a)
        sync_queue.enqueue(USER, "save_accounts", {"accounts": ["Main"]})
        q_save(a)
        assert queued_actions() == ["save_trade", "save_accounts", "save_trade"]

    def test_other_writes_in_between_do_not_block(self, isolated):
        a = T()
        q_save(a)
        sync_queue.enqueue(USER, "save_watchlist", {"symbols": ["X"]})
        sync_queue.enqueue(USER, "set_goal_target", {"account_name": "Main", "value": 1.0})
        q_save(replace(a, notes="n"))
        assert queued_actions() == ["save_watchlist", "set_goal_target", "save_trade"]

    def test_users_are_kept_apart(self, isolated):
        a = T()
        q_save(a, user="alice")
        q_save(a, user="bob")
        q_delete(a.uid, user="alice")
        assert [(e["username"], e["action"]) for e in sync_queue._load_raw()] == [
            ("bob", "save_trade"), ("alice", "delete_trade")]

    def test_whole_account_saves_still_merge_with_each_other(self, isolated):
        for n in (1, 2):
            sync_queue.enqueue(USER, "save_trades", {"account_name": "Main", "trades": [trade_to_dict(T(qty=n))]})
        assert queued_actions() == ["save_trades"]


class TestQueueReplay:
    def test_replays_in_order_against_the_server(self, isolated, server):
        a, b, c = T("AAA"), T("BBB"), T("CCC")
        q_save(a)
        q_save(b)
        q_save(replace(a, share_count=3))  # coalesced into the first save
        q_delete(b.uid)                    # drops b's save
        q_save(c, account="Other")
        assert sync_queue.flush(remote_for(server), username=USER) == (3, 0)
        assert sync_queue.is_empty(USER)
        assert [(r["instrument"], r["account"], r["share_count"]) for r in server.rows] == [
            ("AAA", "Main", 3), ("CCC", "Other", 10)]
        assert [m for m, _ in server.log] == ["PUT", "DELETE", "PUT"]

    def test_entries_queued_by_older_versions_still_replay(self, isolated, server):
        # 1.0 queued whole accounts, and its trades had no uid.
        old_trades = [{k: v for k, v in trade_to_dict(t).items() if k != "uid"} for t in (T("AAA"), T("BBB"))]
        sync_queue.enqueue(USER, "save_trades", {"account_name": "Main", "trades": old_trades})
        late = T("CCC")
        q_save(late)
        assert sync_queue.flush(remote_for(server), username=USER) == (2, 0)
        assert [r["instrument"] for r in server.rows] == ["AAA", "BBB", "CCC"]
        assert server.calls("PUT") == [("PUT", "/trades/Main"), ("PUT", f"/trades/Main/{late.uid}")]

    def test_replay_twice_is_harmless(self, isolated, server):
        a = T()
        store = remote_for(server)
        for _ in range(2):
            q_save(a)
            sync_queue.flush(store, username=USER)
        assert server.uids() == [a.uid]

    def test_replay_against_an_old_server(self, isolated, old_server):
        a, b = T("AAA"), T("BBB")
        q_save(a)
        q_save(b)
        q_delete(a.uid)
        assert sync_queue.flush(remote_for(old_server), username=USER) == (2, 0)
        assert [r["instrument"] for r in old_server.rows] == ["BBB"]

    def test_outage_keeps_the_entries(self, isolated, server):
        q_save(T())
        server.down = True
        assert sync_queue.flush(remote_for(server), username=USER) == (0, 1)
        assert queued_actions() == ["save_trade"]

    def test_unreadable_entry_is_set_aside(self, isolated, server):
        sync_queue.enqueue(USER, "save_trade", {"account_name": "Main", "trade": {"instrument": ""}})
        q_save(T("OK"))
        assert sync_queue.flush(remote_for(server), username=USER) == (1, 1)
        assert sync_queue.is_empty(USER)
        assert [r["instrument"] for r in server.rows] == ["OK"]


# ---------------------------------------------------------------------------
# FallbackDataStore
# ---------------------------------------------------------------------------

def fallback_for(fake: FakeServer):
    events = []
    store = FallbackDataStore(
        remote_for(fake), LocalDataStore(USER),
        on_offline_cb=lambda n: events.append(("offline", n)),
        on_online_cb=lambda n: events.append(("online", n)),
    )
    return store, events


class TestFallbackStore:
    def test_online_write_goes_to_mirror_and_server(self, isolated, server):
        store, events = fallback_for(server)
        a = T(tag="swing")
        store.save_trade("Main", a)
        assert server.uids() == [a.uid]
        assert [(t.uid, t.tag) for t in LocalDataStore(USER).get_all_trades()] == [(a.uid, "swing")]
        assert sync_queue.is_empty(USER) and events == []

    def test_per_trade_save_does_not_rewrite_the_mirror_on_the_next_read(self, isolated, server, monkeypatch):
        store, _ = fallback_for(server)
        store.save_account_trades("Main", [T("AAA"), T("BBB")])
        store.get_all_trades()  # mirrors the server list once
        mirrored = []
        monkeypatch.setattr(store._local, "mirror_trades", lambda trades: mirrored.append(len(trades)))
        store.save_trade("Main", T("CCC"))
        assert len(store.get_all_trades()) == 3
        assert mirrored == []
        assert len(LocalDataStore(USER).get_all_trades()) == 3

    def test_offline_writes_are_queued_per_trade_and_replayed(self, isolated, server):
        store, events = fallback_for(server)
        a, b = T("AAA"), T("BBB")
        store.save_trade("Main", a)
        server.down = True

        store.save_trade("Main", b)                         # this one discovers the outage
        store.save_trade("Main", replace(b, share_count=4))  # queued without a request
        store.save_trade("Other", a)                        # move, offline
        store.delete_trade("Main", b.uid)
        assert queued_actions() == ["save_trade", "delete_trade"]
        assert events[-1] == ("offline", 2)
        # Reads come from the mirror and show every offline edit.
        assert [(t.uid, t.account) for t in store.get_all_trades()] == [(a.uid, "Other")]
        assert not store.attempt_reconnect()

        server.down = False
        server.log.clear()
        assert store.attempt_reconnect()
        assert events[-1] == ("online", 2)
        assert sync_queue.is_empty(USER)
        assert [(r["uid"], r["account"]) for r in server.rows] == [(a.uid, "Other")]
        assert server.calls("PUT", "/trades/") == [("PUT", f"/trades/Other/{a.uid}")]
        assert [(t.uid, t.account) for t in store.get_all_trades()] == [(a.uid, "Other")]

    def test_starts_offline_when_an_older_version_left_a_queue(self, isolated, server):
        sync_queue.enqueue(USER, "save_trades", {"account_name": "Main", "trades": [
            {k: v for k, v in trade_to_dict(T("OLD")).items() if k != "uid"}]})
        store, _ = fallback_for(server)
        new = T("NEW")
        store.save_trade("Main", new)  # queued behind the old entry, no request yet
        assert server.log == []
        assert queued_actions() == ["save_trades", "save_trade"]
        assert store.attempt_reconnect()
        assert [r["instrument"] for r in server.rows] == ["OLD", "NEW"]

    def test_old_server_through_the_fallback_store(self, isolated, old_server):
        store, _ = fallback_for(old_server)
        a = T("AAA")
        store.save_trade("Main", a)
        store.save_trade("Main", replace(a, share_count=6))
        b = T("BBB")
        store.save_trade("Main", b)
        assert [(r["instrument"], r["share_count"]) for r in old_server.rows] == [("AAA", 6), ("BBB", 10)]
        # Old servers store no uid, yet the trades keep the ones they were
        # saved under for the rest of the session.
        assert [t.uid for t in store.get_all_trades()] == [a.uid, b.uid]
        store.delete_trade("Main", a.uid)
        assert [r["instrument"] for r in old_server.rows] == ["BBB"]
        assert [t.instrument for t in store.get_all_trades()] == ["BBB"]

    def test_rejected_write_raises_and_is_not_queued(self, isolated, server, monkeypatch):
        store, _ = fallback_for(server)

        def refuse(*_a, **_k):
            raise APIError("tag too long", 422)

        monkeypatch.setattr(store._remote, "save_trade", refuse)
        with pytest.raises(APIError):
            store.save_trade("Main", T())
        assert sync_queue.is_empty(USER)
