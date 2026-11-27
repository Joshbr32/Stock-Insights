"""Tests for server/server.py without SQL Server or network.

pyodbc is replaced by a tiny sqlite-backed fake before server.py is imported,
and routes are driven with raw ASGI calls (httpx / TestClient is not a
dependency of this project). The sqlite schema mirrors the 1.1 SQL Server
schema closely enough for the queries server.py runs; T-SQL-only code (the
start-up migration) is exercised through its failure path only.
"""
from __future__ import annotations

import asyncio
import gzip
import hashlib
import importlib.util
import json
import sqlite3
import sys
import types
import urllib.parse
from datetime import timedelta
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("pydantic")

ROOT = Path(__file__).resolve().parent.parent

SCHEMA = """
CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT,
                   is_admin INT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE sessions(token TEXT PRIMARY KEY, user_id INT, expires_at TEXT);
CREATE TABLE accounts(id INTEGER PRIMARY KEY, user_id INT, name TEXT,
                      goal_target REAL DEFAULT 500000, goal_presets TEXT DEFAULT '[]',
                      position INT DEFAULT 0, UNIQUE(user_id, name));
CREATE TABLE trades(id INTEGER PRIMARY KEY, account_id INT, instrument TEXT, share_count INT,
                    buy_price REAL, sell_price REAL, open_date TEXT, close_date TEXT, notes TEXT,
                    is_pending INT, is_short INT, tag TEXT NOT NULL DEFAULT '', client_id TEXT);
CREATE UNIQUE INDEX UX_trades_client_id ON trades(client_id) WHERE client_id IS NOT NULL;
CREATE TABLE goal_group(user_id INT PRIMARY KEY, account_names TEXT, shared_goal REAL);
CREATE TABLE watchlist(user_id INT, symbol TEXT, position INT);
"""


class _FakeDB:
    """Holds the sqlite connection the fake pyodbc hands out."""

    conn: sqlite3.Connection = None  # type: ignore[assignment]
    fail_connect = False


class _Cur:
    def __init__(self):
        self.c = _FakeDB.conn.cursor()

    @staticmethod
    def _sql(sql):
        return sql.replace("dbo.", "")

    @staticmethod
    def _params(params):
        return tuple(p.isoformat() if hasattr(p, "isoformat") else p for p in params)

    def execute(self, sql, params=()):
        self.c.execute(self._sql(sql), self._params(params))
        return self

    def executemany(self, sql, rows):
        self.c.executemany(self._sql(sql), [self._params(r) for r in rows])

    @property
    def description(self):
        return self.c.description

    @property
    def rowcount(self):
        return self.c.rowcount

    def fetchone(self):
        return self.c.fetchone()

    def fetchall(self):
        return self.c.fetchall()


class _Conn:
    def cursor(self):
        return _Cur()

    def commit(self):
        _FakeDB.conn.commit()

    def rollback(self):
        _FakeDB.conn.rollback()

    def close(self):
        pass


def _connect(*_a, **_k):
    if _FakeDB.fail_connect:
        raise sqlite3.OperationalError("login lacks permission (fake)")
    return _Conn()


@pytest.fixture(scope="module")
def srv():
    fake = types.ModuleType("pyodbc")
    fake.drivers = lambda: ["ODBC Driver 18 for SQL Server"]
    fake.connect = _connect
    fake.Error = sqlite3.Error
    fake.IntegrityError = sqlite3.IntegrityError
    saved = sys.modules.get("pyodbc")
    sys.modules["pyodbc"] = fake
    mp = pytest.MonkeyPatch()
    mp.setenv("PORTFOLIO_SQL_PASSWORD", "x")
    mp.delenv("PORTFOLIO_ENABLE_DOCS", raising=False)
    try:
        spec = importlib.util.spec_from_file_location("si_server_under_test",
                                                      ROOT / "server" / "server.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        yield mod
    finally:
        mp.undo()
        if saved is None:
            sys.modules.pop("pyodbc", None)
        else:
            sys.modules["pyodbc"] = saved


@pytest.fixture
def server(srv, monkeypatch):
    """Fresh database + two users (admin/pw, bob/pw2) for every test."""
    _FakeDB.conn = sqlite3.connect(":memory:", check_same_thread=False)
    _FakeDB.conn.executescript(SCHEMA)
    _FakeDB.fail_connect = False
    _FakeDB.conn.execute("INSERT INTO users(username, password_hash, is_admin) VALUES (?, ?, 1)",
                         ("admin", srv._hash_password("pw")))
    _FakeDB.conn.execute("INSERT INTO users(username, password_hash, is_admin) VALUES (?, ?, 0)",
                         ("bob", srv._hash_password("pw2")))
    _FakeDB.conn.commit()
    monkeypatch.setattr(srv, "_SCHEMA", {"ok": True, "trade_cols": True, "password_wide": True})
    monkeypatch.setattr(srv, "_health_cache", {"at": 0.0, "db_ok": False})
    srv._LOGIN_FAILS.clear()
    yield srv
    _FakeDB.conn.close()


def call(srv, method, path, body=None, token=None):
    """Run one request through the ASGI app; return (status, json_or_None)."""
    qs = b""
    if "?" in path:
        path, q = path.split("?", 1)
        qs = q.encode()
    headers = [(b"host", b"test")]
    if token:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    data = json.dumps(body).encode() if body is not None else b""
    if body is not None:
        headers.append((b"content-type", b"application/json"))
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": method, "scheme": "http", "path": urllib.parse.unquote(path),
        "raw_path": path.encode(), "root_path": "", "query_string": qs,
        "headers": headers, "client": ("1.2.3.4", 5), "server": ("test", 80),
    }
    out = {"body": b"", "headers": {}}

    async def run():
        sent = False

        async def receive():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": data, "more_body": False}
            await asyncio.sleep(10)
            return {"type": "http.disconnect"}

        async def send(msg):
            if msg["type"] == "http.response.start":
                out["status"] = msg["status"]
                out["headers"] = {k.decode(): v.decode() for k, v in msg["headers"]}
            elif msg["type"] == "http.response.body":
                out["body"] += msg.get("body", b"")

        await srv.app(scope, receive, send)

    asyncio.run(run())
    raw = out["body"]
    if out["headers"].get("content-encoding") == "gzip":
        raw = gzip.decompress(raw)
    try:
        payload = json.loads(raw)
    except ValueError:
        payload = None
    return out["status"], payload


def login(srv, username="admin", password="pw"):
    status, body = call(srv, "POST", "/auth/login", {"username": username, "password": password})
    assert status == 200, body
    return body["token"]


def q(sql, *params):
    return _FakeDB.conn.execute(sql, params).fetchall()


TRADE = {"instrument": "AAPL", "share_count": 3, "buy_price": 1.5}
U1, U2, U3 = "a" * 32, "b" * 32, "c" * 32


# ---- auth -------------------------------------------------------------------

def test_login_stores_hashed_token(server):
    token = login(server)
    stored = [r[0] for r in q("SELECT token FROM sessions")]
    assert stored == [hashlib.sha256(token.encode()).hexdigest()]
    assert token not in stored
    assert call(server, "GET", "/auth/me", token=token)[0] == 200
    assert call(server, "GET", "/auth/me", token="0" * 64)[0] == 401


def test_new_password_hash_is_scrypt(server):
    (h,) = q("SELECT password_hash FROM users WHERE username = 'admin'")[0]
    assert h.startswith("scrypt$15$8$1$") and len(h) <= 255
    assert server._DUMMY_HASH.startswith("scrypt$15$8$1$")
    assert server._verify_password("pw", h) and not server._verify_password("nope", h)


def test_legacy_raw_token_upgraded(server, monkeypatch):
    raw = "d" * 64
    expiry = server._utc_now() + timedelta(days=1)
    monkeypatch.setattr(server, "_LEGACY_TOKEN_CUTOFF", expiry + timedelta(days=1))
    _FakeDB.conn.execute("INSERT INTO sessions VALUES (?, 1, ?)", (raw, expiry.isoformat()))
    _FakeDB.conn.commit()
    status, me = call(server, "GET", "/auth/me", token=raw)
    assert status == 200 and me["username"] == "admin"
    assert [r[0] for r in q("SELECT token FROM sessions")] == [hashlib.sha256(raw.encode()).hexdigest()]
    assert call(server, "GET", "/auth/me", token=raw)[0] == 200  # now found by hash
    assert call(server, "POST", "/auth/logout", token=raw)[1] == {"ok": True}
    assert q("SELECT COUNT(*) FROM sessions")[0][0] == 0


def test_stored_hash_cannot_be_replayed_as_token(server, monkeypatch):
    login(server)
    (digest,) = q("SELECT token FROM sessions")[0]
    monkeypatch.setattr(server, "_LEGACY_TOKEN_CUTOFF", server._utc_now() + timedelta(days=2))
    assert call(server, "GET", "/auth/me", token=digest)[0] == 401


def test_legacy_pbkdf2_hash_rehashed_on_login(server):
    legacy = server._hash_password_pbkdf2("old")
    assert ":" in legacy and not legacy.startswith("scrypt$")
    _FakeDB.conn.execute("UPDATE users SET password_hash = ? WHERE username = 'bob'", (legacy,))
    _FakeDB.conn.commit()
    assert call(server, "POST", "/auth/login", {"username": "bob", "password": "bad"})[0] == 401
    assert q("SELECT password_hash FROM users WHERE username = 'bob'")[0][0] == legacy
    login(server, "bob", "old")
    (new,) = q("SELECT password_hash FROM users WHERE username = 'bob'")[0]
    assert new.startswith("scrypt$") and server._verify_password("old", new)
    login(server, "bob", "old")  # still works with the new hash


def test_password_change_keeps_only_callers_session(server):
    admin = login(server)
    bob = login(server, "bob", "pw2")
    assert call(server, "PUT", "/users/2/password", {"new_password": "n"}, admin)[1] == {"ok": True}
    assert call(server, "GET", "/auth/me", token=bob)[0] == 401
    assert call(server, "GET", "/auth/me", token=admin)[0] == 200
    bob_self = login(server, "bob", "n")
    assert call(server, "PUT", "/users/2/password", {"new_password": "m"}, bob_self)[1] == {"ok": True}
    assert call(server, "GET", "/auth/me", token=bob_self)[0] == 200


# ---- trades -----------------------------------------------------------------

def test_per_trade_upsert_move_and_delete_are_idempotent(server):
    tok = login(server)
    body = dict(TRADE, tag="swing")
    for _ in range(2):  # replaying the same save must not duplicate
        status, resp = call(server, "PUT", f"/trades/Main/{U1}", body, tok)
        assert status == 200 and resp == {"ok": True, "uid": U1}
    trades = call(server, "GET", "/trades", token=tok)[1]
    assert len(trades) == 1
    assert trades[0]["uid"] == U1 and trades[0]["tag"] == "swing" and trades[0]["account"] == "Main"

    # update in place + move to a new (auto-created) account
    call(server, "PUT", f"/trades/Other%20Acct/{U1}", dict(TRADE, share_count=9), tok)
    trades = call(server, "GET", "/trades", token=tok)[1]
    assert len(trades) == 1
    assert trades[0]["account"] == "Other Acct" and trades[0]["share_count"] == 9
    assert trades[0]["tag"] == ""

    for _ in range(2):
        assert call(server, "DELETE", f"/trades/Other%20Acct/{U1}", token=tok) == (200, {"ok": True})
    assert call(server, "GET", "/trades", token=tok)[1] == []


def test_per_trade_routes_are_scoped_per_user(server):
    admin = login(server)
    bob = login(server, "bob", "pw2")
    call(server, "PUT", f"/trades/Main/{U1}", TRADE, admin)
    # bob can neither delete nor take over admin's trade
    assert call(server, "DELETE", f"/trades/Main/{U1}", token=bob) == (200, {"ok": True})
    assert call(server, "PUT", f"/trades/Main/{U1}", TRADE, bob)[0] == 409
    assert len(call(server, "GET", "/trades", token=admin)[1]) == 1
    assert call(server, "GET", "/trades", token=bob)[1] == []
    # admin acts for bob with for_user_id; bob may not act for admin
    assert call(server, "PUT", f"/trades/Bobs/{U2}?for_user_id=2", TRADE, admin)[0] == 200
    assert [t["uid"] for t in call(server, "GET", "/trades", token=bob)[1]] == [U2]
    assert call(server, "PUT", f"/trades/Main/{U3}?for_user_id=1", TRADE, bob)[0] == 403
    assert call(server, "DELETE", f"/trades/Bobs/{U2}?for_user_id=2", token=admin)[0] == 200
    assert call(server, "GET", "/trades", token=bob)[1] == []


def test_invalid_uid_and_tag_rejected(server):
    tok = login(server)
    assert call(server, "PUT", "/trades/Main/NOT-A-UID", TRADE, tok)[0] == 422
    assert call(server, "PUT", f"/trades/Main/{U1.upper()}", TRADE, tok)[0] == 422
    assert call(server, "PUT", f"/trades/Main/{U1}", dict(TRADE, tag="x" * 41), tok)[0] == 422
    bad = {"account_name": "Main", "trades": [dict(TRADE, uid="xyz")]}
    assert call(server, "PUT", "/trades/Main", bad, tok)[0] == 422


def test_bulk_replace_keeps_given_uids_and_tags(server):
    tok = login(server)
    batch = {"account_name": "Main", "trades": [
        dict(TRADE, uid=U1, tag="core"), dict(TRADE, instrument="MSFT"), dict(TRADE, uid=U2)]}
    assert call(server, "PUT", "/trades/Main", batch, tok)[1] == {"ok": True}
    trades = call(server, "GET", "/trades", token=tok)[1]
    assert [t["uid"] for t in trades][0::2] == [U1, U2]
    generated = trades[1]["uid"]
    assert len(generated) == 32 and generated not in (U1, U2)
    assert [t["tag"] for t in trades] == ["core", "", ""]

    # A 1.0 client re-saves without uids/tags: unchanged trades keep both.
    old_client = {"account_name": "Main", "trades": [
        TRADE, dict(TRADE, instrument="MSFT"), dict(TRADE, share_count=7)]}
    call(server, "PUT", "/trades/Main", old_client, tok)
    after = call(server, "GET", "/trades", token=tok)[1]
    assert len(after) == 3
    assert {t["uid"] for t in after} >= {U1, generated}
    assert [t["tag"] for t in after if t["uid"] == U1] == ["core"]


def test_bulk_replace_moves_uid_from_other_account(server):
    tok = login(server)
    call(server, "PUT", f"/trades/A/{U1}", TRADE, tok)
    call(server, "PUT", "/trades/B", {"account_name": "B", "trades": [dict(TRADE, uid=U1)]}, tok)
    trades = call(server, "GET", "/trades", token=tok)[1]
    assert [(t["account"], t["uid"]) for t in trades] == [("B", U1)]


def test_bulk_replace_never_steals_another_users_uid(server):
    admin = login(server)
    call(server, "PUT", f"/trades/Main/{U1}", TRADE, admin)
    bob = login(server, "bob", "pw2")
    call(server, "PUT", "/trades/Main", {"account_name": "Main", "trades": [dict(TRADE, uid=U1)]}, bob)
    assert [t["uid"] for t in call(server, "GET", "/trades", token=admin)[1]] == [U1]
    bob_trades = call(server, "GET", "/trades", token=bob)[1]
    assert len(bob_trades) == 1 and bob_trades[0]["uid"] != U1


def test_get_trades_backfills_missing_uid(server):
    tok = login(server)
    call(server, "PUT", "/accounts", {"accounts": [{"name": "Main"}]}, tok)
    _FakeDB.conn.execute("INSERT INTO trades(account_id, instrument, share_count, buy_price, "
                         "is_pending, is_short) VALUES (1, 'X', 1, 1, 0, 0)")
    _FakeDB.conn.commit()
    (t,) = call(server, "GET", "/trades", token=tok)[1]
    assert len(t["uid"]) == 32 and t["tag"] == ""
    assert q("SELECT client_id FROM trades")[0][0] == t["uid"]


# ---- schema / docs / health -------------------------------------------------

def test_docs_disabled_by_default(server):
    assert server.DOCS_ENABLED is False
    for path in ("/docs", "/redoc", "/openapi.json"):
        status, body = call(server, "GET", path)
        assert status == 404 or not (isinstance(body, dict) and "openapi" in body), path


def test_health_reports_schema(server):
    status, body = call(server, "GET", "/health")
    assert status == 200 and body["schema"] == "ok" and body["db_ok"] is True


def test_migration_failure_degrades_without_crashing(server, caplog):
    _FakeDB.fail_connect = True
    with caplog.at_level("ERROR"):
        server._migrate_schema()  # must not raise
    assert server._SCHEMA["ok"] is False
    assert sum(r.levelname == "ERROR" and "001_tags_trade_uid.sql" in r.getMessage()
               for r in caplog.records) == 1
    _FakeDB.fail_connect = False
    server._health_cache["at"] = 0.0
    assert call(server, "GET", "/health")[1]["schema"] == "needs_migration"


def test_migration_file_batches_are_guarded(server):
    batches = server._migration_batches(server._MIGRATIONS_DIR / "001_tags_trade_uid.sql")
    assert len(batches) >= 8
    for b in batches:
        if "ALTER TABLE" in b or "CREATE " in b and "INDEX" in b or "UPDATE" in b:
            assert "IF " in b, b


def test_reduced_mode_without_new_columns(server, monkeypatch):
    tok = login(server)
    monkeypatch.setitem(server._SCHEMA, "trade_cols", False)
    monkeypatch.setitem(server._SCHEMA, "ok", False)
    assert call(server, "PUT", f"/trades/Main/{U1}", TRADE, tok)[0] == 503
    assert call(server, "DELETE", f"/trades/Main/{U1}", token=tok)[0] == 503
    assert call(server, "PUT", "/trades/Main", {"account_name": "Main", "trades": [TRADE]}, tok)[1] == {"ok": True}
    (t,) = call(server, "GET", "/trades", token=tok)[1]
    assert t["uid"] == "" and t["tag"] == ""
